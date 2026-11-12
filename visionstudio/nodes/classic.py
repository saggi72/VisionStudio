"""Classic (non-AI) detectors: contours, template matching, QR / barcode reading."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..core.executor import to_bgr
from ..core.i18n import t
from ..core.node_base import Node, Param, register
from ..core.schemas import Detection, Detections, PortType

CAT = "Thị giác cổ điển (Classic Vision)"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


@register
class ContourFinder(Node):
    TYPE = "classic.contours"
    TITLE = "Contour Finder"
    DESC = "Tìm các vùng trắng trên ảnh nhị phân và trả về khung bao của từng vùng, lọc theo diện tích."
    CATEGORY = CAT
    INPUTS = {"mask": PortType.IMAGE}
    OUTPUTS = {"detections": PortType.DETECTIONS}
    PARAMS = [Param("class_name", "str", "blob", "Tên lớp gán cho vùng"),
              Param("min_area", "int", 200, "Diện tích tối thiểu (px)", 1, 10**8),
              Param("max_area", "int", 10**7, "Diện tích tối đa (px)", 1, 10**8)]

    def process(self, ctx, mask):
        p = self.params
        img = _gray(mask.image)
        contours, _ = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        items = []
        for c in contours:
            area = cv2.contourArea(c)
            if p["min_area"] <= area <= p["max_area"]:
                x, y, w, h = cv2.boundingRect(c)
                fill = area / max(1.0, float(w * h))            # how much of its box the region fills
                items.append(Detection(p["class_name"], float(min(1.0, fill)), (x, y, x + w, y + h)))
        return {"detections": Detections(items, (img.shape[1], img.shape[0]), "contours", mask)}


@register
class TemplateMatch(Node):
    TYPE = "classic.template_match"
    TITLE = "Template Match"
    DESC = "Tìm vị trí giống ảnh mẫu nhất trong ảnh. Ảnh mẫu phải cùng tỉ lệ và cùng hướng với vật trong ảnh."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"detections": PortType.DETECTIONS}
    PARAMS = [Param("template", "file", "", "File ảnh mẫu"),
              Param("class_name", "str", "template", "Tên lớp"),
              Param("min_score", "float", 0.8, "Điểm khớp tối thiểu", 0.1, 1.0),
              Param("max_matches", "int", 1, "Số vị trí tối đa", 1, 100)]

    def setup(self, ctx):
        self.template = None
        path = Path(self.params["template"])
        if not self.params["template"]:
            return
        if not path.is_absolute() and not path.exists():
            path = PROJECT_ROOT / path
        self.template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if self.template is None:
            raise FileNotFoundError(t("Không đọc được ảnh mẫu: {0}").format(self.params["template"]))

    def process(self, ctx, image):
        if self.template is None:
            raise RuntimeError(t("Chưa chọn file ảnh mẫu"))
        p = self.params
        gray = _gray(image.image)
        th, tw = self.template.shape[:2]
        if th > gray.shape[0] or tw > gray.shape[1]:
            raise RuntimeError(t("Ảnh mẫu lớn hơn ảnh đầu vào"))
        score = cv2.matchTemplate(gray, self.template, cv2.TM_CCOEFF_NORMED)
        items = []
        for _ in range(p["max_matches"]):
            _, best, _, (x, y) = cv2.minMaxLoc(score)
            if best < p["min_score"]:
                break
            items.append(Detection(p["class_name"], float(best), (x, y, x + tw, y + th)))
            cv2.rectangle(score, (max(0, x - tw // 2), max(0, y - th // 2)), (x + tw // 2, y + th // 2), -1.0, -1)
        return {"detections": Detections(items, (gray.shape[1], gray.shape[0]), "template", image)}


@register
class CodeReader(Node):
    TYPE = "classic.code_reader"
    TITLE = "QR / Barcode Reader"
    DESC = ("Đọc mã QR và mã vạch 1D bằng OpenCV. Nội dung mã đầu tiên được dùng làm số serial của job. "
            "Mỗi mã đọc được là một detection có lớp là loại mã.")
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"detections": PortType.DETECTIONS}
    PARAMS = [Param("kind", "choice", "qr", "Loại mã", choices=["qr", "barcode", "both"]),
              Param("use_as_serial", "bool", True, "Dùng nội dung làm serial")]

    def setup(self, ctx):
        self.qr = cv2.QRCodeDetector()
        self.bar = cv2.barcode.BarcodeDetector() if hasattr(cv2, "barcode") else None

    def process(self, ctx, image):
        bgr = to_bgr(image.image)
        kind = self.params["kind"]
        found: list[tuple[str, str, np.ndarray]] = []
        if kind in ("qr", "both"):
            ok, texts, points, _ = self.qr.detectAndDecodeMulti(bgr)
            if ok:
                found += [("qr", txt, pts) for txt, pts in zip(texts, points) if txt]
        if kind in ("barcode", "both"):
            if self.bar is None:
                raise RuntimeError(t("Bản OpenCV này không có bộ đọc mã vạch 1D"))
            res = self.bar.detectAndDecodeMulti(bgr)
            ok, texts, points = res[0], res[1], res[-1]
            if ok:
                found += [("barcode", txt, pts) for txt, pts in zip(texts, points) if txt]
        items = []
        for name, txt, pts in found:
            pts = np.asarray(pts).reshape(-1, 2)
            x1, y1 = pts.min(0)
            x2, y2 = pts.max(0)
            items.append(Detection(name, 1.0, (float(x1), float(y1), float(x2), float(y2))))
        if found and self.params["use_as_serial"]:
            ctx.shared["serial"] = found[0][1]
        ctx.shared["codes"] = [txt for _n, txt, _p in found]
        return {"detections": Detections(items, (bgr.shape[1], bgr.shape[0]), "code-reader", image)}