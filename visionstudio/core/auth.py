"""Accounts, roles and permission rules (Qt-free).

- A role is a named set of permissions. The rule matrix is stored in the DB and can be edited.
- The Developer role always has every permission and cannot be restricted (for testing).
- Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes, never in clear text.
"""
from __future__ import annotations

from .i18n import t

import hashlib
import hmac
import os
import re
from datetime import datetime

PERMISSIONS: list[tuple[str, str]] = [
    ("engine.run", "Chạy / dừng recipe"),
    ("recipe.edit", "Chỉnh sửa node, mở / lưu recipe"),
    ("devices.manage", "Thêm, sửa, kết nối lại thiết bị"),
    ("blocks.edit", "Tạo, sửa, xóa block Python"),
    ("model.train", "Xuất dataset, fine-tune model"),
    ("report.export", "Xuất báo cáo, CSV"),
    ("settings.edit", "Cài đặt hệ thống, retention, dọn ảnh"),
    ("users.manage", "Quản lý tài khoản và rule phân quyền"),
]
ALL_PERMS = {key for key, _ in PERMISSIONS}
FULL_ACCESS_ROLE = "Developer"
GUEST_ROLE = "Operator"
BUILTIN_ROLES: dict[str, set[str]] = {
    "Operator": {"engine.run"},
    "Engineer": {"engine.run", "recipe.edit", "devices.manage", "model.train", "report.export"},
    "Admin": set(ALL_PERMS),
    "Developer": set(ALL_PERMS),
}
# First-run accounts. Change these passwords before the tool leaves the test bench.
DEFAULT_USERS = [("engineer", "Kỹ sư mặc định", "Engineer", "1111"),
                 ("admin", "Quản trị mặc định", "Admin", "0000"),
                 ("dev", "Developer (test)", "Developer", "dev1234")]
MIN_PASSWORD = 4
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{2,32}$")


class AuthError(Exception):
    """Raised with a user-facing message when a rule is violated."""


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000).hex()


class AuthManager:
    def __init__(self, store):
        self.db, self.lock = store.db, store.lock
        with self.lock:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS roles(name TEXT PRIMARY KEY, perms TEXT, builtin INTEGER);
                CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, full_name TEXT, role TEXT,
                    salt TEXT, pw_hash TEXT, active INTEGER, created TEXT);
            """)
            if not self.db.execute("SELECT 1 FROM roles LIMIT 1").fetchone():
                for name, perms in BUILTIN_ROLES.items():
                    self.db.execute("INSERT INTO roles VALUES(?,?,1)", (name, ",".join(sorted(perms))))
            else:
                self._grant_new_permissions(store)
            store.set("auth_known_perms", ",".join(sorted(ALL_PERMS)))
            if not self.db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                for username, full_name, role, password in DEFAULT_USERS:
                    self._insert_user(username, full_name, role, password)
            self.db.commit()

    def _grant_new_permissions(self, store) -> None:
        """A newer version added permissions: give them to the built-in roles that have them by default.
        (Role rules live in the database, so an existing database would otherwise never get them.)"""
        known = set(store.get("auth_known_perms").split(",")) - {""}
        if not known:                                      # database from before this bookkeeping existed
            known = ALL_PERMS - {"blocks.edit"}
        for perm in ALL_PERMS - known:
            for role, defaults in BUILTIN_ROLES.items():
                if perm in defaults:
                    row = self.db.execute("SELECT perms FROM roles WHERE name=?", (role,)).fetchone()
                    if row is not None:
                        perms = {p for p in (row[0] or "").split(",") if p} | {perm}
                        self.db.execute("UPDATE roles SET perms=? WHERE name=?", (",".join(sorted(perms)), role))

    # ---- roles and rules -----------------------------------------------------------------
    def roles(self) -> dict[str, set[str]]:
        with self.lock:
            rows = self.db.execute("SELECT name, perms FROM roles ORDER BY builtin DESC, rowid").fetchall()
        out = {name: {p for p in (perms or "").split(",") if p in ALL_PERMS} for name, perms in rows}
        out[FULL_ACCESS_ROLE] = set(ALL_PERMS)
        return out

    def is_builtin(self, role: str) -> bool:
        return role in BUILTIN_ROLES

    def role_perms(self, role: str) -> set[str]:
        return self.roles().get(role, set())

    def set_role_perm(self, role: str, perm: str, allowed: bool) -> None:
        if role == FULL_ACCESS_ROLE:
            raise AuthError(t("Vai trò Developer luôn có toàn quyền, không chỉnh được."))
        if perm not in ALL_PERMS or role not in self.roles():
            raise AuthError(t("Vai trò hoặc quyền không tồn tại."))
        perms = self.role_perms(role)
        perms.add(perm) if allowed else perms.discard(perm)
        with self.lock:
            self.db.execute("UPDATE roles SET perms=? WHERE name=?", (",".join(sorted(perms)), role))
            self._commit_if_manageable()

    def add_role(self, name: str, copy_from: str = GUEST_ROLE) -> None:
        name = name.strip()
        if not _NAME_RE.match(name):
            raise AuthError(t("Tên vai trò gồm 2-32 ký tự: chữ không dấu, số, '_', '.', '-'."))
        if name.lower() in (r.lower() for r in self.roles()):
            raise AuthError(t("Vai trò '{0}' đã tồn tại.").format(name))
        perms = self.role_perms(copy_from)
        with self.lock:
            self.db.execute("INSERT INTO roles VALUES(?,?,0)", (name, ",".join(sorted(perms))))
            self.db.commit()

    def delete_role(self, name: str) -> None:
        if self.is_builtin(name):
            raise AuthError(t("Không xóa được vai trò có sẵn."))
        with self.lock:
            if self.db.execute("SELECT 1 FROM users WHERE role=?", (name,)).fetchone():
                raise AuthError(t("Vẫn còn tài khoản dùng vai trò này."))
            self.db.execute("DELETE FROM roles WHERE name=?", (name,))
            self.db.commit()

    # ---- users ---------------------------------------------------------------------------
    def users(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT username, full_name, role, active, created FROM users "
                                   "ORDER BY created, username").fetchall()
        return [dict(zip(("username", "full_name", "role", "active", "created"), r)) for r in rows]

    def user(self, username: str) -> dict | None:
        return next((u for u in self.users() if u["username"] == username.strip().lower()), None)

    def verify(self, username: str, password: str) -> dict | None:
        """Return the user when the password matches and the account is active, else None."""
        with self.lock:
            row = self.db.execute("SELECT salt, pw_hash, active FROM users WHERE username=?",
                                  (username.strip().lower(),)).fetchone()
        if not row or not row[2]:
            return None
        if not hmac.compare_digest(_hash(password, bytes.fromhex(row[0])), row[1]):
            return None
        return self.user(username)

    def create_user(self, username: str, full_name: str, role: str, password: str, actor_role: str = "") -> None:
        username = username.strip().lower()
        if not _NAME_RE.match(username):
            raise AuthError(t("Tên đăng nhập gồm 2-32 ký tự: chữ không dấu, số, '_', '.', '-'."))
        if self.user(username):
            raise AuthError(t("Tài khoản '{0}' đã tồn tại.").format(username))
        self._check_role_grant(role, actor_role)
        self._check_password(password)
        with self.lock:
            self._insert_user(username, full_name.strip(), role, password)
            self.db.commit()

    def update_user(self, username: str, full_name: str | None = None, role: str | None = None,
                    active: bool | None = None, actor_role: str = "") -> None:
        user = self._require(username, actor_role)
        if role is not None and role != user["role"]:
            self._check_role_grant(role, actor_role)
        with self.lock:
            self.db.execute("UPDATE users SET full_name=?, role=?, active=? WHERE username=?",
                            (user["full_name"] if full_name is None else full_name.strip(),
                             user["role"] if role is None else role,
                             user["active"] if active is None else int(active), user["username"]))
            self._commit_if_manageable()

    def set_password(self, username: str, password: str, actor_role: str = "") -> None:
        user = self._require(username, actor_role)
        self._check_password(password)
        salt = os.urandom(16)
        with self.lock:
            self.db.execute("UPDATE users SET salt=?, pw_hash=? WHERE username=?",
                            (salt.hex(), _hash(password, salt), user["username"]))
            self.db.commit()

    def delete_user(self, username: str, actor_role: str = "") -> None:
        user = self._require(username, actor_role)
        with self.lock:
            self.db.execute("DELETE FROM users WHERE username=?", (user["username"],))
            self._commit_if_manageable()

    # ---- rules ---------------------------------------------------------------------------
    def _insert_user(self, username: str, full_name: str, role: str, password: str) -> None:
        salt = os.urandom(16)
        self.db.execute("INSERT INTO users VALUES(?,?,?,?,?,1,?)",
                        (username, full_name, role, salt.hex(), _hash(password, salt),
                         datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    def _require(self, username: str, actor_role: str) -> dict:
        user = self.user(username)
        if user is None:
            raise AuthError(t("Không có tài khoản '{0}'.").format(username))
        if user["role"] == FULL_ACCESS_ROLE and actor_role and actor_role != FULL_ACCESS_ROLE:
            raise AuthError(t("Chỉ Developer được thay đổi tài khoản Developer."))
        return user

    def _check_role_grant(self, role: str, actor_role: str) -> None:
        if role not in self.roles():
            raise AuthError(t("Không có vai trò '{0}'.").format(role))
        if role == FULL_ACCESS_ROLE and actor_role and actor_role != FULL_ACCESS_ROLE:
            raise AuthError(t("Chỉ Developer được cấp vai trò Developer."))

    @staticmethod
    def _check_password(password: str) -> None:
        if len(password) < MIN_PASSWORD:
            raise AuthError(t("Mật khẩu cần ít nhất {0} ký tự.").format(MIN_PASSWORD))

    def _commit_if_manageable(self) -> None:
        """Refuse any change that would leave nobody able to manage accounts (lock-out)."""
        roles = self.roles()
        rows = self.db.execute("SELECT role FROM users WHERE active=1").fetchall()
        if any("users.manage" in roles.get(r[0], set()) for r in rows):
            self.db.commit()
            return
        self.db.rollback()
        raise AuthError(t("Phải còn ít nhất một tài khoản đang hoạt động có quyền quản lý tài khoản."))