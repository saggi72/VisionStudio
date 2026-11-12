"""Runs one inspection job through the graph and measures every node."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import cv2
import numpy as np

from .graph import Graph
from .node_base import REGISTRY, Node
from .schemas import Detections, Frame, InspectionResult, Measurement, PortType

CLASS_COLORS = [(80, 220, 120), (60, 200, 255), (255, 160, 60), (220, 120, 255), (120, 255, 255)]


@dataclass
class JobContext:
    devices: Any
    store: Any
    job_no: int = 0
    shared: dict[str, Any] = field(default_factory=dict)   # per-job scratch (serial number, ...)


@dataclass
class JobResult:
    job_no: int
    timestamp: str
    result: InspectionResult
    serial: str = ""
    cycle_ms: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)       # node id -> ms
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    preview: np.ndarray | None = None
    n_detections: int = 0

    @property
    def job_id(self) -> str:
        return f"JOB-{self.job_no:05d}"


class Executor:
    def __init__(self, graph: Graph, devices, store):
        problems = graph.validate()
        if problems:
            raise ValueError("; ".join(f"[{nid or 'graph'}] {msg}" for nid, msg in problems))
        self.graph = graph
        self.order = graph.topo_order()
        self.nodes: dict[str, Node] = {nid: REGISTRY[graph.nodes[nid].type](nid, graph.nodes[nid].params)
                                       for nid in self.order}
        self.ctx = JobContext(devices, store)
        for node in self.nodes.values():
            node.setup(self.ctx)

    def close(self) -> None:
        for node in self.nodes.values():
            try:
                node.teardown()
            except Exception:
                pass

    def _verdict(self, outputs: dict[str, dict[str, Any]]) -> InspectionResult:
        """Final verdict = all terminal results combined: any ERROR -> ERROR, any NG -> NG, else OK.
        A result that feeds another result-producing node (e.g. Combine Results) is not terminal."""
        feeds_logic = {(e.src, e.src_port) for e in self.graph.edges
                       if PortType.RESULT in self.nodes[e.dst].OUTPUTS.values()}
        finals = [v for nid in self.order for port, v in outputs.get(nid, {}).items()
                  if isinstance(v, InspectionResult) and (nid, port) not in feeds_logic]
        if not finals:
            return InspectionResult("ERROR", ["NO_RESULT_NODE"])
        if len(finals) == 1:
            return finals[0]
        status = "ERROR" if any(r.status == "ERROR" for r in finals) else \
            "NG" if any(r.status == "NG" for r in finals) else "OK"
        values: dict[str, float] = {}
        for r in finals:
            values.update(r.values)
        return InspectionResult(status, [reason for r in finals for reason in r.reasons], values)

    def run_job(self, job_no: int) -> JobResult:
        ctx = self.ctx
        ctx.job_no, ctx.shared = job_no, {}
        outputs: dict[str, dict[str, Any]] = {}
        timings: dict[str, float] = {}
        t_job = time.perf_counter()
        try:
            for nid in self.order:
                wired = self.graph.inputs_of(nid)
                kwargs = {port: outputs[src][sport] for port, (src, sport) in wired.items()}
                t0 = time.perf_counter()
                try:
                    out = self.nodes[nid].process(ctx, **kwargs) or {}
                finally:
                    timings[nid] = (time.perf_counter() - t0) * 1000.0
                outputs[nid] = out
            result = self._verdict(outputs)
        except Exception as exc:
            # ERROR means "the system could not judge" and must never be reported as OK.
            failed = next((n for n in self.order if n not in outputs), "?")
            result = InspectionResult("ERROR", [f"NODE_FAILED:{failed}"], {})
            ctx.shared["error_detail"] = f"{type(exc).__name__}: {exc}"
        job = JobResult(job_no, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), result,
                        serial=str(ctx.shared.get("serial", "")),
                        cycle_ms=(time.perf_counter() - t_job) * 1000.0, timings=timings, outputs=outputs)
        if "error_detail" in ctx.shared:
            job.result.values = {}
            job.result.reasons.append(ctx.shared["error_detail"][:120])
        dets = last_detections(job)
        job.n_detections = len(dets.items) if dets else 0
        job.preview = render_preview(job)
        return job


# ---- helpers used by the UI probe and the archive ----------------------------------------------
def last_detections(job: JobResult) -> Detections | None:
    found = None
    for out in job.outputs.values():
        for value in out.values():
            if isinstance(value, Detections):
                found = value
    return found


def to_bgr(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image


def draw_detections(dets: Detections) -> np.ndarray | None:
    if dets.source is None:
        return None
    img = to_bgr(dets.source.image).copy()
    names = sorted({d.cls_name for d in dets.items})
    for d in dets.items:
        color = CLASS_COLORS[names.index(d.cls_name) % len(CLASS_COLORS)]
        x1, y1, x2, y2 = (int(v) for v in d.box)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, f"{d.cls_name} {d.score:.2f}", (x1, max(14, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return img


def render_preview(job: JobResult) -> np.ndarray | None:
    dets = last_detections(job)
    img = draw_detections(dets) if dets else None
    if img is None:
        for out in job.outputs.values():
            for value in out.values():
                if isinstance(value, Frame):
                    img = to_bgr(value.image).copy()
    if img is None:
        return None
    color = {"OK": (80, 200, 80), "NG": (60, 60, 230)}.get(job.result.status, (0, 170, 255))
    cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), color, 4)
    cv2.putText(img, job.result.status, (14, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.1, color, 3, cv2.LINE_AA)
    return img


def probe_image(job: JobResult, node_id: str) -> np.ndarray | None:
    """Image to show when the user probes one node: its image output, or its detections drawn."""
    out = job.outputs.get(node_id, {})
    for value in out.values():
        if isinstance(value, Frame):
            return to_bgr(value.image)
    for value in out.values():
        if isinstance(value, Detections):
            return draw_detections(value)
    for value in out.values():
        if isinstance(value, Measurement) and value.source is not None:
            img = to_bgr(value.source.image).copy()
            text = f"{value.name} = {value.value:.3f} {value.unit}".strip()
            cv2.rectangle(img, (0, 0), (min(img.shape[1], 14 * len(text) + 20), 34), (0, 0, 0), -1)
            cv2.putText(img, text, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (80, 220, 255), 2, cv2.LINE_AA)
            return img
    return job.preview