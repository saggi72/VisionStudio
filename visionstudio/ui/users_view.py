"""Login dialog, account dialog, and the 'Tài khoản & Phân quyền' page of the Settings tab."""
from __future__ import annotations

from ..core.i18n import t

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                             QHeaderView, QInputDialog, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.auth import FULL_ACCESS_ROLE, MIN_PASSWORD, PERMISSIONS, AuthError
from . import theme
from .context import AppContext
from .widgets import Card, label


def _password_edit(placeholder: str = "") -> QLineEdit:
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setPlaceholderText(placeholder)
    return edit


class LoginDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(t("Đăng nhập"))
        self.setMinimumWidth(340)
        col = QVBoxLayout(self)
        form = QFormLayout()
        self.user = QComboBox()
        self.user.setEditable(True)
        self.user.addItems([u["username"] for u in ctx.auth.users() if u["active"]])
        self.user.setCurrentIndex(-1)
        self.user.setEditText("")
        self.password = _password_edit()
        form.addRow(t("Tài khoản"), self.user)
        form.addRow(t("Mật khẩu"), self.password)
        col.addLayout(form)
        self.error = label("", wrap=True)
        self.error.setStyleSheet(f"color:{theme.NG};")
        col.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("Đăng nhập"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Hủy"))
        buttons.accepted.connect(self._try)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

    def _try(self) -> None:
        if self.ctx.login(self.user.currentText(), self.password.text()):
            self.accept()
            return
        self.error.setText(t("Sai tài khoản hoặc mật khẩu, hoặc tài khoản đã bị khóa."))
        self.password.clear()
        self.password.setFocus()


class UserDialog(QDialog):
    """Create an account (user=None) or edit name / role of an existing one."""

    def __init__(self, ctx: AppContext, user: dict | None = None, parent=None):
        super().__init__(parent)
        self.ctx, self.editing = ctx, user
        self.setWindowTitle(t("Sửa tài khoản") if user else t("Tạo tài khoản"))
        self.setMinimumWidth(380)
        col = QVBoxLayout(self)
        form = QFormLayout()
        self.username = QLineEdit(user["username"] if user else "")
        self.username.setEnabled(user is None)
        self.full_name = QLineEdit(user["full_name"] if user else "")
        self.role = QComboBox()
        roles = [r for r in ctx.auth.roles() if r != FULL_ACCESS_ROLE or ctx.user["role"] == FULL_ACCESS_ROLE]
        self.role.addItems(roles)
        self.role.setCurrentText(user["role"] if user else "Operator")
        form.addRow(t("Tên đăng nhập"), self.username)
        form.addRow(t("Họ tên"), self.full_name)
        form.addRow(t("Vai trò"), self.role)
        self.pw1 = self.pw2 = None
        if user is None:
            self.pw1 = _password_edit(t("ít nhất {0} ký tự").format(MIN_PASSWORD))
            self.pw2 = _password_edit()
            form.addRow(t("Mật khẩu"), self.pw1)
            form.addRow(t("Nhập lại mật khẩu"), self.pw2)
        col.addLayout(form)
        self.error = label("", wrap=True)
        self.error.setStyleSheet(f"color:{theme.NG};")
        col.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("Lưu"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Hủy"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

    def _save(self) -> None:
        auth, actor = self.ctx.auth, self.ctx.user["role"]
        try:
            if self.editing is None:
                if self.pw1.text() != self.pw2.text():
                    raise AuthError(t("Hai lần nhập mật khẩu không giống nhau."))
                auth.create_user(self.username.text(), self.full_name.text(), self.role.currentText(),
                                 self.pw1.text(), actor_role=actor)
                self.ctx.audit("CREATE_USER", f"{self.username.text().strip().lower()} ({self.role.currentText()})")
            else:
                auth.update_user(self.editing["username"], full_name=self.full_name.text(),
                                 role=self.role.currentText(), actor_role=actor)
                self.ctx.audit("UPDATE_USER", f"{self.editing['username']} -> {self.role.currentText()}")
        except AuthError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


def ask_new_password(parent, title: str) -> str | None:
    """Ask twice for a new password. Returns None when cancelled or the two entries differ."""
    pw1, ok = QInputDialog.getText(parent, title, t("Mật khẩu mới (ít nhất {0} ký tự):").format(MIN_PASSWORD),
                                   QLineEdit.EchoMode.Password)
    if not ok:
        return None
    pw2, ok = QInputDialog.getText(parent, title, t("Nhập lại mật khẩu mới:"), QLineEdit.EchoMode.Password)
    if not ok:
        return None
    if pw1 != pw2:
        QMessageBox.warning(parent, title, t("Hai lần nhập không giống nhau."))
        return None
    return pw1


class AccountsPage(QWidget):
    """Accounts table + editable permission-rule matrix. Editing needs the 'users.manage' permission."""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self._filling = False
        col = QVBoxLayout(self)

        users = Card()
        head = QHBoxLayout()
        head.addWidget(label(t("TÀI KHOẢN"), "section"), 1)
        self.manage_buttons: list[QPushButton] = []
        for text, slot, primary in ((t("Tạo tài khoản"), self._create, True), (t("Sửa"), self._edit, False),
                                    (t("Đặt lại mật khẩu"), self._reset_password, False),
                                    (t("Khóa / Mở khóa"), self._toggle_active, False), (t("Xóa"), self._delete, False)):
            btn = QPushButton(text)
            if primary:
                btn.setObjectName("primary")
            btn.clicked.connect(slot)
            head.addWidget(btn)
            self.manage_buttons.append(btn)
        self.own_pw_btn = QPushButton(t("Đổi mật khẩu của tôi"))
        self.own_pw_btn.clicked.connect(self._change_own_password)
        head.addWidget(self.own_pw_btn)
        users.box.addLayout(head)
        self.user_table = QTableWidget(0, 5)
        self.user_table.setHorizontalHeaderLabels([t("TÊN ĐĂNG NHẬP"), t("HỌ TÊN"), t("VAI TRÒ"), t("TRẠNG THÁI"), t("NGÀY TẠO")])
        self.user_table.verticalHeader().setVisible(False)
        self.user_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.user_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.user_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.user_table.setShowGrid(False)
        self.user_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.user_table.doubleClicked.connect(lambda _i: self._edit())
        users.box.addWidget(self.user_table, 1)
        col.addWidget(users, 1)

        rules = Card()
        head = QHBoxLayout()
        head.addWidget(label(t("RULE PHÂN QUYỀN THEO VAI TRÒ"), "section"), 1)
        self.add_role_btn = QPushButton(t("Thêm vai trò"))
        self.add_role_btn.clicked.connect(self._add_role)
        self.del_role_btn = QPushButton(t("Xóa vai trò"))
        self.del_role_btn.clicked.connect(self._delete_role)
        head.addWidget(self.add_role_btn)
        head.addWidget(self.del_role_btn)
        rules.box.addLayout(head)
        self.matrix = QTableWidget()
        self.matrix.verticalHeader().setVisible(False)
        self.matrix.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.matrix.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.matrix.setShowGrid(False)
        rules.box.addWidget(self.matrix)
        self.note = label("", "dim", wrap=True)
        rules.box.addWidget(self.note)
        col.addWidget(rules)

        ctx.role_changed.connect(lambda _r: self.refresh())
        self.refresh()

    # ---- display -------------------------------------------------------------------------
    def refresh(self) -> None:
        can = self.ctx.can("users.manage")
        for btn in self.manage_buttons + [self.add_role_btn, self.del_role_btn]:
            btn.setEnabled(can)
        self.own_pw_btn.setEnabled(self.ctx.logged_in)
        self.note.setText(t("Tick để cấp quyền, thay đổi có hiệu lực ngay. Vai trò Developer luôn có toàn quyền.")
                          if can else t("Cần quyền 'Quản lý tài khoản và rule phân quyền' để thay đổi."))
        users = self.ctx.auth.users()
        self.user_table.setRowCount(len(users))
        for r, u in enumerate(users):
            cells = [u["username"], u["full_name"], u["role"], t("Hoạt động") if u["active"] else t("Đã khóa"), u["created"]]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                if c == 3:
                    item.setForeground(QColor(theme.OK if u["active"] else theme.NG))
                self.user_table.setItem(r, c, item)
        self._fill_matrix(can)

    def _fill_matrix(self, editable: bool) -> None:
        self._filling = True
        roles = self.ctx.auth.roles()
        self.matrix.clear()
        self.matrix.setRowCount(len(PERMISSIONS))
        self.matrix.setColumnCount(1 + len(roles))
        self.matrix.setHorizontalHeaderLabels([t("QUYỀN")] + [r.upper() for r in roles])
        header = self.matrix.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for r, (perm, text) in enumerate(PERMISSIONS):
            self.matrix.setItem(r, 0, QTableWidgetItem(t(text)))
            for c, (role, perms) in enumerate(roles.items(), start=1):
                box = QCheckBox()
                box.setChecked(perm in perms)
                box.setEnabled(editable and role != FULL_ACCESS_ROLE)
                box.toggled.connect(lambda on, ro=role, pe=perm: self._set_perm(ro, pe, on))
                holder = QWidget()
                lay = QHBoxLayout(holder)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lay.addWidget(box)
                self.matrix.setCellWidget(r, c, holder)
        self.matrix.setFixedHeight(42 + 32 * len(PERMISSIONS))
        self._filling = False

    def _selected(self) -> dict | None:
        row = self.user_table.currentRow()
        if row < 0:
            QMessageBox.information(self, t("Tài khoản"), t("Hãy chọn một tài khoản trong bảng."))
            return None
        return self.ctx.auth.user(self.user_table.item(row, 0).text())

    def _run(self, action, audit: tuple[str, str] | None = None) -> None:
        """Run an auth change, show rule violations, then refresh every view."""
        try:
            action()
        except AuthError as exc:
            QMessageBox.warning(self, t("Không thực hiện được"), str(exc))
        else:
            if audit:
                self.ctx.audit(*audit)
        QTimer.singleShot(0, self.ctx.rules_changed)   # deferred: the sender widget may be rebuilt

    # ---- account actions -----------------------------------------------------------------
    def _create(self) -> None:
        if UserDialog(self.ctx, parent=self).exec():
            self.ctx.rules_changed()

    def _edit(self) -> None:
        if not self.ctx.can("users.manage"):
            return
        user = self._selected()
        if user and UserDialog(self.ctx, user, parent=self).exec():
            self.ctx.rules_changed()

    def _reset_password(self) -> None:
        user = self._selected()
        if not user:
            return
        pw = ask_new_password(self, t("Đặt lại mật khẩu cho {0}").format(user['username']))
        if pw is not None:
            self._run(lambda: self.ctx.auth.set_password(user["username"], pw, actor_role=self.ctx.user["role"]),
                      ("RESET_PASSWORD", user["username"]))

    def _toggle_active(self) -> None:
        user = self._selected()
        if not user:
            return
        if user["username"] == self.ctx.user["username"]:
            QMessageBox.warning(self, t("Không thực hiện được"), t("Không thể tự khóa tài khoản đang đăng nhập."))
            return
        self._run(lambda: self.ctx.auth.update_user(user["username"], active=not user["active"],
                                                    actor_role=self.ctx.user["role"]),
                  ("UNLOCK_USER" if not user["active"] else "LOCK_USER", user["username"]))

    def _delete(self) -> None:
        user = self._selected()
        if not user:
            return
        if user["username"] == self.ctx.user["username"]:
            QMessageBox.warning(self, t("Không thực hiện được"), t("Không thể xóa tài khoản đang đăng nhập."))
            return
        if QMessageBox.question(self, t("Xóa tài khoản"), t("Xóa tài khoản '{0}'?").format(user['username'])) \
                != QMessageBox.StandardButton.Yes:
            return
        self._run(lambda: self.ctx.auth.delete_user(user["username"], actor_role=self.ctx.user["role"]),
                  ("DELETE_USER", user["username"]))

    def _change_own_password(self) -> None:
        name = self.ctx.user["username"]
        old, ok = QInputDialog.getText(self, t("Đổi mật khẩu"), t("Mật khẩu hiện tại:"), QLineEdit.EchoMode.Password)
        if not ok:
            return
        if self.ctx.auth.verify(name, old) is None:
            QMessageBox.warning(self, t("Đổi mật khẩu"), t("Mật khẩu hiện tại không đúng."))
            return
        pw = ask_new_password(self, t("Đổi mật khẩu"))
        if pw is not None:
            self._run(lambda: self.ctx.auth.set_password(name, pw), ("CHANGE_PASSWORD", name))

    # ---- rule actions --------------------------------------------------------------------
    def _set_perm(self, role: str, perm: str, allowed: bool) -> None:
        if self._filling:
            return
        self._run(lambda: self.ctx.auth.set_role_perm(role, perm, allowed),
                  ("CHANGE_RULE", f"{role}: {perm} = {'allow' if allowed else 'deny'}"))

    def _add_role(self) -> None:
        name, ok = QInputDialog.getText(self, t("Thêm vai trò"), t("Tên vai trò mới (không dấu, ví dụ QC_Leader):"))
        if not ok or not name.strip():
            return
        base, ok = QInputDialog.getItem(self, t("Thêm vai trò"), t("Sao chép quyền từ vai trò:"),
                                        [r for r in self.ctx.auth.roles() if r != FULL_ACCESS_ROLE], 0, False)
        if ok:
            self._run(lambda: self.ctx.auth.add_role(name, base), ("ADD_ROLE", f"{name.strip()} (from {base})"))

    def _delete_role(self) -> None:
        custom = [r for r in self.ctx.auth.roles() if not self.ctx.auth.is_builtin(r)]
        if not custom:
            QMessageBox.information(self, t("Xóa vai trò"), t("Chưa có vai trò tự tạo nào. Vai trò có sẵn không xóa được."))
            return
        name, ok = QInputDialog.getItem(self, t("Xóa vai trò"), t("Chọn vai trò cần xóa:"), custom, 0, False)
        if ok:
            self._run(lambda: self.ctx.auth.delete_role(name), ("DELETE_ROLE", name))