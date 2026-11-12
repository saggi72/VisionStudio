"""Drag-and-drop node editor on QGraphicsScene: typed ports, bezier edges, profiling heatmap."""
from __future__ import annotations

from ..core.i18n import t

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPainterPath,
                         QPainterPathStroker, QPen, QPolygonF)
from PyQt6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsScene,
                             QGraphicsView, QMenu)

from ..core.graph import Edge, Graph, NodeInst
from ..core.node_base import REGISTRY, catalog
from ..core.schemas import PORT_COLORS
from . import theme

NODE_W, HEADER_H, ROW_H, PORT_R, FOOT_H = 208, 28, 20, 5, 22
HOT, WARM = 50.0, 20.0        # % of cycle time: red above HOT, amber above WARM
GRID = 10                     # nodes snap to this grid
PORT_HIT = 13                 # px around a port that still counts as a hit
MIME_NODE = "application/x-visionstudio-node"     # palette -> canvas drag payload (node type id)


class PortItem(QGraphicsEllipseItem):
    def __init__(self, node_item: "NodeItem", name: str, ptype, is_output: bool):
        super().__init__(-PORT_R, -PORT_R, 2 * PORT_R, 2 * PORT_R, node_item)
        self.node_item, self.name, self.ptype, self.is_output = node_item, name, ptype, is_output
        self.setBrush(QBrush(QColor(PORT_COLORS[ptype])))
        self.setPen(QPen(QColor("#111111"), 1))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAcceptHoverEvents(True)
        self.setToolTip(t("{0} : {1}  (kéo để nối)").format(name, ptype.value))

    def hoverEnterEvent(self, event) -> None:
        self.setScale(1.6)

    def hoverLeaveEvent(self, event) -> None:
        self.setScale(1.0)

    def set_hint(self, state: bool | None) -> None:
        """While a connection is dragged: True = valid target, False = not allowed, None = normal."""
        self.setScale(1.7 if state else 1.0)
        self.setOpacity(0.25 if state is False else 1.0)
        self.setPen(QPen(QColor(theme.TEXT_STRONG if state else "#111111"), 2 if state else 1))


class EdgeItem(QGraphicsPathItem):
    def __init__(self, edge: Edge, src: PortItem, dst: PortItem):
        super().__init__()
        self.edge, self.src, self.dst = edge, src, dst
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.update_path()

    def update_path(self) -> None:
        self.setPath(bezier(self.src.scenePos(), self.dst.scenePos()))

    def shape(self) -> QPainterPath:                # a wide band around the curve, easy to click
        stroker = QPainterPathStroker()
        stroker.setWidth(14)
        return stroker.createStroke(self.path())

    def paint(self, painter, option, widget=None) -> None:
        color = QColor(theme.TEXT_STRONG) if self.isSelected() else QColor(PORT_COLORS[self.src.ptype])
        painter.setPen(QPen(color, 3 if self.isSelected() else 2))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPath(self.path())


def bezier(p1: QPointF, p2: QPointF) -> QPainterPath:
    dx = max(40.0, abs(p2.x() - p1.x()) / 2)
    path = QPainterPath(p1)
    path.cubicTo(p1 + QPointF(dx, 0), p2 - QPointF(dx, 0), p2)
    return path


class NodeItem(QGraphicsItem):
    def __init__(self, inst: NodeInst):
        super().__init__()
        self.inst = inst
        self.cls = REGISTRY.get(inst.type)
        self.exec_ms: float | None = None
        self.score = 0.0
        self.heatmap = True
        self.invalid = ""
        ins = self.cls.INPUTS if self.cls else {}
        outs = self.cls.OUTPUTS if self.cls else {}
        rows = max(len(ins), len(outs), 1)
        self.h = HEADER_H + rows * ROW_H + 10 + FOOT_H
        self.in_ports: dict[str, PortItem] = {}
        self.out_ports: dict[str, PortItem] = {}
        for i, (name, ptype) in enumerate(ins.items()):
            port = PortItem(self, name, ptype, False)
            port.setPos(0, HEADER_H + 5 + i * ROW_H + ROW_H / 2)
            self.in_ports[name] = port
        for i, (name, ptype) in enumerate(outs.items()):
            port = PortItem(self, name, ptype, True)
            port.setPos(NODE_W, HEADER_H + 5 + i * ROW_H + ROW_H / 2)
            self.out_ports[name] = port
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
                      | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(inst.x, inst.y)

    def boundingRect(self) -> QRectF:
        return QRectF(-8, -8, NODE_W + 16, self.h + 16)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QPointF(round(value.x() / GRID) * GRID, round(value.y() / GRID) * GRID)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and self.scene():
            self.inst.x, self.inst.y = self.pos().x(), self.pos().y()
            self.scene().node_moved(self)
        return super().itemChange(change, value)

    def _heat(self) -> tuple[str, str]:
        if self.invalid:
            return theme.NG, theme.NODE_FILL
        if not self.heatmap or self.exec_ms is None:
            return theme.NODE_BORDER, theme.NODE_FILL
        if self.score > HOT:
            return theme.NG, theme.NG_BG
        if self.score > WARM:
            return theme.WARN, theme.WARN_BG
        return theme.OK, theme.OK_BG

    def paint(self, p: QPainter, option, widget=None) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        border, fill = self._heat()
        body = QRectF(0, 0, NODE_W, self.h)
        if self.isSelected():
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(body.adjusted(-4, -4, 4, 4), 10, 10)
        p.setPen(QPen(QColor(border), 2))
        p.setBrush(QColor(fill))
        p.drawRoundedRect(body, 8, 8)
        head = QPainterPath()
        head.addRoundedRect(QRectF(1, 1, NODE_W - 2, HEADER_H), 7, 7)
        p.fillPath(head, QColor(theme.NODE_HEAD))
        p.fillRect(QRectF(1, HEADER_H - 7, NODE_W - 2, 8), QColor(theme.NODE_HEAD))

        bold = QFont(p.font())
        bold.setBold(True)
        bold.setPointSizeF(8.5)
        mono = QFont("DejaVu Sans Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSizeF(7.5)
        badge = f"{self.exec_ms:.1f} ms" if self.exec_ms is not None else ""
        badge_w = QFontMetrics(mono).horizontalAdvance(badge) + 10 if badge else 0
        p.setFont(bold)
        p.setPen(QColor(theme.TEXT_STRONG))
        title = QFontMetrics(bold).elidedText(self.inst.title, Qt.TextElideMode.ElideRight, NODE_W - 22 - badge_w)
        p.drawText(QRectF(10, 0, NODE_W - 20, HEADER_H), Qt.AlignmentFlag.AlignVCenter, title)
        if badge:
            hot = self.heatmap and self.score > HOT
            r = QRectF(NODE_W - badge_w - 6, 6, badge_w, HEADER_H - 12)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.BTN_STOP) if hot else QColor(theme.NODE_FILL))
            p.drawRoundedRect(r, 3, 3)
            p.setFont(mono)
            p.setPen(QColor(theme.ON_COLOR) if hot else QColor(theme.OK))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, badge)

        small = QFont(p.font())
        small.setBold(False)
        small.setPointSizeF(8)
        p.setFont(small)
        p.setPen(QColor(theme.TEXT_DIM))
        for port in self.in_ports.values():
            p.drawText(QRectF(12, port.y() - ROW_H / 2, NODE_W / 2, ROW_H), Qt.AlignmentFlag.AlignVCenter, port.name)
        for port in self.out_ports.values():
            p.drawText(QRectF(NODE_W / 2 - 12, port.y() - ROW_H / 2, NODE_W / 2, ROW_H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, port.name)

        foot = QRectF(8, self.h - FOOT_H - 2, NODE_W - 16, FOOT_H - 4)
        text, bg, fg = "", None, theme.TEXT_DIM
        if self.invalid:
            text, bg, fg = self.invalid, QColor(theme.NG_BG), theme.NG
        elif self.heatmap and self.exec_ms is not None and self.score > HOT:
            text, bg, fg = t("Nút cổ chai · {0:.0f}% chu kỳ").format(self.score), QColor(theme.BTN_STOP), theme.ON_COLOR
        elif self.heatmap and self.exec_ms is not None:
            text = t("{0:.0f}% chu kỳ").format(self.score)
        if text:
            if bg:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(foot, 3, 3)
            tiny = QFont(small)
            tiny.setPointSizeF(7.5)
            tiny.setBold(bg is not None)
            p.setFont(tiny)
            p.setPen(QColor(fg))
            p.drawText(foot, Qt.AlignmentFlag.AlignCenter,
                       QFontMetrics(tiny).elidedText(text, Qt.TextElideMode.ElideRight, int(foot.width()) - 6))


class NodeScene(QGraphicsScene):
    node_selected = pyqtSignal(str)       # node id, or "" when nothing is selected
    graph_changed = pyqtSignal(str)       # structural change (nodes, edges, undo): engine must rebuild
    layout_changed = pyqtSignal()         # nodes were only moved
    history_changed = pyqtSignal()        # undo / redo availability changed
    message = pyqtSignal(str)

    _clipboard: dict | None = None        # shared by all scenes: copied nodes + the edges between them

    def __init__(self, parent=None):
        super().__init__(parent)
        self.graph = Graph()
        self.node_items: dict[str, NodeItem] = {}
        self.edge_items: list[EdgeItem] = []
        self._read_only = False
        self._heatmap = True
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._drag_src: PortItem | None = None
        self._temp: QGraphicsPathItem | None = None
        self._pre_move: dict | None = None
        self._paste_n = 0
        self.setBackgroundBrush(QColor(theme.BG_CANVAS))
        self.selectionChanged.connect(self._on_selection)

    # ---- access --------------------------------------------------------------------------
    @property
    def read_only(self) -> bool:
        return self._read_only

    @read_only.setter
    def read_only(self, value: bool) -> None:
        self._read_only = value
        for item in self.node_items.values():
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not value)

    def selected_nodes(self) -> list[NodeItem]:
        return [i for i in self.selectedItems() if isinstance(i, NodeItem)]

    def can_undo(self) -> bool:
        return bool(self._undo) and not self._read_only

    def can_redo(self) -> bool:
        return bool(self._redo) and not self._read_only

    # ---- build ---------------------------------------------------------------------------
    def load(self, graph: Graph, keep_history: bool = False) -> None:
        self.blockSignals(True)
        self.clear()
        self.blockSignals(False)
        self.graph, self.node_items, self.edge_items = graph, {}, []
        self._drag_src = self._temp = None
        if not keep_history:
            self._undo, self._redo = [], []
        for inst in graph.nodes.values():
            self._add_node_item(inst)
        for edge in graph.edges:
            self._add_edge_item(edge)
        self.refresh_validation()
        self._grow()
        self.history_changed.emit()

    def _grow(self) -> None:
        """Keep plenty of free canvas around the nodes so the layout can extend in any direction."""
        rect = self.itemsBoundingRect() if self.node_items else QRectF(0, 0, 1200, 700)
        self.setSceneRect(rect.adjusted(-1500, -1000, 1500, 1000))

    def _add_node_item(self, inst: NodeInst) -> NodeItem:
        item = NodeItem(inst)
        item.heatmap = self._heatmap
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not self._read_only)
        self.addItem(item)
        self.node_items[inst.id] = item
        return item

    def _add_edge_item(self, edge: Edge) -> None:
        src = self.node_items[edge.src].out_ports.get(edge.src_port)
        dst = self.node_items[edge.dst].in_ports.get(edge.dst_port)
        if src and dst:
            item = EdgeItem(edge, src, dst)
            self.addItem(item)
            self.edge_items.append(item)

    def _remove_edge_items(self, match) -> None:
        for e in [e for e in self.edge_items if match(e.edge)]:
            self.edge_items.remove(e)
            self.removeItem(e)

    # ---- undo / redo ---------------------------------------------------------------------
    def checkpoint(self) -> None:
        """Remember the current graph. Call BEFORE every change that should be undoable."""
        if self._read_only:
            return
        self._undo.append(self.graph.to_dict())
        del self._undo[:-60]
        self._redo.clear()
        self.history_changed.emit()

    def undo(self) -> None:
        if self.can_undo():
            self._redo.append(self.graph.to_dict())
            self._restore(self._undo.pop(), "UNDO")

    def redo(self) -> None:
        if self.can_redo():
            self._undo.append(self.graph.to_dict())
            self._restore(self._redo.pop(), "REDO")

    def _restore(self, data: dict, what: str) -> None:
        selected = [n.inst.id for n in self.selected_nodes()]
        self.load(Graph.from_dict(data), keep_history=True)
        for nid in selected:
            if nid in self.node_items:
                self.node_items[nid].setSelected(True)
        self.graph_changed.emit(what)
        self._on_selection()

    # ---- editing -------------------------------------------------------------------------
    def add_node(self, type_id: str, pos: QPointF) -> str:
        if self._read_only:
            return ""
        self.checkpoint()
        inst = self.graph.add_node(type_id, pos.x(), pos.y())
        item = self._add_node_item(inst)
        inst.x, inst.y = item.pos().x(), item.pos().y()       # after grid snap
        self.clearSelection()
        item.setSelected(True)
        self._changed(f"ADD_NODE {inst.id} ({type_id})")
        return inst.id

    def _changed(self, what: str) -> None:
        self.refresh_validation()
        self._grow()
        self.graph_changed.emit(what)

    def delete_selected(self) -> None:
        if self._read_only or not self.selectedItems():
            return
        self.checkpoint()
        changed = []
        for item in list(self.selectedItems()):
            if isinstance(item, EdgeItem) and item in self.edge_items:
                self.graph.remove_edge(item.edge)
                self.edge_items.remove(item)
                self.removeItem(item)
                changed.append(f"edge {item.edge.src}->{item.edge.dst}")
        for item in self.selected_nodes():
            nid = item.inst.id
            self._remove_edge_items(lambda e: nid in (e.src, e.dst))
            self.graph.remove_node(nid)
            self.node_items.pop(nid, None)
            self.removeItem(item)
            changed.append(f"node {nid}")
        self._changed("DELETE " + ", ".join(changed))

    def disconnect_node(self, node_id: str) -> None:
        edges = [e for e in self.graph.edges if node_id in (e.src, e.dst)]
        if self._read_only or not edges:
            return
        self.checkpoint()
        for edge in edges:
            self.graph.remove_edge(edge)
        self._remove_edge_items(lambda e: node_id in (e.src, e.dst))
        self._changed(f"DISCONNECT {node_id}")

    def select_all(self) -> None:
        for item in self.node_items.values():
            item.setSelected(True)

    def copy_selected(self) -> bool:
        nodes = self.selected_nodes()
        if not nodes:
            return False
        ids = {n.inst.id for n in nodes}
        NodeScene._clipboard = {
            "nodes": [{"id": n.inst.id, "type": n.inst.type, "title": n.inst.title, "x": n.inst.x, "y": n.inst.y,
                       "params": dict(n.inst.params)} for n in nodes],
            "edges": [(e.src, e.src_port, e.dst, e.dst_port) for e in self.graph.edges
                      if e.src in ids and e.dst in ids]}
        self._paste_n = 0
        self.message.emit(t("Đã sao chép {0} node").format(len(nodes)))
        return True

    def paste(self, at: QPointF | None = None) -> None:
        clip = NodeScene._clipboard
        if self._read_only or not clip:
            return
        self.checkpoint()
        self._paste_n += 1
        x0 = min(n["x"] for n in clip["nodes"])
        y0 = min(n["y"] for n in clip["nodes"])
        dx, dy = (at.x() - x0, at.y() - y0) if at is not None else (30 * self._paste_n, 30 * self._paste_n)
        new_ids, items = {}, []
        for n in clip["nodes"]:
            if n["type"] not in REGISTRY:
                continue
            inst = self.graph.add_node(n["type"], n["x"] + dx, n["y"] + dy, params=dict(n["params"]), title=n["title"])
            new_ids[n["id"]] = inst.id
            items.append(self._add_node_item(inst))
        for src, sp, dst, dp in clip["edges"]:
            if src in new_ids and dst in new_ids:
                self._add_edge_item(self.graph.add_edge(new_ids[src], sp, new_ids[dst], dp))
        self.clearSelection()
        for item in items:
            item.inst.x, item.inst.y = item.pos().x(), item.pos().y()
            item.setSelected(True)
        self._changed("PASTE " + ", ".join(new_ids.values()))

    def duplicate_selected(self) -> None:
        if self.copy_selected():
            self.paste()

    def auto_layout(self) -> None:
        """Arrange nodes left to right by pipeline depth."""
        if self._read_only or not self.node_items:
            return
        self.checkpoint()
        level: dict[str, int] = {}
        try:
            order = self.graph.topo_order()
        except Exception:
            order = list(self.graph.nodes)
        for nid in order:
            preds = [e.src for e in self.graph.edges if e.dst == nid and e.src in level]
            level[nid] = 1 + max((level[p] for p in preds), default=-1)
        columns: dict[int, list[str]] = {}
        for nid in order:
            columns.setdefault(level[nid], []).append(nid)
        for col, ids in columns.items():
            ids.sort(key=lambda n: self.graph.nodes[n].y)
            total = sum(self.node_items[n].h + 40 for n in ids) - 40
            y = 300 - total / 2
            for nid in ids:
                self.node_items[nid].setPos(60 + col * (NODE_W + 80), y)
                y += self.node_items[nid].h + 40
        self._grow()
        self.layout_changed.emit()

    def _connect(self, a: PortItem, b: PortItem | None) -> None:
        if b is None or a.is_output == b.is_output:
            self.message.emit(t("Chưa nối: hãy thả vào một cổng ") + (t("vào (bên trái node)") if a.is_output else t("ra (bên phải node)")))
            return
        src, dst = (a, b) if a.is_output else (b, a)
        s, d = src.node_item.inst.id, dst.node_item.inst.id
        err = self.graph.can_connect(s, src.name, d, dst.name)
        if err:
            self.message.emit(t("Không nối được: {0}").format(err))
            return
        self.checkpoint()
        self._remove_edge_items(lambda e: e.dst == d and e.dst_port == dst.name)   # an input takes one edge
        self._add_edge_item(self.graph.add_edge(s, src.name, d, dst.name))
        self._changed(f"CONNECT {s}.{src.name} -> {d}.{dst.name}")

    # ---- feedback ------------------------------------------------------------------------
    def refresh_validation(self) -> list[tuple[str, str]]:
        problems = self.graph.validate()
        by_node = {nid: msg for nid, msg in problems}
        for nid, item in self.node_items.items():
            item.invalid = by_node.get(nid, "")
            item.update()
        return problems

    def set_timings(self, timings: dict[str, float]) -> None:
        total = sum(timings.values()) or 1.0
        for nid, item in self.node_items.items():
            item.exec_ms = timings.get(nid)
            item.score = 100.0 * timings.get(nid, 0.0) / total
            item.update()

    def set_heatmap(self, on: bool) -> None:
        self._heatmap = on
        for item in self.node_items.values():
            item.heatmap = on
            item.update()

    def node_moved(self, node_item: NodeItem) -> None:
        nid = node_item.inst.id
        for e in self.edge_items:
            if nid in (e.edge.src, e.edge.dst):
                e.update_path()

    def _on_selection(self) -> None:
        nodes = self.selected_nodes()
        self.node_selected.emit(nodes[0].inst.id if nodes else "")

    # ---- mouse: connect ports, track moves -------------------------------------------------
    def _port_at(self, pos: QPointF) -> PortItem | None:
        best, best_d = None, 1e9
        for item in self.items(QRectF(pos.x() - PORT_HIT, pos.y() - PORT_HIT, 2 * PORT_HIT, 2 * PORT_HIT)):
            if isinstance(item, PortItem):
                d = (item.scenePos() - pos).manhattanLength()
                if d < best_d:
                    best, best_d = item, d
        return best

    def _hint_ports(self, src: PortItem | None) -> None:
        for node in self.node_items.values():
            for port in list(node.in_ports.values()) + list(node.out_ports.values()):
                if src is None or port is src:
                    port.set_hint(None)
                elif port.is_output == src.is_output:
                    port.set_hint(False)
                else:
                    o, i = (src, port) if src.is_output else (port, src)
                    port.set_hint(self.graph.can_connect(o.node_item.inst.id, o.name, i.node_item.inst.id, i.name) is None)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._read_only:
            port = self._port_at(event.scenePos())
            if port:
                self._drag_src = port
                self._temp = QGraphicsPathItem()
                self._temp.setPen(QPen(QColor(PORT_COLORS[port.ptype]), 2, Qt.PenStyle.DashLine))
                self._temp.setZValue(10)
                self.addItem(self._temp)
                self._hint_ports(port)
                event.accept()
                return
            self._pre_move = self.graph.to_dict()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._temp is not None:
            a, b = self._drag_src.scenePos(), event.scenePos()
            self._temp.setPath(bezier(a, b) if self._drag_src.is_output else bezier(b, a))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._temp is not None:
            self.removeItem(self._temp)
            self._temp, src = None, self._drag_src
            self._drag_src = None
            self._hint_ports(None)
            target = self._port_at(event.scenePos())
            if target is not src:
                self._connect(src, target)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        before, self._pre_move = self._pre_move, None
        if before is not None and not self._read_only:
            old = {n["id"]: (n.get("ui", {}).get("x"), n.get("ui", {}).get("y")) for n in before.get("nodes", [])}
            if any(old.get(nid) != (inst.x, inst.y) for nid, inst in self.graph.nodes.items()):
                self._undo.append(before)
                del self._undo[:-60]
                self._redo.clear()
                self._grow()
                self.history_changed.emit()
                self.layout_changed.emit()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor(theme.GRID_DOT), 1.5))
        step = 20
        while (rect.width() / step) * (rect.height() / step) > 20000:     # zoomed far out: thin the grid
            step *= 2
        x0, y0 = int(rect.left()) - int(rect.left()) % step, int(rect.top()) - int(rect.top()) % step
        points = QPolygonF([QPointF(x, y) for x in range(x0, int(rect.right()) + step, step)
                            for y in range(y0, int(rect.bottom()) + step, step)])
        if not points.isEmpty():
            painter.drawPoints(points)


class NodeView(QGraphicsView):
    """Canvas view. Wheel = zoom, middle-button drag = pan, drag on empty space = select area,
    right-click = context menu. Accepts node drops from the palette."""
    fit_requested = pyqtSignal()

    def __init__(self, scene: NodeScene):
        super().__init__(scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pan = None
        self._add_n = 0

    def node_scene(self) -> NodeScene:
        return self.scene()

    # ---- zoom and pan --------------------------------------------------------------------
    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if 0.25 < self.transform().m11() * factor < 2.5:
            self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pan is not None:
            delta = event.position() - self._pan
            self._pan = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._pan is not None:
            self._pan = None
            self.unsetCursor()
            return
        super().mouseReleaseEvent(event)

    def center_scene_pos(self) -> QPointF:
        return self.mapToScene(self.viewport().rect().center())

    def next_add_pos(self) -> QPointF:
        """Where a node added without a mouse position goes: view centre, cascading so nodes don't stack."""
        self._add_n = (self._add_n + 1) % 8
        return self.center_scene_pos() - QPointF(NODE_W / 2, 40) + QPointF(30 * self._add_n, 30 * self._add_n)

    # ---- keyboard ------------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:
        scene = self.node_scene()
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            scene.delete_selected()
        elif event.matches(QKeySequence.StandardKey.Undo):
            scene.undo()
        elif event.matches(QKeySequence.StandardKey.Redo) or (
                event.key() == Qt.Key.Key_Y and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            scene.redo()
        elif event.matches(QKeySequence.StandardKey.Copy):
            scene.copy_selected()
        elif event.matches(QKeySequence.StandardKey.Paste):
            scene.paste()
        elif event.matches(QKeySequence.StandardKey.SelectAll):
            scene.select_all()
        elif event.key() == Qt.Key.Key_D and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            scene.duplicate_selected()
        elif event.key() == Qt.Key.Key_F:
            self.fit_requested.emit()
        else:
            super().keyPressEvent(event)

    # ---- drop from the palette -----------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_NODE) and not self.node_scene().read_only:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_NODE):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(MIME_NODE):
            return
        type_id = bytes(event.mimeData().data(MIME_NODE)).decode()
        pos = self.mapToScene(event.position().toPoint()) - QPointF(NODE_W / 2, HEADER_H / 2)
        self.node_scene().add_node(type_id, pos)
        self.setFocus()
        event.acceptProposedAction()

    # ---- context menu --------------------------------------------------------------------
    def contextMenuEvent(self, event) -> None:
        scene = self.node_scene()
        scene_pos = self.mapToScene(event.pos())
        item = self.itemAt(event.pos())
        if isinstance(item, PortItem):
            item = item.node_item
        menu = QMenu(self)
        if scene.read_only:
            menu.addAction(t("Chế độ chỉ xem (cần quyền chỉnh sửa recipe)")).setEnabled(False)
        elif isinstance(item, NodeItem):
            if not item.isSelected():
                scene.clearSelection()
                item.setSelected(True)
            menu.addAction(t("Nhân bản\tCtrl+D"), scene.duplicate_selected)
            menu.addAction(t("Sao chép\tCtrl+C"), scene.copy_selected)
            menu.addAction(t("Ngắt mọi kết nối"), lambda: scene.disconnect_node(item.inst.id))
            menu.addSeparator()
            menu.addAction(t("Xóa\tDelete"), scene.delete_selected)
        elif isinstance(item, EdgeItem):
            scene.clearSelection()
            item.setSelected(True)
            menu.addAction(t("Xóa kết nối\tDelete"), scene.delete_selected)
        else:
            add = menu.addMenu(t("Thêm node tại đây"))
            for category, classes in catalog().items():
                sub = add.addMenu(t(category))
                for cls in classes:
                    sub.addAction(t(cls.TITLE), lambda type_id=cls.TYPE: scene.add_node(type_id, scene_pos))
            paste = menu.addAction(t("Dán\tCtrl+V"), lambda: scene.paste(scene_pos))
            paste.setEnabled(NodeScene._clipboard is not None)
            menu.addAction(t("Chọn tất cả\tCtrl+A"), scene.select_all)
            menu.addAction(t("Tự sắp xếp"), scene.auto_layout)
        menu.addSeparator()
        menu.addAction(t("Vừa khung\tF"), self.fit_requested.emit)
        menu.exec(event.globalPos())

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if self.node_scene().node_items:
            return
        painter.resetTransform()
        painter.setPen(QColor(theme.TEXT_DIM))
        font = QFont(painter.font())
        font.setPointSizeF(11)
        painter.setFont(font)
        painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                         t("Recipe chưa có node.\n\nKéo node từ danh sách bên trái vào đây,\n"
                         "hoặc nhấp chuột phải để thêm node."))