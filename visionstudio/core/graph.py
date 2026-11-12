"""Pipeline graph model, validation, and recipe (JSON) load/save."""
from __future__ import annotations

from .i18n import t

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .node_base import REGISTRY

SCHEMA_VERSION = 1


class GraphError(Exception):
    pass


@dataclass
class NodeInst:
    id: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0
    title: str = ""


@dataclass
class Edge:
    src: str
    src_port: str
    dst: str
    dst_port: str


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, NodeInst] = {}
        self.edges: list[Edge] = []

    # ---- editing -------------------------------------------------------------------------
    def add_node(self, type_id: str, x: float = 0, y: float = 0, node_id: str | None = None,
                 params: dict | None = None, title: str | None = None) -> NodeInst:
        if type_id not in REGISTRY:
            raise GraphError(f"Unknown node type '{type_id}'")
        cls = REGISTRY[type_id]
        if node_id is None:
            base, i = type_id.split(".")[-1], 1
            while f"{base}{i}" in self.nodes:
                i += 1
            node_id = f"{base}{i}"
        merged = {p.name: p.default for p in cls.PARAMS}
        merged.update(params or {})
        inst = NodeInst(node_id, type_id, merged, x, y, title or cls.TITLE)
        self.nodes[node_id] = inst
        return inst

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.edges = [e for e in self.edges if e.src != node_id and e.dst != node_id]

    def can_connect(self, src: str, src_port: str, dst: str, dst_port: str) -> str | None:
        """Return None if the connection is legal, otherwise the reason it is not."""
        if src == dst:
            return t("Không thể nối node với chính nó")
        s_cls, d_cls = REGISTRY[self.nodes[src].type], REGISTRY[self.nodes[dst].type]
        if src_port not in s_cls.OUTPUTS or dst_port not in d_cls.INPUTS:
            return t("Cổng không tồn tại")
        if s_cls.OUTPUTS[src_port] != d_cls.INPUTS[dst_port]:
            return t("Sai kiểu: {0} → {1}").format(s_cls.OUTPUTS[src_port].value, d_cls.INPUTS[dst_port].value)
        if self._reaches(dst, src):
            return t("Kết nối tạo thành vòng lặp")
        return None

    def add_edge(self, src: str, src_port: str, dst: str, dst_port: str) -> Edge:
        err = self.can_connect(src, src_port, dst, dst_port)
        if err:
            raise GraphError(err)
        self.edges = [e for e in self.edges if not (e.dst == dst and e.dst_port == dst_port)]
        edge = Edge(src, src_port, dst, dst_port)
        self.edges.append(edge)
        return edge

    def remove_edge(self, edge: Edge) -> None:
        self.edges = [e for e in self.edges if e is not edge and e != edge]

    # ---- analysis ------------------------------------------------------------------------
    def _reaches(self, start: str, target: str) -> bool:
        stack, seen = [start], set()
        while stack:
            cur = stack.pop()
            if cur == target:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(e.dst for e in self.edges if e.src == cur)
        return False

    def inputs_of(self, node_id: str) -> dict[str, tuple[str, str]]:
        return {e.dst_port: (e.src, e.src_port) for e in self.edges if e.dst == node_id}

    def topo_order(self) -> list[str]:
        indeg = {nid: 0 for nid in self.nodes}
        for e in self.edges:
            indeg[e.dst] += 1
        ready = [n for n, d in indeg.items() if d == 0]
        order: list[str] = []
        while ready:
            nid = ready.pop(0)
            order.append(nid)
            for e in self.edges:
                if e.src == nid:
                    indeg[e.dst] -= 1
                    if indeg[e.dst] == 0:
                        ready.append(e.dst)
        if len(order) != len(self.nodes):
            raise GraphError(t("Đồ thị có vòng lặp"))
        return order

    def drop_stale_edges(self) -> int:
        """Remove edges that point at ports which no longer exist or changed type (a block was edited)."""
        def alive(e: Edge) -> bool:
            src, dst = REGISTRY.get(self.nodes[e.src].type), REGISTRY.get(self.nodes[e.dst].type)
            if src is None or dst is None:
                return True                                # missing plugin: keep, validate() reports it
            return (e.src_port in src.OUTPUTS and e.dst_port in dst.INPUTS
                    and src.OUTPUTS[e.src_port] == dst.INPUTS[e.dst_port])
        before = len(self.edges)
        self.edges = [e for e in self.edges if alive(e)]
        return before - len(self.edges)

    def validate(self) -> list[tuple[str, str]]:
        """Return a list of (node_id, problem). Empty list means the graph can run."""
        problems: list[tuple[str, str]] = []
        for nid, inst in self.nodes.items():
            cls = REGISTRY.get(inst.type)
            if cls is None:
                problems.append((nid, t("Thiếu plugin cho node '{0}'").format(inst.type)))
                continue
            wired = self.inputs_of(nid)
            for port in cls.INPUTS:
                if port not in wired:
                    problems.append((nid, t("Cổng vào '{0}' chưa được nối").format(port)))
        try:
            self.topo_order()
        except GraphError as exc:
            problems.append(("", str(exc)))
        return problems

    # ---- serialisation -------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "nodes": [{"id": n.id, "type": n.type, "title": n.title, "params": copy.deepcopy(n.params),
                       "ui": {"x": n.x, "y": n.y}} for n in self.nodes.values()],
            "edges": [{"from": f"{e.src}.{e.src_port}", "to": f"{e.dst}.{e.dst_port}"} for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Graph":
        g = cls()
        for n in data.get("nodes", []):
            ui = n.get("ui", {})
            g.nodes[n["id"]] = NodeInst(n["id"], n["type"], copy.deepcopy(n.get("params", {})),
                                        ui.get("x", 0), ui.get("y", 0), n.get("title", n["type"]))
        for e in data.get("edges", []):
            src, sp = e["from"].rsplit(".", 1)
            dst, dp = e["to"].rsplit(".", 1)
            g.edges.append(Edge(src, sp, dst, dp))
        return g


@dataclass
class Recipe:
    id: str = "NEW-RECIPE"
    name: str = ""
    version: int = 1
    devices: dict[str, dict] = field(default_factory=dict)
    graph: Graph = field(default_factory=Graph)

    @property
    def label(self) -> str:
        return f"{self.id} (v{self.version})"

    @classmethod
    def load(cls, path: str | Path) -> "Recipe":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema_version", 1) > SCHEMA_VERSION:
            raise GraphError(t("Recipe được tạo bởi phiên bản mới hơn của VisionStudio"))
        meta = data.get("recipe", {})
        return cls(meta.get("id", "RECIPE"), meta.get("name", ""), meta.get("version", 1),
                   data.get("devices", {}), Graph.from_dict(data.get("graph", {})))

    def save(self, path: str | Path, bump_version: bool = True) -> None:
        if bump_version:
            self.version += 1
        data = {"schema_version": SCHEMA_VERSION,
                "recipe": {"id": self.id, "name": self.name, "version": self.version},
                "devices": self.devices, "graph": self.graph.to_dict()}
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")