"""Measurement nodes: each returns one number (a Measurement). Judge it with 'Tolerance Check'."""
from __future__ import annotations

import math

import cv2

from ..core.i18n import t
from ..core.node_base import Node, Param, register
from ..core.schemas import Measurement, PortType

CAT = "Đo lường (Measure)"


def _gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


@register
class MeanBrightness(Node):
    TYPE = "measure.brightness"
    TITLE = "Mean Brightness"
    DESC = "Đo độ sáng trung bình của ảnh (0 đến 255). Dùng để kiểm tra đèn chiếu hoặc phát hiện ảnh quá tối."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"value": PortType.MEASUREMENT}

    def process(self, ctx, image):
        return {"value": Measurement("brightness", float(_gray(image.image).mean()), "", image)}


@register
class Sharpness(Node):
    TYPE = "measure.sharpness"
    TITLE = "Sharpness (Focus)"
    DESC = "Đo độ nét bằng phương sai Laplacian. Giá trị thấp nghĩa là ảnh mờ, ống kính lệch nét hoặc bị bẩn."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"value": PortType.MEASUREMENT}

    def process(self, ctx, image):
        return {"value": Measurement("sharpness", float(cv2.Laplacian(_gray(image.image), cv2.CV_64F).var()), "", image)}


@register
class WhiteRatio(Node):
    TYPE = "measure.white_ratio"
    TITLE = "White Pixel Ratio"
    DESC = "Đo tỉ lệ phần trăm điểm trắng trên ảnh nhị phân. Dùng để kiểm tra mức phủ keo, mức đầy, vùng thiếu."
    CATEGORY = CAT
    INPUTS = {"mask": PortType.IMAGE}
    OUTPUTS = {"value": PortType.MEASUREMENT}

    def process(self, ctx, mask):
        img = _gray(mask.image)
        return {"value": Measurement("white_ratio", 100.0 * cv2.countNonZero(img) / img.size, "%", mask)}


@register
class DetectionSize(Node):
    TYPE = "measure.detection_size"
    TITLE = "Detection Size"
    DESC = ("Đo chiều rộng, chiều cao hoặc diện tích khung bao của detection lớn nhất (có thể lọc theo lớp). "
            "Nhập hệ số mm/px để đổi sang milimét.")
    CATEGORY = CAT
    INPUTS = {"detections": PortType.DETECTIONS}
    OUTPUTS = {"value": PortType.MEASUREMENT}
    PARAMS = [Param("class_name", "str", "", "Lớp cần đo (để trống = bất kỳ)"),
              Param("dimension", "choice", "width", "Đại lượng", choices=["width", "height", "area"]),
              Param("mm_per_px", "float", 1.0, "Hệ số mm/px", 0.0001, 1000.0)]

    def process(self, ctx, detections):
        p = self.params
        items = [d for d in detections.items if not p["class_name"] or d.cls_name == p["class_name"]]
        if not items:
            raise RuntimeError(t("Không có detection nào để đo"))
        d = max(items, key=lambda d: (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]))
        w, h = (d.box[2] - d.box[0]) * p["mm_per_px"], (d.box[3] - d.box[1]) * p["mm_per_px"]
        value = {"width": w, "height": h, "area": w * h}[p["dimension"]]
        unit = "px" if p["mm_per_px"] == 1.0 else "mm"
        return {"value": Measurement(p["dimension"], float(value), unit + ("²" if p["dimension"] == "area" else ""),
                                     detections.source)}


@register
class DetectionDistance(Node):
    TYPE = "measure.detection_distance"
    TITLE = "Detection Distance"
    DESC = ("Đo khoảng cách giữa tâm của hai detection thuộc hai lớp (lấy detection có điểm cao nhất của mỗi lớp). "
            "Nhập hệ số mm/px để đổi sang milimét.")
    CATEGORY = CAT
    INPUTS = {"detections": PortType.DETECTIONS}
    OUTPUTS = {"value": PortType.MEASUREMENT}
    PARAMS = [Param("class_a", "str", "", "Lớp A"), Param("class_b", "str", "", "Lớp B"),
              Param("mm_per_px", "float", 1.0, "Hệ số mm/px", 0.0001, 1000.0)]

    def process(self, ctx, detections):
        p = self.params
        centers = []
        for name in (p["class_a"], p["class_b"]):
            items = [d for d in detections.items if d.cls_name == name]
            if not items:
                raise RuntimeError(t("Không tìm thấy lớp '{0}' để đo khoảng cách").format(name))
            if name == p["class_a"] == p["class_b"]:
                items = sorted(items, key=lambda d: -d.score)[len(centers):]     # same class: two best items
                if not items:
                    raise RuntimeError(t("Cần ít nhất hai detection của lớp '{0}'").format(name))
            d = max(items, key=lambda d: d.score)
            centers.append(((d.box[0] + d.box[2]) / 2, (d.box[1] + d.box[3]) / 2))
        dist = math.dist(centers[0], centers[1]) * p["mm_per_px"]
        return {"value": Measurement("distance", float(dist), "px" if p["mm_per_px"] == 1.0 else "mm", detections.source)}