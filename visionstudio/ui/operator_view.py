"""Operator tab: big OK/NG verdict, live overlay image, shift KPIs. No editing here."""
from __future__ import annotations

from ..core.i18n import t

from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from . import theme
from .context import AppContext
from .widgets import Card, ImageView, label



class OperatorView(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("view")
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 24, 24, 24)
        col.setSpacing(18)

        self.banner = QFrame()
        b = QHBoxLayout(self.banner)
        b.setContentsMargins(28, 20, 28, 20)
        left = QVBoxLayout()
        left.addWidget(label(t("KẾT QUẢ KIỂM TRA"), "caption"))
        self.verdict = QLabel("--")
        self.reason = QLabel(t("Bấm START để bắt đầu"))
        left.addWidget(self.verdict)
        left.addWidget(self.reason)
        right = QVBoxLayout()
        right.addWidget(label("CYCLE TIME", "caption"))
        self.cycle = QLabel("-- ms")
        self.cycle.setStyleSheet(f"font-family:{theme.MONO}; font-size:28px; font-weight:bold;")
        self.serial = label("", "dim")
        right.addWidget(self.cycle)
        right.addWidget(self.serial)
        b.addLayout(left, 1)
        b.addLayout(right)
        col.addWidget(self.banner)
        self._style_banner("--")

        grid = QGridLayout()
        grid.setSpacing(18)
        cam = Card()
        cam.box.addWidget(label(t("Ảnh kiểm tra kèm overlay"), "section"))
        self.image = ImageView(t("[Chưa có ảnh]"), 300)
        cam.box.addWidget(self.image, 1)
        grid.addWidget(cam, 0, 0)

        kpi = Card()
        kpi.box.addWidget(label("SHIFT KPI", "section"))
        kpi.box.addWidget(label(t("TỔNG SỐ"), "caption"))
        self.total = self._num(theme.TEXT_STRONG, 30)
        kpi.box.addWidget(self.total)
        row = QHBoxLayout()
        self.ok = self._num(theme.OK, 22)
        self.ng = self._num(theme.NG, 22)
        self.err = self._num(theme.WARN, 22)
        for cap, w in ((t("ĐẠT (OK)"), self.ok), (t("LỖI (NG)"), self.ng), ("ERROR", self.err)):
            box = QVBoxLayout()
            box.addWidget(label(cap, "caption"))
            box.addWidget(w)
            row.addLayout(box)
        kpi.box.addLayout(row)
        yrow = QHBoxLayout()
        yrow.addWidget(label("YIELD", "caption"), 1)
        self.yield_label = QLabel("--")
        self.yield_label.setStyleSheet(f"color:{theme.OK}; font-weight:bold;")
        yrow.addWidget(self.yield_label)
        kpi.box.addLayout(yrow)
        self.yield_bar = QProgressBar()
        self.yield_bar.setRange(0, 1000)
        self.yield_bar.setTextVisible(False)
        kpi.box.addWidget(self.yield_bar)
        kpi.box.addStretch(1)
        kpi.setFixedWidth(340)
        grid.addWidget(kpi, 0, 1)
        col.addLayout(grid, 1)

        ctx.job_done.connect(self._on_job)
        self._update_stats()

    def _num(self, color: str, size: int) -> QLabel:
        lb = QLabel("0")
        lb.setStyleSheet(f"color:{color}; font-family:{theme.MONO}; font-size:{size}px; font-weight:900;")
        return lb

    def _style_banner(self, status: str) -> None:
        known = status in ("OK", "NG", "ERROR")
        bg, fg = theme.result_bg(status), theme.result_color(status) if known else theme.TEXT_DIM
        self.banner.setStyleSheet(f"QFrame {{ background:{bg}; border:2px solid {fg}; border-radius:12px; }}"
                                  "QLabel { border:none; background:transparent; }")
        self.verdict.setStyleSheet(f"color:{fg}; font-family:{theme.MONO}; font-size:54px; font-weight:900;")
        self.reason.setStyleSheet(f"font-family:{theme.MONO}; font-size:14px;")

    def _update_stats(self) -> None:
        s = self.ctx.engine.stats
        self.total.setText(f"{s['total']:,}")
        self.ok.setText(f"{s['ok']:,}")
        self.ng.setText(f"{s['ng']:,}")
        self.err.setText(f"{s['error']:,}")
        if s["total"]:
            y = s["ok"] / s["total"]
            self.yield_label.setText(f"{y * 100:.2f}%")
            self.yield_bar.setValue(int(y * 1000))

    def _on_job(self, job) -> None:
        self._update_stats()
        if not self.isVisible():
            return
        self._style_banner(job.result.status)
        self.verdict.setText(job.result.status)
        self.reason.setText(t("Lý do: ") + (", ".join(job.result.reasons) or "ALL_PASS"))
        self.cycle.setText(f"{job.cycle_ms:.1f} ms")
        self.serial.setText(f"{job.job_id} · {job.serial}")
        self.image.set_image(job.preview)