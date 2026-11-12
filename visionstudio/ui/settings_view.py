"""Settings tab: station config, accounts + permission rules, audit trail, storage retention."""
from __future__ import annotations

from ..core.i18n import t

from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox,
                             QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..core.i18n import LANGUAGES
from ..core.node_base import PLUGIN_ERRORS, REGISTRY
from . import theme
from .context import AppContext
from .users_view import AccountsPage
from .widgets import Card, label, view_header


class SettingsView(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("view")
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 24, 24, 24)
        col.addWidget(view_header(t("Cài đặt hệ thống"), t("Thông số trạm, phân quyền người dùng, nhật ký thay đổi và chính sách lưu ảnh")))
        tabs = QTabWidget()
        tabs.addTab(self._general(), t("Cấu hình chung"))
        tabs.addTab(AccountsPage(ctx), t("Tài khoản && Phân quyền"))
        tabs.addTab(self._audit(), "Audit trail")
        tabs.addTab(self._storage(), t("Lưu trữ && Retention"))
        tabs.currentChanged.connect(lambda _i: self._load_audit())
        col.addWidget(tabs, 1)
        ctx.role_changed.connect(lambda _r: self._apply_role())
        self._apply_role()

    def _apply_role(self) -> None:
        allowed = self.ctx.can("settings.edit")
        for w in self.admin_widgets:
            w.setEnabled(allowed)
        self.role_note.setText("" if allowed else t("Cần quyền 'Cài đặt hệ thống' để thay đổi."))

    def _spin(self, key: str, lo: int, hi: int) -> QSpinBox:
        w = QSpinBox()
        w.setRange(lo, hi)
        w.setValue(self.ctx.store.get(key, int))
        w.valueChanged.connect(lambda v, k=key: self._save(k, v))
        self.admin_widgets.append(w)
        return w

    def _dspin(self, key: str) -> QDoubleSpinBox:
        w = QDoubleSpinBox()
        w.setRange(0.0, 1.0)
        w.setSingleStep(0.05)
        w.setValue(self.ctx.store.get(key, float))
        w.valueChanged.connect(lambda v, k=key: self._save(k, round(v, 2)))
        self.admin_widgets.append(w)
        return w

    def _save(self, key: str, value) -> None:
        self.ctx.store.set(key, value)
        self.ctx.audit("CHANGE_SETTING", f"{key} = {value}")

    def _general(self) -> QWidget:
        self.admin_widgets: list[QWidget] = []
        page = QWidget()
        col = QVBoxLayout(page)
        card = Card()
        card.setMaximumWidth(680)
        card.box.addWidget(label(t("THÔNG SỐ TRẠM"), "section"))
        form = QFormLayout()
        station = QLineEdit(self.ctx.store.get("station_id"))
        station.editingFinished.connect(lambda: self._save("station_id", station.text()))
        self.admin_widgets.append(station)
        form.addRow(t("Tên trạm (Station ID)"), station)
        form.addRow(t("Chu kỳ trigger phần mềm (ms)"), self._spin("interval_ms", 20, 60000))
        form.addRow(t("Vùng không chắc chắn - cận dưới"), self._dspin("unc_lo"))
        form.addRow(t("Vùng không chắc chắn - cận trên"), self._dspin("unc_hi"))
        card.box.addLayout(form)
        self.role_note = label("", "dim")
        card.box.addWidget(self.role_note)
        col.addWidget(card)
        look = Card()
        look.setMaximumWidth(680)
        look.box.addWidget(label(t("GIAO DIỆN"), "section"))
        form = QFormLayout()
        self.theme_box = QComboBox()
        self.theme_box.addItem(t("Tối (nền tối, chữ sáng)"), "dark")
        self.theme_box.addItem(t("Sáng (nền sáng, chữ tối)"), "light")
        self.theme_box.setCurrentIndex(self.theme_box.findData(self.ctx.store.get("theme")))
        self.theme_box.activated.connect(lambda _i: self.ctx.set_theme(self.theme_box.currentData()))
        self.lang_box = QComboBox()
        for code, name in LANGUAGES.items():
            self.lang_box.addItem(name, code)
        self.lang_box.setCurrentIndex(self.lang_box.findData(self.ctx.store.get("language")))
        self.lang_box.activated.connect(lambda _i: self.ctx.set_language(self.lang_box.currentData()))
        form.addRow(t("Chế độ màu"), self.theme_box)
        form.addRow(t("Ngôn ngữ"), self.lang_box)
        look.box.addLayout(form)
        look.box.addWidget(label(t("Mọi tài khoản đều đổi được. Lựa chọn được lưu cho lần mở sau."), "dim"))
        col.addWidget(look)
        plug = Card()
        plug.setMaximumWidth(680)
        plug.box.addWidget(label("PLUGIN NODE", "section"))
        plug.box.addWidget(label(t("{0} loại node đã nạp: ").format(len(REGISTRY)) + ", ".join(sorted(REGISTRY)), "sub", wrap=True))
        if PLUGIN_ERRORS:
            err = label(t("Plugin bị bỏ qua:\n") + "\n".join(PLUGIN_ERRORS), wrap=True)
            err.setStyleSheet(f"color:{theme.WARN};")
            plug.box.addWidget(err)
        col.addWidget(plug)
        col.addStretch(1)
        return page

    def _audit(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        audit = Card()
        head = QHBoxLayout()
        head.addWidget(label(t("NHẬT KÝ THAY ĐỔI (AUDIT TRAIL)"), "section"), 1)
        refresh = QPushButton(t("Làm mới"))
        refresh.clicked.connect(self._load_audit)
        head.addWidget(refresh)
        audit.box.addLayout(head)
        self.audit_table = QTableWidget(0, 4)
        self.audit_table.setHorizontalHeaderLabels([t("THỜI GIAN"), t("TÀI KHOẢN (VAI TRÒ)"), t("HÀNH ĐỘNG"), t("CHI TIẾT")])
        self.audit_table.verticalHeader().setVisible(False)
        self.audit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.audit_table.setShowGrid(False)
        self.audit_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.audit_table.setStyleSheet(f"font-family:{theme.MONO};")
        audit.box.addWidget(self.audit_table, 1)
        col.addWidget(audit, 1)
        return page

    def _load_audit(self) -> None:
        rows = self.ctx.store.audit_rows()
        self.audit_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                self.audit_table.setItem(r, c, QTableWidgetItem(str(text)))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._load_audit()

    def _storage(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        card = Card()
        card.setMaximumWidth(680)
        card.box.addWidget(label(t("CHÍNH SÁCH LƯU ẢNH"), "section"))
        form = QFormLayout()
        form.addRow(t("Giữ ảnh NG / ERROR (ngày, PNG không mất dữ liệu)"), self._spin("ng_days", 1, 3650))
        form.addRow(t("Giữ ảnh OK mẫu (ngày, JPEG)"), self._spin("ok_days", 1, 3650))
        form.addRow(t("Lưu 1 ảnh OK trong mỗi N ảnh"), self._spin("ok_sample_n", 1, 100000))
        form.addRow(t("Số mẫu tối đa trong kho retrain"), self._spin("buffer_max", 10, 100000))
        card.box.addLayout(form)
        card.box.addWidget(label(t("Thư mục dữ liệu: {0}").format(self.ctx.store.dir.resolve()), "dim", wrap=True))
        clean = QPushButton(t("Dọn ảnh quá hạn ngay"))
        clean.clicked.connect(self._cleanup)
        self.admin_widgets.append(clean)
        row = QHBoxLayout()
        row.addWidget(clean)
        row.addStretch(1)
        card.box.addLayout(row)
        col.addWidget(card)
        col.addStretch(1)
        return page

    def _cleanup(self) -> None:
        n = self.ctx.store.cleanup()
        self.ctx.audit("CLEANUP_ARCHIVE", f"{n} files")
        QMessageBox.information(self, t("Dọn ảnh"), t("Đã xóa {0} ảnh quá hạn.").format(n))