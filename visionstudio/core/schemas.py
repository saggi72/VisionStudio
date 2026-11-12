"""Data contracts exchanged between nodes. Every node and adapter speaks only these types."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class PortType(str, Enum):
    IMAGE = "IMAGE"
    ROI = "ROI"
    DETECTIONS = "DETECTIONS"
    MEASUREMENT = "MEASUREMENT"
    RESULT = "RESULT"


PORT_COLORS = {
    PortType.IMAGE: "#3498db",
    PortType.ROI: "#f39c12",
    PortType.DETECTIONS: "#e74c3c",
    PortType.MEASUREMENT: "#2ecc71",
    PortType.RESULT: "#9b59b6",
}


@dataclass
class Frame:
    image: np.ndarray               # HxW (mono) or HxWx3 (BGR), uint8
    timestamp_ns: int = 0
    frame_id: int = 0
    source_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def with_image(self, image: np.ndarray, **meta: Any) -> "Frame":
        return Frame(image, self.timestamp_ns, self.frame_id, self.source_id, {**self.meta, **meta})


@dataclass
class Detection:
    cls_name: str
    score: float
    box: tuple[float, float, float, float]   # x1, y1, x2, y2 in pixels of the source image


@dataclass
class Detections:
    items: list[Detection]
    image_size: tuple[int, int]               # (w, h)
    model_id: str = ""
    source: Frame | None = None               # frame the detections were computed on


@dataclass
class Measurement:
    name: str
    value: float
    unit: str = ""
    source: Frame | None = None               # frame the value was measured on (for the probe)


@dataclass
class InspectionResult:
    status: str                               # "OK" | "NG" | "ERROR"
    reasons: list[str] = field(default_factory=list)
    values: dict[str, float] = field(default_factory=dict)