from __future__ import annotations

from ..core.i18n import t

import cv2

from ..core.executor import to_bgr
from ..core.node_base import Node, Param, register
from ..core.schemas import PortType

CAT = "Tiền xử lý (Preprocess)"


@register
class MultiCamSync(Node):
    """Pairs two frames by timestamp and joins them side by side. This is software pairing;
    sub-millisecond sync needs hardware trigger or PTP configured on the cameras themselves."""
    TYPE = "source.multicam_sync"
    TITLE = "Multi-Cam Sync"
    DESC = "Ghép hai ảnh theo thời gian chụp và đặt cạnh nhau. Đây là ghép bằng phần mềm, không phải đồng bộ phần cứng."
    CATEGORY = "Nguồn ảnh & Đồng bộ (Source)"
    INPUTS = {"cam1": PortType.IMAGE, "cam2": PortType.IMAGE}
    OUTPUTS = {"synced_pair": PortType.IMAGE}
    PARAMS = [Param("max_tolerance_ms", "float", 250.0, "Lệch tối đa (ms)", 0.1, 5000.0)]

    def process(self, ctx, cam1, cam2):
        delta_ms = abs(cam1.timestamp_ns - cam2.timestamp_ns) / 1e6
        if delta_ms > self.params["max_tolerance_ms"]:
            raise RuntimeError(t("Hai ảnh lệch {0:.1f} ms, vượt ngưỡng đồng bộ").format(delta_ms))
        a, b = to_bgr(cam1.image), to_bgr(cam2.image)
        if a.shape[0] != b.shape[0]:
            b = cv2.resize(b, (int(b.shape[1] * a.shape[0] / b.shape[0]), a.shape[0]))
        return {"synced_pair": cam1.with_image(cv2.hconcat([a, b]), sync_delta_ms=delta_ms)}


@register
class Threshold(Node):
    TYPE = "classic.threshold"
    TITLE = "Threshold"
    DESC = "Tách ngưỡng ảnh xám thành ảnh nhị phân (Otsu, ngưỡng cố định hoặc thích nghi)."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"mask": PortType.IMAGE}
    PARAMS = [Param("method", "choice", "otsu", "Phương pháp", choices=["otsu", "binary", "adaptive"]),
              Param("thresh", "int", 128, "Ngưỡng", 0, 255),
              Param("invert", "bool", False, "Đảo")]

    def process(self, ctx, image):
        p = self.params
        gray = cv2.cvtColor(image.image, cv2.COLOR_BGR2GRAY) if image.image.ndim == 3 else image.image
        kind = cv2.THRESH_BINARY_INV if p["invert"] else cv2.THRESH_BINARY
        if p["method"] == "adaptive":
            out = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, kind, 31, 5)
        else:
            if p["method"] == "otsu":
                kind |= cv2.THRESH_OTSU
            _, out = cv2.threshold(gray, p["thresh"], 255, kind)
        return {"mask": image.with_image(out)}


@register
class GaussianBlur(Node):
    TYPE = "classic.gaussian_blur"
    TITLE = "Gaussian Blur"
    DESC = "Làm mờ Gaussian để giảm nhiễu trước khi tách ngưỡng hoặc tìm biên."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"image": PortType.IMAGE}
    PARAMS = [Param("ksize", "int", 5, "Kích thước kernel", 1, 99)]

    def process(self, ctx, image):
        k = int(self.params["ksize"]) | 1          # kernel must be odd
        return {"image": image.with_image(cv2.GaussianBlur(image.image, (k, k), 0))}


@register
class CropRoi(Node):
    TYPE = "classic.crop"
    TITLE = "Crop / ROI"
    DESC = "Cắt một vùng chữ nhật của ảnh để chỉ xử lý vùng cần kiểm tra."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"image": PortType.IMAGE}
    PARAMS = [Param("x", "int", 0, "X", 0, 20000), Param("y", "int", 0, "Y", 0, 20000),
              Param("w", "int", 320, "Rộng", 1, 20000), Param("h", "int", 240, "Cao", 1, 20000)]

    def process(self, ctx, image):
        p = self.params
        crop = image.image[p["y"]:p["y"] + p["h"], p["x"]:p["x"] + p["w"]]
        if crop.size == 0:
            raise RuntimeError(t("ROI nằm ngoài ảnh"))
        return {"image": image.with_image(crop.copy(), crop_offset=(p["x"], p["y"]))}


def _gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


@register
class Grayscale(Node):
    TYPE = "classic.grayscale"
    TITLE = "Grayscale"
    DESC = "Chuyển ảnh màu thành ảnh xám."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"image": PortType.IMAGE}

    def process(self, ctx, image):
        return {"image": image.with_image(_gray(image.image))}


@register
class Resize(Node):
    TYPE = "classic.resize"
    TITLE = "Resize"
    DESC = "Đổi kích thước ảnh theo tỉ lệ phần trăm. Ảnh nhỏ hơn thì các bước sau chạy nhanh hơn."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"image": PortType.IMAGE}
    PARAMS = [Param("scale_percent", "int", 50, "Tỉ lệ (%)", 5, 400)]

    def process(self, ctx, image):
        f = self.params["scale_percent"] / 100.0
        interp = cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR
        return {"image": image.with_image(cv2.resize(image.image, None, fx=f, fy=f, interpolation=interp))}


@register
class RotateFlip(Node):
    TYPE = "classic.rotate_flip"
    TITLE = "Rotate / Flip"
    DESC = "Xoay ảnh theo bội số 90 độ hoặc lật ảnh, dùng khi camera lắp nghiêng hay ngược."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"image": PortType.IMAGE}
    PARAMS = [Param("rotate", "choice", "0", "Xoay (độ)", choices=["0", "90", "180", "270"]),
              Param("flip", "choice", "none", "Lật", choices=["none", "horizontal", "vertical"])]

    def process(self, ctx, image):
        img = image.image
        code = {"90": cv2.ROTATE_90_CLOCKWISE, "180": cv2.ROTATE_180,
                "270": cv2.ROTATE_90_COUNTERCLOCKWISE}.get(str(self.params["rotate"]))
        if code is not None:
            img = cv2.rotate(img, code)
        if self.params["flip"] != "none":
            img = cv2.flip(img, 1 if self.params["flip"] == "horizontal" else 0)
        return {"image": image.with_image(img)}


@register
class BrightnessContrast(Node):
    TYPE = "classic.brightness_contrast"
    TITLE = "Brightness / Contrast"
    DESC = "Chỉnh độ tương phản (nhân) và độ sáng (cộng) của ảnh."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"image": PortType.IMAGE}
    PARAMS = [Param("contrast", "float", 1.0, "Tương phản (x)", 0.1, 5.0),
              Param("brightness", "int", 0, "Độ sáng (+/-)", -255, 255)]

    def process(self, ctx, image):
        out = cv2.convertScaleAbs(image.image, alpha=self.params["contrast"], beta=self.params["brightness"])
        return {"image": image.with_image(out)}


@register
class Clahe(Node):
    TYPE = "classic.clahe"
    TITLE = "CLAHE"
    DESC = "Cân bằng tương phản cục bộ, làm rõ chi tiết khi ánh sáng không đều. Đầu ra là ảnh xám."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"image": PortType.IMAGE}
    PARAMS = [Param("clip_limit", "float", 2.0, "Giới hạn tương phản", 0.5, 20.0),
              Param("tile", "int", 8, "Số ô lưới", 2, 32)]

    def process(self, ctx, image):
        clahe = cv2.createCLAHE(self.params["clip_limit"], (self.params["tile"], self.params["tile"]))
        return {"image": image.with_image(clahe.apply(_gray(image.image)))}


@register
class CannyEdge(Node):
    TYPE = "classic.canny"
    TITLE = "Canny Edge"
    DESC = "Tìm biên bằng thuật toán Canny. Đầu ra là ảnh nhị phân, biên có màu trắng."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"edges": PortType.IMAGE}
    PARAMS = [Param("low", "int", 50, "Ngưỡng thấp", 0, 500), Param("high", "int", 150, "Ngưỡng cao", 0, 500)]

    def process(self, ctx, image):
        return {"edges": image.with_image(cv2.Canny(_gray(image.image), self.params["low"], self.params["high"]))}


@register
class Morphology(Node):
    TYPE = "classic.morphology"
    TITLE = "Morphology"
    DESC = "Phép hình thái trên ảnh nhị phân: open xóa đốm nhỏ, close lấp lỗ nhỏ, erode co, dilate nở."
    CATEGORY = CAT
    INPUTS = {"mask": PortType.IMAGE}
    OUTPUTS = {"mask": PortType.IMAGE}
    PARAMS = [Param("operation", "choice", "open", "Phép toán", choices=["open", "close", "erode", "dilate"]),
              Param("ksize", "int", 5, "Kích thước kernel", 1, 99),
              Param("iterations", "int", 1, "Số lần lặp", 1, 20)]

    def process(self, ctx, mask):
        p = self.params
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (p["ksize"], p["ksize"]))
        op = {"open": cv2.MORPH_OPEN, "close": cv2.MORPH_CLOSE, "erode": cv2.MORPH_ERODE,
              "dilate": cv2.MORPH_DILATE}[p["operation"]]
        return {"mask": mask.with_image(cv2.morphologyEx(mask.image, op, kernel, iterations=p["iterations"]))}


@register
class ColorMask(Node):
    TYPE = "classic.color_mask"
    TITLE = "Color Mask (HSV)"
    DESC = "Giữ lại các điểm ảnh có màu nằm trong khoảng HSV. Đầu ra là ảnh nhị phân. H của OpenCV chạy từ 0 đến 179."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"mask": PortType.IMAGE}
    PARAMS = [Param("h_min", "int", 0, "H thấp", 0, 179), Param("h_max", "int", 179, "H cao", 0, 179),
              Param("s_min", "int", 80, "S thấp", 0, 255), Param("s_max", "int", 255, "S cao", 0, 255),
              Param("v_min", "int", 80, "V thấp", 0, 255), Param("v_max", "int", 255, "V cao", 0, 255)]

    def process(self, ctx, image):
        p = self.params
        hsv = cv2.cvtColor(to_bgr(image.image), cv2.COLOR_BGR2HSV)
        lo, hi = (p["h_min"], p["s_min"], p["v_min"]), (p["h_max"], p["s_max"], p["v_max"])
        return {"mask": image.with_image(cv2.inRange(hsv, lo, hi))}