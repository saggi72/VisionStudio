"""Shared application context: engine, store, login session, permission checks, Qt signals."""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from ..core.auth import FULL_ACCESS_ROLE, GUEST_ROLE, AuthManager

GUEST = {"username": "guest", "full_name": "Chưa đăng nhập", "role": GUEST_ROLE, "active": 1}


class AppContext(QObject):
    job_done = pyqtSignal(object)        # JobResult, emitted from the engine thread (queued to UI)
    engine_state = pyqtSignal(bool)
    role_changed = pyqtSignal(str)       # session or permission rules changed -> views re-check can()
    recipe_changed = pyqtSignal()       # another recipe was loaded, or it was saved
    dirty_changed = pyqtSignal(bool)     # the recipe has unsaved edits
    appearance_changed = pyqtSignal()    # theme or language changed -> the main window rebuilds itself

    def __init__(self, engine, store, recipe_path: str, previous: "AppContext | None" = None):
        super().__init__()
        self.engine, self.store, self.recipe_path = engine, store, recipe_path
        self.auth = AuthManager(store)
        self.user = dict(GUEST)
        self.dirty = False
        self.preview_role = ""           # Developer only: try the app with another role's rules
        if previous is not None:         # window rebuilt after a theme / language switch: keep the session
            self.user, self.preview_role, self.dirty = previous.user, previous.preview_role, previous.dirty
        self._hooks = (self.job_done.emit, self.engine_state.emit)
        engine.listeners.append(self._hooks[0])
        engine.state_listeners.append(self._hooks[1])

    def detach(self) -> None:
        """Stop receiving engine events (called on the context of a window that is being replaced)."""
        if self._hooks[0] in self.engine.listeners:
            self.engine.listeners.remove(self._hooks[0])
        if self._hooks[1] in self.engine.state_listeners:
            self.engine.state_listeners.remove(self._hooks[1])
        # Jobs already queued for this context must not reach views that are about to be deleted.
        for signal in (self.job_done, self.engine_state, self.role_changed, self.recipe_changed,
                       self.dirty_changed, self.appearance_changed):
            try:
                signal.disconnect()
            except TypeError:                # nothing was connected
                pass

    # ---- appearance ----------------------------------------------------------------------
    def set_theme(self, mode: str) -> None:
        if mode != self.store.get("theme"):
            self.store.set("theme", mode)
            self.audit("CHANGE_THEME", mode)
            self.appearance_changed.emit()

    def set_language(self, lang: str) -> None:
        if lang != self.store.get("language"):
            self.store.set("language", lang)
            self.audit("CHANGE_LANGUAGE", lang)
            self.appearance_changed.emit()

    # ---- session -------------------------------------------------------------------------
    @property
    def role(self) -> str:
        """Effective role: the previewed role when a Developer is testing, else the account's role."""
        return self.preview_role or self.user["role"]

    @property
    def is_developer(self) -> bool:
        return self.user["role"] == FULL_ACCESS_ROLE

    @property
    def logged_in(self) -> bool:
        return self.user["username"] != GUEST["username"]

    def login(self, username: str, password: str) -> bool:
        user = self.auth.verify(username, password)
        if user is None:
            self.audit("LOGIN_FAILED", username.strip().lower())
            return False
        self.user, self.preview_role = user, ""
        self.audit("LOGIN", f"{user['username']} ({user['role']})")
        self.role_changed.emit(self.role)
        return True

    def logout(self) -> None:
        if self.logged_in:
            self.audit("LOGOUT")
        self.user, self.preview_role = dict(GUEST), ""
        self.role_changed.emit(self.role)

    def preview_as(self, role: str) -> None:
        """Developer: switch the effective role without logging out ('' = back to Developer)."""
        if not self.is_developer:
            return
        self.preview_role = "" if role == FULL_ACCESS_ROLE else role
        self.audit("PREVIEW_ROLE", role or FULL_ACCESS_ROLE)
        self.role_changed.emit(self.role)

    def rules_changed(self) -> None:
        current = self.auth.user(self.user["username"]) if self.logged_in else None
        if self.logged_in and (current is None or not current["active"]):
            self.user, self.preview_role = dict(GUEST), ""
        elif current:
            self.user = current
        self.role_changed.emit(self.role)

    def set_dirty(self, dirty: bool = True) -> None:
        if dirty != self.dirty:
            self.dirty = dirty
            self.dirty_changed.emit(dirty)

    # ---- permissions ---------------------------------------------------------------------
    def can(self, perm: str) -> bool:
        return perm in self.auth.role_perms(self.role)

    def audit(self, action: str, detail: str = "") -> None:
        who = f"{self.user['username']} ({self.role})"
        self.store.audit(who, action, detail)