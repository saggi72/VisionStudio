"""Reports tab: KPI cards, Pareto of defect reasons, export to Excel and PDF."""
from __future__ import annotations

from ..core.i18n import t

from datetime import datetime

from PyQt6.QtGui import QTextDocument
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget

from . import theme
from .context import AppContext
from .widgets import Card, StatCard, label, view_header



class ReportsView(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("view")
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 24, 24, 24)
        col.setSpacing(16)
        xlsx = QPushButton(t("Xuất Excel (.xlsx)"))
        xlsx.clicked.connect(self._export_xlsx)
        pdf = QPushButton(t("Xuất PDF báo cáo"))
        pdf.setObjectName("primary")
        pdf.clicked.connect(self._export_pdf)
        for btn in (xlsx, pdf):
            btn.setEnabled(ctx.can("report.export"))
            ctx.role_changed.connect(lambda _r, b=btn: b.setEnabled(ctx.can("report.export")))
        col.addWidget(view_header(t("Báo cáo và Pareto lỗi"), t("Thống kê từ toàn bộ dữ liệu kiểm tra đã lưu trên trạm"), xlsx, pdf))
        row = QHBoxLayout()
        row.setSpacing(14)
        self.c_total = StatCard(t("TỔNG SẢN PHẨM"))
        self.c_ok = StatCard(t("ĐẠT CHUẨN (OK)"), theme.OK)
        self.c_ng = StatCard(t("LỖI (NG)"), theme.NG)
        self.c_yield = StatCard(t("TỶ LỆ YIELD"), theme.INFO)
        for c in (self.c_total, self.c_ok, self.c_ng, self.c_yield):
            row.addWidget(c)
        col.addLayout(row)
        self.pareto_card = Card()
        self.pareto_card.box.addWidget(label(t("BIỂU ĐỒ PARETO NGUYÊN NHÂN LỖI"), "section"))
        self.pareto_box = QVBoxLayout()
        self.pareto_box.setSpacing(12)
        self.pareto_card.box.addLayout(self.pareto_box)
        col.addWidget(self.pareto_card)
        col.addStretch(1)
        ctx.job_done.connect(lambda _job: self.isVisible() and self.refresh())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def _data(self):
        s = self.ctx.store.counts()
        y = 100.0 * s["ok"] / s["total"] if s["total"] else 0.0
        return s, y, self.ctx.store.pareto()

    def refresh(self) -> None:
        s, y, pareto = self._data()
        self.c_total.set_value(f"{s['total']:,}")
        self.c_ok.set_value(f"{s['ok']:,}")
        self.c_ng.set_value(f"{s['ng']:,}")
        self.c_yield.set_value(f"{y:.2f}%")
        while self.pareto_box.count():
            item = self.pareto_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        total_bad = sum(n for _r, n in pareto) or 1
        if not pareto:
            self.pareto_box.addWidget(label(t("Chưa có lỗi nào được ghi nhận."), "dim"))
        for i, (reason, n) in enumerate(pareto):
            colors = [theme.NG, theme.WARN, theme.INFO, *theme.BAR_EXTRA]
            color = colors[i % len(colors)]
            w = QWidget()
            box = QVBoxLayout(w)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(4)
            line = QHBoxLayout()
            line.addWidget(QLabel(f"{i + 1}. {reason}"), 1)
            cnt = QLabel(t("{0} lỗi ({1:.1f}%)").format(n, 100 * n / total_bad))
            cnt.setStyleSheet(f"color:{color}; font-family:{theme.MONO}; font-weight:bold;")
            line.addWidget(cnt)
            bar = QProgressBar()
            bar.setRange(0, total_bad)
            bar.setValue(n)
            bar.setTextVisible(False)
            bar.setStyleSheet(f"QProgressBar::chunk {{ background:{color}; border-radius:4px; }}")
            box.addLayout(line)
            box.addWidget(bar)
            self.pareto_box.addWidget(w)

    def _export_xlsx(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError:
            QMessageBox.information(self, t("Thiếu thư viện"), t("Cần cài openpyxl: pip install openpyxl"))
            return
        path, _ = QFileDialog.getSaveFileName(self, t("Xuất Excel"), "bao_cao_kiem_tra.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        s, y, pareto = self._data()
        wb = Workbook()
        ws = wb.active
        ws.title = "Tong hop"
        for line in ([t("Trạm"), self.ctx.store.get("station_id")], [t("Thời điểm xuất"), datetime.now().strftime("%Y-%m-%d %H:%M")],
                     [t("Tổng"), s["total"]], ["OK", s["ok"]], ["NG", s["ng"]], ["ERROR", s["error"]], ["Yield (%)", round(y, 2)],
                     [], [t("Nguyên nhân"), t("Số lỗi")], *[[r, n] for r, n in pareto]):
            ws.append(line)
        ws2 = wb.create_sheet("Chi tiet")
        ws2.append(["Job", t("Thời gian"), "Recipe", "Serial", t("Kết quả"), t("Lý do"), "Cycle ms", "Detections", t("Ảnh")])
        for row in self.ctx.store.query(limit=1_000_000):
            ws2.append(list(row))
        wb.save(path)
        self.ctx.audit("EXPORT_XLSX", path)

    def _export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, t("Xuất PDF"), "bao_cao_kiem_tra.pdf", "PDF (*.pdf)")
        if path:
            self.write_pdf(path)
            self.ctx.audit("EXPORT_PDF", path)

    def write_pdf(self, path: str) -> None:
        s, y, pareto = self._data()
        total_bad = sum(n for _r, n in pareto) or 1
        rows = "".join(f"<tr><td>{i + 1}</td><td>{r}</td><td align='right'>{n}</td>"
                       f"<td align='right'>{100 * n / total_bad:.1f}%</td></tr>" for i, (r, n) in enumerate(pareto))
        recipe = self.ctx.engine.recipe.label if self.ctx.engine.recipe else ""
        html = (f"<h2>{t('Báo cáo kiểm tra')} - {self.ctx.store.get('station_id')}</h2>"
                f"<p>Recipe: {recipe}<br>{t('Thời điểm xuất')}: {datetime.now():%Y-%m-%d %H:%M}</p>"
                "<table border='1' cellspacing='0' cellpadding='6'>"
                f"<tr><th>{t('Tổng')}</th><th>OK</th><th>NG</th><th>ERROR</th><th>Yield</th></tr>"
                f"<tr><td align='right'>{s['total']}</td><td align='right'>{s['ok']}</td>"
                f"<td align='right'>{s['ng']}</td><td align='right'>{s['error']}</td>"
                f"<td align='right'>{y:.2f}%</td></tr></table>"
                f"<h3>{t('Pareto nguyên nhân lỗi')}</h3>"
                "<table border='1' cellspacing='0' cellpadding='6'>"
                f"<tr><th>#</th><th>{t('Nguyên nhân')}</th><th>{t('Số lỗi')}</th><th>{t('Tỷ lệ')}</th></tr>{rows}</table>")
        doc = QTextDocument()
        doc.setHtml(html)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        doc.print(printer)