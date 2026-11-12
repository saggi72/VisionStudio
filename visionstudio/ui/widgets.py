"""Small reusable widgets."""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme


def np_to_qimage(img: np.ndarray) -> QImage:
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    if img.ndim == 2:
        return QImage(img.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
    return QImage(img.data, w, h, 3 * w, QImage.Format.Format_BGR888).copy()


class ImageView(QLabel):
    """Shows a numpy image scaled to fit, keeping the aspect ratio."""

    def __init__(self, placeholder: str = "", min_h: int = 160, fixed_h: int = 0):
        super().__init__(placeholder)
        self._pix: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if fixed_h:
            self.setFixedHeight(fixed_h)
            self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        else:
            self.setMinimumSize(120, min_h)
            self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet(f"background:{theme.IMAGE_BG}; border:1px solid {theme.BORDER_HI}; border-radius:8px;"
                           f"color:{theme.IMAGE_TEXT}; font-family:{theme.MONO}; font-size:11px;")

    def set_image(self, img: np.ndarray | None) -> None:
        if img is None:
            return
        self._pix = QPixmap.fromImage(np_to_qimage(img))
        self._rescale()

    def set_file(self, path: str) -> None:
        self._pix = QPixmap(path)
        self._rescale()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._pix and not self._pix.isNull():
            self.setPixmap(self._pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))


class Card(QFrame):
    def __init__(self, margins: int = 18, spacing: int = 10):
        super().__init__()
        self.setObjectName("card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(margins, margins, margins, margins)
        self.box.setSpacing(spacing)


class StatCard(Card):
    def __init__(self, caption: str, color: str = ""):
        super().__init__(14, 4)
        cap = QLabel(caption)
        cap.setObjectName("caption")
        self.value = QLabel("0")
        self.value.setObjectName("value")
        self.value.setStyleSheet(f"color:{color or theme.TEXT_STRONG};")
        self.box.addWidget(cap)
        self.box.addWidget(self.value)

    def set_value(self, text: str) -> None:
        self.value.setText(text)


def label(text: str, obj: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def view_header(title: str, subtitle: str, *buttons: QWidget) -> QWidget:
    """Standard page header: title + subtitle on the left, action buttons on the right."""
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 12)
    col = QVBoxLayout()
    col.setSpacing(2)
    col.addWidget(label(title, "h1"))
    col.addWidget(label(subtitle, "sub"))
    row.addLayout(col, 1)
    for b in buttons:
        row.addWidget(b)
    w.setStyleSheet(f"QWidget#hdr {{ border-bottom: 1px solid {theme.BORDER}; }}")
    w.setObjectName("hdr")
    return w