from __future__ import annotations

from collections import Counter

from ..core.node_base import Node, Param, register
from ..core.schemas import Detections, InspectionResult, PortType


@register
class CountByClass(Node):
    TYPE = "logic.count_by_class"
    TITLE = "Count by Class"
    DESC = "Đếm detection theo lớp và so với số lượng mong đợi. Thiếu thì NG; thừa cũng NG nếu bật kiểm tra chặt."
    CATEGORY = "Logic"
    INPUTS = {"detections": PortType.DETECTIONS}
    OUTPUTS = {"result": PortType.RESULT}
    PARAMS = [Param("expect", "str", "connector=4,screw=2", "Số lượng mong đợi"),
              Param("strict", "bool", True, "Thừa cũng tính NG")]

    def process(self, ctx, detections):
        expect = {}
        for part in self.params["expect"].split(","):
            if "=" in part:
                name, n = part.split("=", 1)
                expect[name.strip()] = int(n)
        counts = Counter(d.cls_name for d in detections.items)
        reasons = []
        for name, n in expect.items():
            if counts[name] < n:
                reasons.append(f"MISSING_{name.upper()}")
            elif counts[name] > n and self.params["strict"]:
                reasons.append(f"EXTRA_{name.upper()}")
        values = {f"count_{k}": float(v) for k, v in counts.items()}
        return {"result": InspectionResult("NG" if reasons else "OK", reasons, values)}


@register
class ToleranceCheck(Node):
    TYPE = "logic.tolerance"
    TITLE = "Tolerance Check"
    DESC = "So một giá trị đo với khoảng cho phép [min, max]. Trong khoảng là OK, ngoài khoảng là NG."
    CATEGORY = "Logic"
    INPUTS = {"value": PortType.MEASUREMENT}
    OUTPUTS = {"result": PortType.RESULT}
    PARAMS = [Param("min", "float", 0.0, "Giá trị nhỏ nhất", -1e9, 1e9),
              Param("max", "float", 100.0, "Giá trị lớn nhất", -1e9, 1e9)]

    def process(self, ctx, value):
        p = self.params
        reasons = []
        if value.value < p["min"]:
            reasons.append(f"{value.name.upper()}_TOO_LOW")
        elif value.value > p["max"]:
            reasons.append(f"{value.name.upper()}_TOO_HIGH")
        return {"result": InspectionResult("NG" if reasons else "OK", reasons, {value.name: float(value.value)})}


@register
class DetectionFilter(Node):
    TYPE = "logic.detection_filter"
    TITLE = "Detection Filter"
    DESC = "Lọc detection theo lớp, điểm tin cậy và diện tích khung bao trước khi đếm hoặc đo."
    CATEGORY = "Logic"
    INPUTS = {"detections": PortType.DETECTIONS}
    OUTPUTS = {"detections": PortType.DETECTIONS}
    PARAMS = [Param("keep_classes", "str", "", "Chỉ giữ các lớp (để trống = tất cả)"),
              Param("min_score", "float", 0.0, "Điểm tối thiểu", 0.0, 1.0),
              Param("min_area", "int", 0, "Diện tích tối thiểu (px)", 0, 10**8),
              Param("max_area", "int", 10**8, "Diện tích tối đa (px)", 0, 10**8)]

    def process(self, ctx, detections):
        p = self.params
        keep = {c.strip() for c in p["keep_classes"].split(",") if c.strip()}
        items = [d for d in detections.items
                 if (not keep or d.cls_name in keep) and d.score >= p["min_score"]
                 and p["min_area"] <= (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]) <= p["max_area"]]
        return {"detections": Detections(items, detections.image_size, detections.model_id, detections.source)}


@register
class PresenceCheck(Node):
    TYPE = "logic.presence"
    TITLE = "Presence Check"
    DESC = ("Kiểm tra có / không: NG khi thiếu bất kỳ lớp bắt buộc nào, hoặc khi xuất hiện bất kỳ lớp bị cấm nào "
            "(ví dụ các lớp lỗi như scratch, dent).")
    CATEGORY = "Logic"
    INPUTS = {"detections": PortType.DETECTIONS}
    OUTPUTS = {"result": PortType.RESULT}
    PARAMS = [Param("required", "str", "", "Lớp bắt buộc có"),
              Param("forbidden", "str", "", "Lớp bị cấm (lỗi)")]

    def process(self, ctx, detections):
        present = Counter(d.cls_name for d in detections.items)
        split = lambda text: [c.strip() for c in text.split(",") if c.strip()]
        reasons = [f"MISSING_{c.upper()}" for c in split(self.params["required"]) if not present[c]]
        reasons += [f"FOUND_{c.upper()}" for c in split(self.params["forbidden"]) if present[c]]
        values = {f"count_{k}": float(v) for k, v in present.items()}
        return {"result": InspectionResult("NG" if reasons else "OK", reasons, values)}


@register
class CombineResults(Node):
    TYPE = "logic.combine"
    TITLE = "Combine Results (AND)"
    DESC = ("Gộp hai kết quả thành một: OK khi cả hai đều OK, ERROR nếu có nhánh ERROR, còn lại là NG. "
            "Dùng trước PLC Handshake khi pipeline có nhiều phép kiểm.")
    CATEGORY = "Logic"
    INPUTS = {"a": PortType.RESULT, "b": PortType.RESULT}
    OUTPUTS = {"result": PortType.RESULT}

    def process(self, ctx, a, b):
        status = "ERROR" if "ERROR" in (a.status, b.status) else "NG" if "NG" in (a.status, b.status) else "OK"
        return {"result": InspectionResult(status, a.reasons + b.reasons, {**a.values, **b.values})}