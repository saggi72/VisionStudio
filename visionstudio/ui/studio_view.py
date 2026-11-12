"""Studio tab: node palette, graph canvas with profiling heatmap, inspector with live probe."""
from __future__ import annotations

from ..core.i18n import t

import re
from pathlib import Path

from PyQt6.QtCore import QMimeData, Qt, QTimer
from PyQt6.QtGui import QColor, QDrag
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                             QScrollArea, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core.executor import probe_image
from ..core.graph import Graph, Recipe
from ..core.node_base import REGISTRY, Param, catalog
from ..core.schemas import PortType
from . import theme
from .context import AppContext
from .node_editor import MIME_NODE, NodeScene, NodeView
from .widgets import ImageView, label


class PaletteTree(QTreeWidget):
    """Node list. Drag an entry onto the canvas, or double-click it."""

    def startDrag(self, _actions) -> None:
        item = self.currentItem()
        type_id = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not type_id:
            return
        mime = QMimeData()
        mime.setData(MIME_NODE, type_id.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class RecipeInfoDialog(QDialog):
    """Recipe ID and description, used for 'new recipe' and 'edit recipe info'."""

    def __init__(self, title: str, recipe_id: str = "", name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        col = QVBoxLayout(self)
        form = QFormLayout()
        self.id_edit = QLineEdit(recipe_id)
        self.id_edit.setPlaceholderText(t("ví dụ: BRACKET-A12"))
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText(t("mô tả ngắn về sản phẩm / phép kiểm"))
        form.addRow(t("Mã recipe (ID)"), self.id_edit)
        form.addRow(t("Mô tả"), self.name_edit)
        col.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Hủy"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

    def _accept(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{2,40}", self.id_edit.text().strip()):
            QMessageBox.warning(self, self.windowTitle(), t("Mã recipe gồm 2-40 ký tự: chữ không dấu, số, '_', '.', '-'."))
            return
        self.accept()

    def values(self) -> tuple[str, str]:
        return self.id_edit.text().strip().upper(), self.name_edit.text().strip()


class StudioView(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.selected = ""
        self.scene = NodeScene(self)            # parented: Qt deletes it together with this view
        self.view = NodeView(self.scene)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_palette())
        row.addWidget(self._build_center(), 1)
        row.addWidget(self._build_inspector())

        self.scene.node_selected.connect(self._on_select)
        self.scene.selectionChanged.connect(self._update_actions)
        self.scene.graph_changed.connect(self._on_graph_changed)
        self.scene.layout_changed.connect(ctx.set_dirty)
        self.scene.history_changed.connect(self._update_actions)
        self.scene.message.connect(self._flash)
        self.view.fit_requested.connect(self.fit_view)
        ctx.job_done.connect(self._on_job)
        ctx.role_changed.connect(self._apply_role)
        ctx.recipe_changed.connect(self._update_recipe_info)
        ctx.dirty_changed.connect(lambda _d: self._update_recipe_info())
        self.reload()
        self._apply_role()

    # ---- layout --------------------------------------------------------------------------
    def _build_palette(self) -> QWidget:
        side = QWidget()
        side.setObjectName("side")
        side.setFixedWidth(250)
        col = QVBoxLayout(side)
        col.setContentsMargins(8, 8, 8, 8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(t("Tìm kiếm node..."))
        self.search.textChanged.connect(self._fill_palette)
        self.tree = PaletteTree()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(10)
        self.tree.setDragEnabled(True)
        self.tree.itemDoubleClicked.connect(self._add_from_palette)
        col.addWidget(self.search)
        col.addWidget(self.tree, 1)
        col.addWidget(label(t("Kéo node vào sơ đồ (hoặc nhấp đúp).\nNối: kéo từ cổng này sang cổng kia.\n"
                            "Chuột phải: menu thêm / nhân bản / xóa.\nLăn chuột: zoom. Giữ nút giữa: di chuyển.\n"
                            "Delete, Ctrl+Z / Y, Ctrl+C / V / D, F."), "dim", wrap=True))
        self._fill_palette()
        return side

    def _fill_palette(self) -> None:
        text = self.search.text().lower()
        self.tree.clear()
        for category, classes in catalog().items():
            matches = [c for c in classes if text in t(c.TITLE).lower() or text in c.TYPE.lower()]
            if not matches:
                continue
            top = QTreeWidgetItem([t(category).upper()])
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            top.setForeground(0, QColor(theme.TEXT_DIM))
            for c in matches:
                child = QTreeWidgetItem([t(c.TITLE)])
                child.setData(0, Qt.ItemDataRole.UserRole, c.TYPE)
                child.setToolTip(0, t(c.DESC) or c.TYPE)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()

    def _button(self, text: str, slot, tip: str = "", obj: str = "") -> QPushButton:
        btn = QPushButton(text)
        btn.clicked.connect(slot)
        btn.setToolTip(tip)
        if obj:
            btn.setObjectName(obj)
        return btn

    def _build_center(self) -> QWidget:
        center = QWidget()
        col = QVBoxLayout(center)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # row 1: recipe file actions
        bar1 = QWidget()
        bar1.setObjectName("side")
        bar1.setFixedHeight(40)
        row = QHBoxLayout(bar1)
        row.setContentsMargins(12, 4, 12, 4)
        self.recipe_info = label("", wrap=False)
        self.info_btn = self._button(t("Sửa thông tin"), self._edit_info, t("Đổi mã và mô tả của recipe"))
        self.new_btn = self._button(t("Tạo mới"), self._new_recipe, t("Tạo recipe trống, giữ danh sách thiết bị hiện tại"))
        self.open_btn = self._button(t("Mở…"), self._open_recipe, t("Mở file recipe .json"))
        self.save_as_btn = self._button(t("Lưu thành…"), self._save_recipe_as, t("Lưu thành file recipe mới"))
        self.save_btn = self._button(t("Lưu Recipe"), self._save_recipe, t("Lưu và tăng số phiên bản"), "primary")
        self.block_btn = self._button(t("Block Python…"), self._open_blocks,
                                      t("Tự viết block bằng Python: tạo, sửa, chạy thử, xóa"))
        row.addWidget(self.recipe_info, 1)
        for b in (self.block_btn, self.info_btn, self.new_btn, self.open_btn, self.save_as_btn, self.save_btn):
            row.addWidget(b)
        col.addWidget(bar1)

        # row 2: layout editing actions
        bar2 = QWidget()
        bar2.setObjectName("side")
        bar2.setFixedHeight(40)
        row = QHBoxLayout(bar2)
        row.setContentsMargins(12, 4, 12, 4)
        self.undo_btn = self._button(t("↶ Hoàn tác"), self.scene.undo, "Ctrl+Z")
        self.redo_btn = self._button(t("↷ Làm lại"), self.scene.redo, "Ctrl+Y")
        self.dup_btn = self._button(t("Nhân bản"), self.scene.duplicate_selected, "Ctrl+D")
        self.del_btn = self._button(t("Xóa"), self.scene.delete_selected, "Delete")
        self.layout_btn = self._button(t("Tự sắp xếp"), self.scene.auto_layout, t("Xếp node từ trái sang phải theo luồng xử lý"))
        fit_btn = self._button(t("Vừa khung"), self.fit_view, "F")
        self.heat_btn = QPushButton("Heatmap (ON)")
        self.heat_btn.setObjectName("amber")
        self.heat_btn.setCheckable(True)
        self.heat_btn.setChecked(True)
        self.heat_btn.toggled.connect(self._toggle_heatmap)
        self.status = label("", "dim")
        for b in (self.undo_btn, self.redo_btn, self.dup_btn, self.del_btn, self.layout_btn, fit_btn):
            row.addWidget(b)
        row.addSpacing(10)
        row.addWidget(self.status, 1)
        row.addWidget(self.heat_btn)
        col.addWidget(bar2)

        # read-only notice
        self.lock_bar = QWidget()
        self.lock_bar.setStyleSheet(f"background:{theme.WARN_BG}; border-bottom:1px solid {theme.WARN};")
        row = QHBoxLayout(self.lock_bar)
        row.setContentsMargins(12, 6, 12, 6)
        self.lock_text = QLabel()
        self.lock_text.setStyleSheet(f"color:{theme.WARN}; font-weight:bold; border:none;")
        login = self._button(t("Đăng nhập"), self._login, obj="primary")
        row.addWidget(self.lock_text, 1)
        row.addWidget(login)
        col.addWidget(self.lock_bar)

        col.addWidget(self.view, 1)
        return center

    def _build_inspector(self) -> QWidget:
        side = QWidget()
        side.setObjectName("side")
        side.setFixedWidth(320)
        col = QVBoxLayout(side)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(label("Inspector & Live Probe", "section"), 1)
        self.id_label = label("", "dim")
        head.addWidget(self.id_label)
        col.addLayout(head)
        col.addWidget(label("LIVE PROBE", "caption"))
        self.probe = ImageView(t("Chọn node và bấm START\nđể xem đầu ra của node"), fixed_h=180)
        col.addWidget(self.probe)
        self.time_label = label("", "dim")
        col.addWidget(self.time_label)
        self.prop_title = label(t("THUỘC TÍNH NODE"), "caption")
        col.addWidget(self.prop_title)
        self.node_doc = label("", "dim", wrap=True)
        col.addWidget(self.node_doc)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(self.form_host)
        col.addWidget(scroll, 1)
        return side

    # ---- state ---------------------------------------------------------------------------
    def fit_view(self) -> None:
        port = self.view.viewport()
        if port.width() < 200 or port.height() < 150:        # not laid out yet; showEvent fits again
            return
        rect = self.scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        self.view.resetTransform()
        if not self.scene.node_items:
            self.view.centerOn(600, 350)
            return
        factor = min(port.width() / rect.width(), port.height() / rect.height(), 1.0)
        factor = max(factor, 0.25)                           # same lower limit as the mouse-wheel zoom
        self.view.scale(factor, factor)
        self.view.centerOn(rect.center())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self.fit_view)

    def reload(self) -> None:
        """Show the engine's current recipe (after open / new)."""
        recipe = self.ctx.engine.recipe
        if recipe:
            self.scene.load(recipe.graph)
            self._show_validation()
        self._on_select("")
        self._update_recipe_info()
        self._update_actions()
        QTimer.singleShot(0, self.fit_view)

    def _editable(self) -> bool:
        return self.ctx.can("recipe.edit")

    def _apply_role(self, *_):
        editable = self._editable()
        self.scene.read_only = not editable
        for w in (self.info_btn, self.new_btn, self.open_btn, self.save_as_btn, self.save_btn, self.layout_btn,
                  self.tree, self.form_host):
            w.setEnabled(editable)
        self.block_btn.setEnabled(editable and self.ctx.can("blocks.edit"))
        self.block_btn.setToolTip(t("Tự viết block bằng Python: tạo, sửa, chạy thử, xóa") if self.ctx.can("blocks.edit")
                                  else t("Cần quyền 'Tạo, sửa, xóa block Python'"))
        self.lock_bar.setVisible(not editable)
        who = self.ctx.user["username"] if self.ctx.logged_in else t("chưa đăng nhập")
        self.lock_text.setText(t("Chế độ chỉ xem: {0} · vai trò {1} không có quyền chỉnh sửa recipe. Đăng nhập tài khoản Engineer, Admin hoặc Developer để tạo và sửa layout.").format(who, self.ctx.role))
        self._update_actions()

    def _update_actions(self) -> None:
        editable = self._editable()
        try:
            has_node = bool(self.scene.selected_nodes())
        except RuntimeError:                     # the scene is being destroyed with the window
            return
        self.undo_btn.setEnabled(self.scene.can_undo())
        self.redo_btn.setEnabled(self.scene.can_redo())
        self.dup_btn.setEnabled(editable and has_node)
        self.del_btn.setEnabled(editable and bool(self.scene.selectedItems()))

    def _update_recipe_info(self) -> None:
        recipe = self.ctx.engine.recipe
        if not recipe:
            return
        dirty = t("  <span style='color:{0}'>● chưa lưu</span>").format(theme.WARN) if self.ctx.dirty else ""
        name = f" · {recipe.name}" if recipe.name else ""
        self.recipe_info.setText(f"<b>{recipe.label}</b>{name}  "
                                 f"<span style='color:{theme.TEXT_DIM}'>[{Path(self.ctx.recipe_path).name}]</span>{dirty}")

    def _flash(self, text: str) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{theme.WARN};")
        QTimer.singleShot(4000, self._show_validation)

    def _toggle_heatmap(self, on: bool) -> None:
        self.heat_btn.setText(f"Heatmap ({'ON' if on else 'OFF'})")
        self.scene.set_heatmap(on)

    def _show_validation(self) -> None:
        problems = self.scene.refresh_validation()
        if problems:
            self.status.setText(t("{0} lỗi cấu hình - {1}").format(len(problems), problems[0][1]))
            self.status.setStyleSheet(f"color:{theme.NG};")
        elif not any(PortType.RESULT in REGISTRY[n.type].OUTPUTS.values() for n in self.scene.graph.nodes.values()):
            self.status.setText(t("Chưa có node cho ra kết quả OK/NG (ví dụ: Count by Class) - job sẽ báo ERROR"))
            self.status.setStyleSheet(f"color:{theme.WARN};")
        else:
            self.status.setText(t("Hợp lệ · {0} node · {1} kết nối").format(len(self.scene.graph.nodes), len(self.scene.graph.edges)))
            self.status.setStyleSheet(f"color:{theme.OK};")

    def _login(self) -> None:
        from .users_view import LoginDialog
        LoginDialog(self.ctx, self).exec()

    # ---- graph editing -------------------------------------------------------------------
    def _add_from_palette(self, item: QTreeWidgetItem) -> None:
        type_id = item.data(0, Qt.ItemDataRole.UserRole)
        if type_id:
            self.scene.add_node(type_id, self.view.next_add_pos())

    def _on_graph_changed(self, what: str) -> None:
        self.ctx.engine.recipe.graph = self.scene.graph        # undo / redo replace the graph object
        self._show_validation()
        self.ctx.engine.update_graph(self.scene.graph)
        self.ctx.audit("EDIT_GRAPH", what)
        self.ctx.set_dirty()
        self._on_select(self.selected if self.selected in self.scene.graph.nodes else "")
        self._update_actions()

    # ---- user blocks ---------------------------------------------------------------------
    def _open_blocks(self) -> None:
        from .block_editor import BlockDialog
        dialog = BlockDialog(self.ctx, self)
        dialog.blocks_changed.connect(self.blocks_changed)
        dialog.exec()

    def blocks_changed(self) -> None:
        """A user block was saved or deleted: refresh the node list and every node that uses it."""
        self._fill_palette()
        graph = self.scene.graph
        dropped = graph.drop_stale_edges()                 # its ports may have changed
        selected = self.selected
        self.scene.load(graph, keep_history=True)
        self.ctx.engine.update_graph(graph)
        self._show_validation()
        if dropped:
            self.ctx.set_dirty()
            self._flash(t("Block đổi cổng: đã gỡ {0} đường nối không còn hợp lệ").format(dropped))
        if selected in graph.nodes:
            self.scene.node_items[selected].setSelected(True)
        else:
            self._on_select("")

    # ---- recipe files --------------------------------------------------------------------
    def confirm_discard(self) -> bool:
        """Ask before throwing away unsaved edits. True = go ahead."""
        if not self.ctx.dirty:
            return True
        box = QMessageBox(QMessageBox.Icon.Question, t("Recipe chưa lưu"),
                          t("Recipe {0} có thay đổi chưa lưu.").format(self.ctx.engine.recipe.label), parent=self)
        save = box.addButton(t("Lưu"), QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton(t("Bỏ thay đổi"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(t("Hủy"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            return self._save_recipe()
        return box.clickedButton() is discard

    def _set_recipe(self, recipe: Recipe, path: str, audit: tuple[str, str]) -> None:
        self.ctx.engine.load_recipe(recipe)
        self.ctx.recipe_path = path
        self.ctx.audit(*audit)
        self.ctx.set_dirty(False)
        self.reload()
        self.ctx.recipe_changed.emit()

    def _new_recipe(self) -> None:
        if not self.confirm_discard():
            return
        dlg = RecipeInfoDialog(t("Tạo recipe mới"), parent=self)
        if not dlg.exec():
            return
        rid, name = dlg.values()
        current = self.ctx.engine.recipe
        path = Path(self.ctx.recipe_path).parent / f"{rid.lower().replace('-', '_')}.json"
        if path.exists() and QMessageBox.question(
                self, t("Tạo recipe mới"), t("File {0} đã tồn tại và sẽ bị ghi đè khi lưu. Tiếp tục?").format(path.name)) \
                != QMessageBox.StandardButton.Yes:
            return
        import copy
        recipe = Recipe(rid, name, 0, copy.deepcopy(current.devices) if current else {}, Graph())
        self._set_recipe(recipe, str(path), ("NEW_RECIPE", rid))
        self.ctx.set_dirty()

    def _edit_info(self) -> None:
        recipe = self.ctx.engine.recipe
        dlg = RecipeInfoDialog(t("Thông tin recipe"), recipe.id, recipe.name, parent=self)
        if dlg.exec():
            recipe.id, recipe.name = dlg.values()
            self.ctx.audit("EDIT_RECIPE_INFO", f"{recipe.id} · {recipe.name}")
            self.ctx.set_dirty()
            self.ctx.recipe_changed.emit()

    def _open_recipe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("Mở recipe"), str(Path(self.ctx.recipe_path).parent), "Recipe (*.json)")
        if path and self.confirm_discard():
            self.open_recipe(path)

    def open_recipe(self, path: str) -> bool:
        try:
            recipe = Recipe.load(path)
        except Exception as exc:
            QMessageBox.warning(self, t("Không mở được recipe"), f"{type(exc).__name__}: {exc}")
            return False
        self._set_recipe(recipe, path, ("OPEN_RECIPE", f"{recipe.label} <- {path}"))
        self.ctx.store.set("last_recipe", path)
        return True

    def _save_recipe(self) -> bool:
        recipe = self.ctx.engine.recipe
        problems = self.scene.graph.validate()
        if problems and QMessageBox.question(self, t("Recipe chưa hợp lệ"),
                                             t("Còn {0} lỗi cấu hình. Vẫn lưu?").format(len(problems))) != QMessageBox.StandardButton.Yes:
            return False
        recipe.graph = self.scene.graph
        try:
            recipe.save(self.ctx.recipe_path)
        except OSError as exc:
            QMessageBox.warning(self, t("Không lưu được"), str(exc))
            return False
        self.ctx.store.set("last_recipe", self.ctx.recipe_path)
        self.ctx.audit("SAVE_RECIPE", recipe.label)
        self.ctx.set_dirty(False)
        self.ctx.recipe_changed.emit()
        self.status.setText(t("Đã lưu {0}").format(recipe.label))
        return True

    def _save_recipe_as(self) -> None:
        recipe = self.ctx.engine.recipe
        path, _ = QFileDialog.getSaveFileName(self, t("Lưu recipe thành"), str(Path(self.ctx.recipe_path).parent),
                                              "Recipe (*.json)")
        if path:
            self.save_recipe_as(path if path.lower().endswith(".json") else path + ".json")

    def save_recipe_as(self, path: str) -> None:
        recipe = self.ctx.engine.recipe
        recipe.graph = self.scene.graph
        recipe.id, recipe.version = Path(path).stem.upper().replace("_", "-"), 0
        self.ctx.recipe_path = path
        self.ctx.audit("SAVE_RECIPE_AS", f"{recipe.id} -> {path}")
        self._save_recipe()

    # ---- inspector -----------------------------------------------------------------------
    def _on_job(self, job) -> None:
        if not self.isVisible():
            return
        self.scene.set_timings(job.timings)
        img = probe_image(job, self.selected) if self.selected else job.preview
        self.probe.set_image(img)
        if self.selected in job.timings:
            self.time_label.setText(t("Thời gian node: {0:.2f} ms · cả chu kỳ: {1:.1f} ms").format(job.timings[self.selected], job.cycle_ms))

    def _on_select(self, node_id: str) -> None:
        self.selected = node_id
        while self.form.rowCount():
            self.form.removeRow(0)
        inst = self.scene.graph.nodes.get(node_id)
        self.id_label.setText(f"ID: {node_id}" if inst else "")
        self.time_label.setText("")
        if not inst:
            self.prop_title.setText(t("THUỘC TÍNH NODE"))
            self.node_doc.setText("")
            self.form.addRow(label(t("Chọn một node trên sơ đồ để xem và sửa thuộc tính."), "dim", wrap=True))
            return
        cls = REGISTRY.get(inst.type)
        self.prop_title.setText(t("THUỘC TÍNH NODE ({0})").format(inst.type))
        self.node_doc.setText(t(cls.DESC) if cls else t("Thiếu plugin cho loại node này."))
        title = QLineEdit(inst.title)
        title.editingFinished.connect(lambda: self._rename(inst, title.text()))
        self.form.addRow(t("Tên hiển thị"), title)
        for param in (cls.PARAMS if cls else []):
            self.form.addRow(t(param.label) or param.name, self._editor(inst, param))
        if self.ctx.engine.last_job:
            self.probe.set_image(probe_image(self.ctx.engine.last_job, node_id))

    def _rename(self, inst, text: str) -> None:
        text = text.strip()
        if text and text != inst.title:
            self.scene.checkpoint()
            inst.title = text
            self.scene.node_items[inst.id].update()
            self.ctx.set_dirty()

    def _set_param(self, inst, name: str, value) -> None:
        if inst.params.get(name) == value:
            return
        self.scene.checkpoint()
        inst.params[name] = value
        self.ctx.engine.update_graph(self.scene.graph)
        self.ctx.audit("EDIT_PARAM", f"{inst.id}.{name} = {value}")
        self.ctx.set_dirty()

    def _editor(self, inst, param: Param) -> QWidget:
        value = inst.params.get(param.name, param.default)
        setter = lambda v, n=param.name: self._set_param(inst, n, v)
        if param.kind == "int":
            w = QSpinBox()
            w.setRange(int(param.min if param.min is not None else -10**9), int(param.max if param.max is not None else 10**9))
            w.setValue(int(value))
            w.valueChanged.connect(setter)
        elif param.kind == "float":
            w = QDoubleSpinBox()
            w.setDecimals(2)
            w.setSingleStep(0.05)
            w.setRange(param.min if param.min is not None else -1e9, param.max if param.max is not None else 1e9)
            w.setValue(float(value))
            w.valueChanged.connect(setter)
        elif param.kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
            w.toggled.connect(setter)
        elif param.kind == "choice" or param.kind.startswith("device:"):
            w = QComboBox()
            if param.kind == "device:camera":
                options = list(self.ctx.engine.devices.cameras)
            elif param.kind == "device:plc":
                options = list(self.ctx.engine.devices.plcs)
            elif param.kind == "device:comm":
                options = list(self.ctx.engine.devices.comms)
            else:
                options = list(param.choices or [])
            if value not in options:
                options.append(str(value))
            w.addItems(options)
            w.setCurrentText(str(value))
            w.currentTextChanged.connect(setter)
        elif param.kind == "file":
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(str(value))
            edit.editingFinished.connect(lambda: setter(edit.text()))
            browse = QPushButton("…")
            browse.setFixedWidth(36)
            browse.setStyleSheet("padding:6px 0;")

            def pick():
                path, _ = QFileDialog.getOpenFileName(self, t("Chọn file"), "", "Model (*.onnx *.pt);;All (*)")
                if path:
                    edit.setText(path)
                    setter(path)
            browse.clicked.connect(pick)
            row.addWidget(edit, 1)
            row.addWidget(browse)
        else:
            w = QLineEdit(str(value))
            w.editingFinished.connect(lambda: setter(w.text()))
        return w