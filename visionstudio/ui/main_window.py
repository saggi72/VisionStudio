"""Main window: header (logo, recipe, tabs, role, START/STOP), stacked views, status footer."""
from __future__ import annotations

from ..core.i18n import t

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
                             QStackedWidget, QVBoxLayout, QWidget)

from .. import __version__
from . import theme
from ..core.auth import FULL_ACCESS_ROLE
from ..core.i18n import set_language, t
from .context import AppContext
from .devices_view import DevicesView
from .history_view import HistoryView
from .operator_view import OperatorView
from .reports_view import ReportsView
from .retrain_view import RetrainView
from .settings_view import SettingsView
from .studio_view import StudioView
from .users_view import LoginDialog

TABS = [("studio", "Studio Editor && Heatmap"), ("operator", "Operator Line"), ("retrain", "AI Active Retrain"),
        ("devices", "Thiết bị"), ("history", "Inspection Logs"), ("reports", "Xuất Báo Cáo"),
        ("settings", "Cài Đặt Hệ Thống")]


_RETIRED: list = []          # windows replaced by a rebuild, waiting for Qt to delete them
_LIVE: list = []             # the window in use; a strong Python reference (see keep_alive)


def keep_alive(window: "MainWindow") -> None:
    """Hold the main window from Python. A top-level window has no Qt parent, so without this
    reference the garbage collector would delete it while it is on screen. The Qt property is only
    a convenient way to find the current window; it does not keep the Python object alive."""
    _LIVE[:] = [window]
    QApplication.instance().setProperty("main_window", window)


class MainWindow(QMainWindow):
    def __init__(self, engine, store, recipe_path: str, previous: AppContext | None = None, tab: int = 0):
        super().__init__()
        self._replaced = False
        self.ctx = AppContext(engine, store, recipe_path, previous)
        self.setWindowTitle(f"VisionStudio v{__version__}")
        self.resize(1500, 880)
        root = QWidget()
        root.setObjectName("root")
        col = QVBoxLayout(root)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self._build_header())
        self.stack = QStackedWidget()
        self.views = {"studio": StudioView(self.ctx), "operator": OperatorView(self.ctx),
                      "retrain": RetrainView(self.ctx), "devices": DevicesView(self.ctx),
                      "history": HistoryView(self.ctx), "reports": ReportsView(self.ctx),
                      "settings": SettingsView(self.ctx)}
        for key, _title in TABS:
            self.stack.addWidget(self.views[key])
        col.addWidget(self.stack, 1)
        col.addWidget(self._build_footer())
        self.setCentralWidget(root)

        self.ctx.job_done.connect(self._on_job)
        self.ctx.engine_state.connect(self._on_state)
        self.ctx.role_changed.connect(lambda _r: self._update_session())
        self.ctx.recipe_changed.connect(self._update_recipe_label)
        self._on_state(engine.running)
        self._update_session()
        self._update_footer(None)
        self.foot_timer = QTimer(self)                 # device status can change without a job
        self.foot_timer.timeout.connect(lambda: self._update_footer(self.ctx.engine.last_job))
        self.foot_timer.start(2000)
        self.ctx.appearance_changed.connect(lambda: QTimer.singleShot(0, self._rebuild))
        list(self.tab_buttons.values())[tab].click()
        if previous is None:
            self.ctx.audit("APP_START", f"v{__version__}")

    # ---- header / footer -----------------------------------------------------------------
    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(50)
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(10)
        logo = QLabel(f"VISIONSTUDIO v{__version__}")
        logo.setObjectName("logo")
        self.recipe_label = QLabel()
        self.recipe_label.setObjectName("chip")
        self._update_recipe_label()
        row.addWidget(logo)
        row.addWidget(self.recipe_label)
        row.addStretch(1)
        self.tab_group = QButtonGroup(self)
        self.tab_buttons: dict[str, QPushButton] = {}
        for i, (key, title) in enumerate(TABS):
            btn = QPushButton(t(title))
            btn.setObjectName("tab")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _c, idx=i: self.stack.setCurrentIndex(idx))
            self.tab_group.addButton(btn)
            self.tab_buttons[key] = btn
            row.addWidget(btn)
        self.tab_buttons["studio"].setChecked(True)
        row.addStretch(1)
        self.role_btn = QPushButton()
        self.role_menu = QMenu(self.role_btn)
        self.role_btn.setMenu(self.role_menu)
        light = store_theme = self.ctx.store.get("theme") == "light"
        self.theme_btn = QPushButton(t("Tối") if light else t("Sáng"))
        self.theme_btn.setToolTip(t("Chuyển giao diện sáng / tối"))
        self.theme_btn.clicked.connect(lambda: self.ctx.set_theme("dark" if store_theme else "light"))
        english = self.ctx.store.get("language") == "en"
        self.lang_btn = QPushButton("VI" if english else "EN")
        self.lang_btn.setToolTip(t("Tiếng Việt / English"))
        self.lang_btn.clicked.connect(lambda: self.ctx.set_language("vi" if english else "en"))
        row.addWidget(self.theme_btn)
        row.addWidget(self.lang_btn)
        self.run_btn = QPushButton("START")
        self.run_btn.setFixedWidth(84)
        self.run_btn.clicked.connect(self._toggle_engine)
        row.addWidget(self.role_btn)
        row.addWidget(self.run_btn)
        return header

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setObjectName("footer")
        footer.setFixedHeight(24)
        row = QHBoxLayout(footer)
        row.setContentsMargins(12, 0, 12, 0)
        self.foot_left = QLabel()
        self.foot_right = QLabel()
        row.addWidget(self.foot_left, 1)
        row.addWidget(self.foot_right)
        return footer

    def _update_recipe_label(self) -> None:
        recipe = self.ctx.engine.recipe
        self.recipe_label.setText(f"Recipe: <b>{recipe.label}</b>" if recipe else "Recipe: -")

    def _update_footer(self, job) -> None:
        devs = self.ctx.engine.devices.info()
        good = sum(1 for d in devs if d["status"] == "Connected")
        state = "Engine: RUNNING" if self.ctx.engine.running else "Engine: STOPPED"
        self.foot_left.setText(t("{0}   |   Thiết bị kết nối: {1}/{2}   |   Trạm: {3}").format(state, good, len(devs), self.ctx.store.get('station_id')))
        cycle = f"Cycle Time: {job.cycle_ms:.1f} ms   |   " if job else ""
        self.foot_right.setText(t("{0}Audit trail: đang ghi").format(cycle))

    # ---- actions -------------------------------------------------------------------------
    def _update_session(self) -> None:
        """Refresh the account button, its menu and the START button after a login or rule change."""
        ctx = self.ctx
        name = ctx.user["username"] if ctx.logged_in else t("Chưa đăng nhập")
        preview = t(" → thử {0}").format(ctx.preview_role) if ctx.preview_role else ""
        self.role_btn.setText(f"{name} · {ctx.user['role']}{preview}")
        self.role_btn.setStyleSheet(f"color:{theme.WARN};" if ctx.preview_role or ctx.is_developer else "")
        menu = self.role_menu
        menu.clear()
        menu.addAction(t("Đăng nhập / đổi tài khoản…"), self._login)
        logout = menu.addAction(t("Đăng xuất"), ctx.logout)
        logout.setEnabled(ctx.logged_in)
        if ctx.is_developer:
            sub = menu.addMenu(t("Thử quyền của vai trò (Developer)"))
            for role in ctx.auth.roles():
                text = t("{0}  (vai trò thật)").format(role) if role == FULL_ACCESS_ROLE else role
                action = sub.addAction(text, lambda r=role: ctx.preview_as(r))
                action.setCheckable(True)
                action.setChecked(role == ctx.role)
        self.run_btn.setEnabled(ctx.can("engine.run"))
        self.run_btn.setToolTip("" if ctx.can("engine.run") else t("Vai trò hiện tại không có quyền chạy / dừng recipe"))

    def _login(self) -> None:
        LoginDialog(self.ctx, self).exec()

    def _toggle_engine(self) -> None:
        if not self.ctx.can("engine.run"):
            return
        engine = self.ctx.engine
        if engine.running:
            engine.stop()
            self.ctx.audit("ENGINE_STOP")
        else:
            engine.start()
            self.ctx.audit("ENGINE_START", engine.recipe.label if engine.recipe else "")

    def _on_state(self, running: bool) -> None:
        self.run_btn.setText("■ STOP" if running else "▶ START")
        self.run_btn.setObjectName("stop" if running else "start")
        self.run_btn.style().unpolish(self.run_btn)
        self.run_btn.style().polish(self.run_btn)
        self._update_footer(self.ctx.engine.last_job)

    def _on_job(self, job) -> None:
        status = job.result.status
        color = {"OK": theme.OK, "NG": theme.NG}.get(status, theme.WARN)
        btn = self.tab_buttons["operator"]
        btn.setText(f"Operator Line  [{status}]")
        btn.setStyleSheet("" if btn.isChecked() else f"color:{color};")
        self._update_footer(job)

    def _rebuild(self) -> None:
        """Theme or language changed: build a fresh window with the new look and keep the session."""
        app = QApplication.instance()
        set_language(self.ctx.store.get("language"))
        theme.apply_theme(app, self.ctx.store.get("theme"))
        new = MainWindow(self.ctx.engine, self.ctx.store, self.ctx.recipe_path, self.ctx, self.stack.currentIndex())
        if self.isMaximized():
            new.showMaximized()
        else:
            new.setGeometry(self.geometry())
            new.show()
        keep_alive(new)
        self.ctx.detach()
        self._replaced = True
        self.close()
        # Qt must destroy the old window from the event loop. If Python's garbage collector freed it
        # first (it can run in the middle of a paint), the application would crash - so keep a
        # reference until Qt reports the window as destroyed.
        _RETIRED.append(self)
        self.destroyed.connect(lambda _obj=None, old=self: old in _RETIRED and _RETIRED.remove(old))
        self.deleteLater()

    def closeEvent(self, event) -> None:
        if self._replaced:
            super().closeEvent(event)
            return
        if not self.views["studio"].confirm_discard():
            event.ignore()
            return
        self.ctx.audit("APP_EXIT")
        self.ctx.engine.stop()
        super().closeEvent(event)