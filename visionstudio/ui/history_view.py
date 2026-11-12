"""Inspection history tab: filter, search, view the archived image, export CSV."""
from __future__ import annotations

from ..core.i18n import t

import csv
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .context import AppContext
from .widgets import ImageView, label, view_header

COLUMNS = ["Job ID", "Thời gian", "Recipe", "Serial", "Kết quả", "Lý do", "Cycle time", "Số detection", "Ảnh"]


class HistoryView(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.rows: list[tuple] = []
        self.setObjectName("view")
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 24, 24, 24)
        export = QPushButton(t("Xuất CSV"))
        export.clicked.connect(self._export)
        export.setEnabled(ctx.can("report.export"))
        ctx.role_changed.connect(lambda _r: export.setEnabled(ctx.can("report.export")))
        col.addWidget(view_header(t("Lịch sử kiểm tra"), t("Truy xuất theo recipe, serial và kết quả. Nhấp đúp để xem ảnh đã lưu."), export))
        bar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems([t("Tất cả"), "OK", "NG", "ERROR"])
        self.filter.currentTextChanged.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("Tìm theo serial hoặc lý do..."))
        self.search.textChanged.connect(self.refresh)
        self.info = label("", "dim")
        bar.addWidget(self.filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.info)
        col.addLayout(bar)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([t(c).upper() for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet(f"font-family:{theme.MONO};")
        self.table.cellDoubleClicked.connect(self._open_image)
        col.addWidget(self.table, 1)
        ctx.job_done.connect(lambda _job: self.isVisible() and self.refresh())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self, *_):
        result = self.filter.currentText()
        self.rows = self.ctx.store.query(None if result == t("Tất cả") else result, self.search.text(), 300)
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            job_no, ts, recipe, serial, res, reason, cycle, dets, image = row
            cells = [f"JOB-{job_no:05d}", ts, recipe, serial, res, reason, f"{cycle:.1f} ms", str(dets),
                     t("có") if image else ""]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 4:
                    item.setForeground(QColor(theme.result_color(res)))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                elif c == 3:
                    item.setForeground(QColor(theme.INFO))
                self.table.setItem(r, c, item)
        self.info.setText(t("{0} bản ghi mới nhất").format(len(self.rows)))

    def _open_image(self, row: int, _col: int) -> None:
        path = self.rows[row][8]
        if not path or not Path(path).exists():
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"JOB-{self.rows[row][0]:05d} · {self.rows[row][4]} · {self.rows[row][5]}")
        dlg.resize(1000, 460)
        box = QVBoxLayout(dlg)
        view = ImageView()
        view.set_file(path)
        box.addWidget(view)
        dlg.exec()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, t("Xuất CSV"), "inspections.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([t(c) for c in COLUMNS])
            writer.writerows(self.ctx.store.query(limit=1_000_000))
        self.ctx.audit("EXPORT_CSV", path)