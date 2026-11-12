"""AI Active Retrain tab: uncertainty buffer -> YOLO dataset export -> optional fine-tune process."""
from __future__ import annotations

from ..core.i18n import t

import shutil

from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from . import theme
from .context import AppContext
from .widgets import Card, ImageView, label, view_header


class RetrainView(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.proc: QProcess | None = None
        self.setObjectName("view")
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 24, 24, 24)
        col.addWidget(view_header(t("Active Learning - gom mẫu khó và huấn luyện lại"),
                                  t("Ảnh có detection nằm trong vùng điểm số không chắc chắn được gom tự động kèm nhãn giả")))
        row = QHBoxLayout()
        row.setSpacing(18)

        buf = Card()
        buf.setFixedWidth(360)
        buf.box.addWidget(label(t("KHO MẪU KHÔNG CHẮC CHẮN"), "section"))
        self.count = QLabel("0")
        self.count.setStyleSheet(f"color:{theme.WARN}; font-family:{theme.MONO}; font-size:34px; font-weight:900;")
        buf.box.addWidget(self.count)
        self.range_label = label("", "dim", wrap=True)
        buf.box.addWidget(self.range_label)
        self.sample = ImageView(t("[Chưa có mẫu]"), 180)
        buf.box.addWidget(self.sample, 1)
        self.sample_name = label("", "dim")
        buf.box.addWidget(self.sample_name)
        row.addWidget(buf)

        train = Card()
        train.box.addWidget(label(t("XUẤT DATASET VÀ FINE-TUNE"), "section"))
        train.box.addWidget(label(
            t("Bước 1: xuất kho mẫu thành dataset định dạng YOLO (ảnh + nhãn + data.yaml).\n"
            "Bước 2: mở dataset bằng công cụ gán nhãn để sửa nhãn giả. Nhãn giả do chính model hiện tại "
            "sinh ra nên phải được người kiểm tra trước khi train.\n"
            "Bước 3: fine-tune bằng Ultralytics nếu máy đã cài (pip install ultralytics, giấy phép AGPL-3.0)."),
            "sub", wrap=True))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(f"font-family:{theme.MONO}; font-size:11px;")
        train.box.addWidget(self.log, 1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.export_btn = QPushButton(t("Xuất dataset YOLO"))
        self.export_btn.clicked.connect(self._export)
        self.train_btn = QPushButton(t("Bắt đầu Fine-tune"))
        self.train_btn.setObjectName("amber")
        self.train_btn.clicked.connect(self._train)
        btns.addWidget(self.export_btn)
        btns.addWidget(self.train_btn)
        train.box.addLayout(btns)
        row.addWidget(train, 1)
        col.addLayout(row, 1)

        ctx.job_done.connect(lambda _job: self.isVisible() and self.refresh())
        ctx.role_changed.connect(lambda _r: self._apply_role())
        self._apply_role()

    def _apply_role(self) -> None:
        self.export_btn.setEnabled(self.ctx.can("model.train"))
        self.train_btn.setEnabled(self.ctx.can("model.train"))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        store = self.ctx.store
        files = store.uncertain_files()
        self.count.setText(t("{0} mẫu").format(len(files)))
        self.range_label.setText(t("Detection có điểm từ {0:.2f} đến {1:.2f} (chỉnh trong Cài đặt). Giữ tối đa {2} mẫu mới nhất.").format(store.get('unc_lo', float), store.get('unc_hi', float), store.get('buffer_max')))
        if files and self.sample_name.text() != files[-1].name:
            self.sample.set_file(str(files[-1]))
            self.sample_name.setText(files[-1].name)

    def _dataset_dir(self):
        return self.ctx.store.dir / "dataset"

    def _export(self) -> None:
        yaml, n = self.ctx.store.export_dataset(self._dataset_dir())
        self.log.appendPlainText(t("Đã xuất {0} ảnh vào {1}\ndata.yaml: {2}\n").format(n, self._dataset_dir(), yaml))
        self.ctx.audit("EXPORT_DATASET", f"{n} images")

    def _train(self) -> None:
        if self.proc is not None:
            return
        yaml = self._dataset_dir() / "data.yaml"
        if not yaml.exists():
            self.log.appendPlainText(t("Chưa có dataset. Hãy bấm 'Xuất dataset YOLO' trước.\n"))
            return
        exe = shutil.which("yolo")
        if exe is None:
            self.log.appendPlainText(t("Không tìm thấy lệnh 'yolo'. Cài bằng: pip install ultralytics\n"
                                     "Sau khi train, export sang ONNX (yolo export format=onnx) rồi chọn file "
                                     "trong node 'YOLO Detector (ONNX)'.\n"))
            return
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(
            lambda: self.log.appendPlainText(bytes(self.proc.readAllStandardOutput()).decode(errors="replace").rstrip()))
        self.proc.finished.connect(self._finished)
        self.train_btn.setText(t("Đang huấn luyện..."))
        self.train_btn.setEnabled(False)
        self.ctx.audit("START_FINETUNE", str(yaml))
        self.proc.start(exe, ["detect", "train", f"data={yaml}", "model=yolov8n.pt", "epochs=10", "imgsz=640",
                              f"project={self.ctx.store.dir / 'runs'}"])

    def _finished(self, code: int, _status) -> None:
        self.log.appendPlainText(t("\nKết thúc huấn luyện (mã thoát {0}).\n").format(code))
        self.proc = None
        self.train_btn.setText(t("Bắt đầu Fine-tune"))
        self.train_btn.setEnabled(self.ctx.can("model.train"))