from __future__ import annotations

from ..core.i18n import t

import ast
import math
from pathlib import Path

import cv2
import numpy as np

from ..core.executor import to_bgr
from ..core.node_base import Node, Param, register
from ..core.schemas import Detection, Detections, PortType

CAT = "Trí tuệ nhân tạo (AI Vision)"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_model(path: str) -> str:
    """Model paths in a recipe may be absolute, relative to the working dir, or to the project root."""
    p = Path(path)
    if p.is_absolute() or p.exists():
        return str(p)
    alt = PROJECT_ROOT / p
    return str(alt) if alt.exists() else str(p)


def parse_filter(text: str) -> set[str]:
    return {c.strip() for c in text.split(",") if c.strip()}

# HSV range and nominal area (px) per class for the colour-blob detector.
BLOB_PROFILES = {
    "connector": {"lo": (95, 120, 100), "hi": (125, 255, 255), "area": 110 * 56},
    "screw": {"lo": (0, 0, 170), "hi": (180, 50, 255), "area": math.pi * 30 ** 2},
}


@register
class ColorBlobDetector(Node):
    """Classic HSV blob detector. It finds the parts of the built-in simulated product and lets
    the whole pipeline run with no model file. For real parts use one of the YOLO detector nodes."""
    TYPE = "ai.blob_detect"
    TITLE = "Color Blob Detector"
    DESC = "Tìm connector và ốc của sản phẩm mô phỏng theo màu. Chỉ dùng với camera mô phỏng."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"detections": PortType.DETECTIONS}
    PARAMS = [Param("classes", "str", "connector,screw", "Lớp cần tìm"),
              Param("conf_threshold", "float", 0.5, "Ngưỡng tin cậy", 0.05, 1.0),
              Param("min_area", "int", 300, "Diện tích tối thiểu (px)", 10, 100000)]

    def process(self, ctx, image):
        p = self.params
        bgr = to_bgr(image.image)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        kernel = np.ones((3, 3), np.uint8)
        items = []
        for name in (c.strip() for c in p["classes"].split(",")):
            prof = BLOB_PROFILES.get(name)
            if prof is None:
                raise ValueError(t("Chưa có profile màu cho lớp '{0}'").format(name))
            mask = cv2.morphologyEx(cv2.inRange(hsv, prof["lo"], prof["hi"]), cv2.MORPH_OPEN, kernel)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                area = cv2.contourArea(c)
                if area < p["min_area"]:
                    continue
                score = min(1.0, area / prof["area"])    # how complete the part looks
                if score >= p["conf_threshold"]:
                    x, y, w, h = cv2.boundingRect(c)
                    items.append(Detection(name, float(score), (x, y, x + w, y + h)))
        return {"detections": Detections(items, (bgr.shape[1], bgr.shape[0]), "color-blob", image)}


@register
class YoloOnnxDetector(Node):
    """YOLO detection model exported to ONNX (Ultralytics v8/v11 layout: 1 x (4+nc) x N).
    Pre/post-processing is done here, so the line PC needs only `pip install onnxruntime`.
    Class names are read from the model file; fill 'Tên lớp' only when the file has none."""
    TYPE = "ai.yolo_onnx"
    TITLE = "YOLO Detector (ONNX)"
    DESC = "Phát hiện vật thể bằng model YOLO dạng ONNX. Chỉ cần onnxruntime; tên lớp đọc từ file model."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"detections": PortType.DETECTIONS}
    PARAMS = [Param("model", "file", "", "File model .onnx"),
              Param("class_names", "str", "", "Tên lớp (để trống = đọc từ model)"),
              Param("only_classes", "str", "", "Chỉ giữ các lớp (để trống = tất cả)"),
              Param("conf_threshold", "float", 0.5, "Ngưỡng tin cậy", 0.05, 1.0),
              Param("nms_iou", "float", 0.45, "NMS IoU", 0.05, 0.95),
              Param("backend", "choice", "auto", "Backend", choices=["auto", "cpu", "cuda", "tensorrt"])]

    def setup(self, ctx):
        self.session = None
        if not self.params["model"]:
            return
        path = resolve_model(self.params["model"])
        if not Path(path).exists():
            raise FileNotFoundError(t("Không tìm thấy file model: {0}").format(self.params['model']))
        try:
            import onnxruntime as ort                  # lazy: optional dependency
        except ImportError as exc:
            raise RuntimeError(t("Thiếu thư viện onnxruntime. Cài bằng: pip install onnxruntime")) from exc
        want = {"cpu": [], "cuda": ["CUDAExecutionProvider"],
                "tensorrt": ["TensorrtExecutionProvider", "CUDAExecutionProvider"]}.get(
                    self.params["backend"], ["CUDAExecutionProvider"])
        providers = [p for p in want if p in ort.get_available_providers()] + ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(path, providers=providers)
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        h, w = inp.shape[2], inp.shape[3]
        self.size = (w if isinstance(w, int) else 640, h if isinstance(h, int) else 640)
        self.names = [n.strip() for n in self.params["class_names"].split(",") if n.strip()]
        if not self.names:                             # Ultralytics stores {id: name} in the metadata
            meta = self.session.get_modelmeta().custom_metadata_map.get("names", "")
            try:
                parsed = ast.literal_eval(meta) if meta else {}
                self.names = [parsed[i] for i in sorted(parsed)]
            except (ValueError, SyntaxError, KeyError):
                self.names = []

    def process(self, ctx, image):
        if self.session is None:
            raise RuntimeError(t("Chưa chọn file model .onnx"))
        p = self.params
        bgr = to_bgr(image.image)
        ih, iw = bgr.shape[:2]
        tw, th = self.size
        scale = min(tw / iw, th / ih)
        nw, nh = int(round(iw * scale)), int(round(ih * scale))
        dx, dy = (tw - nw) // 2, (th - nh) // 2
        canvas = np.full((th, tw, 3), 114, np.uint8)                       # letterbox
        canvas[dy:dy + nh, dx:dx + nw] = cv2.resize(bgr, (nw, nh))
        blob = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        pred = self.session.run(None, {self.input_name: blob})[0][0]
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T                                                  # -> N x (4+nc)
        scores = pred[:, 4:]
        cls_ids, conf = scores.argmax(1), scores.max(1)
        keep = conf >= p["conf_threshold"]
        boxes, conf, cls_ids = pred[keep, :4], conf[keep], cls_ids[keep]
        xywh = np.stack([(boxes[:, 0] - boxes[:, 2] / 2 - dx) / scale, (boxes[:, 1] - boxes[:, 3] / 2 - dy) / scale,
                         boxes[:, 2] / scale, boxes[:, 3] / scale], 1) if len(boxes) else np.zeros((0, 4))
        only = parse_filter(p["only_classes"])
        items = []
        for cid in np.unique(cls_ids):                                     # NMS per class
            sel = np.where(cls_ids == cid)[0]
            name = self.names[cid] if cid < len(self.names) else f"class{cid}"
            if only and name not in only:
                continue
            idx = cv2.dnn.NMSBoxes(xywh[sel].tolist(), conf[sel].tolist(), p["conf_threshold"], p["nms_iou"])
            for i in sel[np.array(idx).flatten()]:
                x, y, w, h = xywh[i]
                x1, y1 = max(0.0, float(x)), max(0.0, float(y))
                x2, y2 = min(float(iw), float(x + w)), min(float(ih), float(y + h))
                items.append(Detection(name, float(conf[i]), (x1, y1, x2, y2)))
        return {"detections": Detections(items, (iw, ih), Path(p["model"]).name, image)}

    def teardown(self):
        self.session = None


@register
class YoloUltralyticsDetector(Node):
    """YOLO model in Ultralytics format (.pt), run through the `ultralytics` package (PyTorch).
    Handy for development: a standard name such as yolo11n.pt is downloaded on first use.
    For a line PC prefer the ONNX node (lighter install). Ultralytics is licensed AGPL-3.0."""
    TYPE = "ai.yolo_ultralytics"
    TITLE = "YOLO Detector (Ultralytics .pt)"
    DESC = "Phát hiện vật thể bằng model YOLO dạng .pt qua thư viện ultralytics (PyTorch). Dùng khi phát triển."
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"detections": PortType.DETECTIONS}
    PARAMS = [Param("model", "file", "yolo11n.pt", "File model .pt"),
              Param("only_classes", "str", "", "Chỉ giữ các lớp (để trống = tất cả)"),
              Param("conf_threshold", "float", 0.5, "Ngưỡng tin cậy", 0.05, 1.0),
              Param("nms_iou", "float", 0.45, "NMS IoU", 0.05, 0.95),
              Param("imgsz", "int", 640, "Kích thước ảnh suy luận", 160, 1920),
              Param("device", "choice", "auto", "Thiết bị", choices=["auto", "cpu", "cuda:0"])]

    def setup(self, ctx):
        try:
            from ultralytics import YOLO               # lazy: optional dependency
        except ImportError as exc:
            raise RuntimeError(t("Thiếu thư viện ultralytics. Cài bằng: pip install ultralytics")) from exc
        self.model = YOLO(resolve_model(self.params["model"]))

    def process(self, ctx, image):
        p = self.params
        bgr = to_bgr(image.image)
        res = self.model.predict(bgr, conf=p["conf_threshold"], iou=p["nms_iou"], imgsz=p["imgsz"],
                                 device=None if p["device"] == "auto" else p["device"], verbose=False)[0]
        only = parse_filter(p["only_classes"])
        items = []
        for box, score, cid in zip(res.boxes.xyxy.tolist(), res.boxes.conf.tolist(), res.boxes.cls.tolist()):
            name = res.names[int(cid)]
            if not only or name in only:
                items.append(Detection(name, float(score), tuple(float(v) for v in box)))
        return {"detections": Detections(items, (bgr.shape[1], bgr.shape[0]), Path(p["model"]).name, image)}

    def teardown(self):
        self.model = None