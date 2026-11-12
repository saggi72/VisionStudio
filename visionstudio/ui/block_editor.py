"""Block Python: create, edit, try and delete user blocks (nodes written in Python) from the Studio."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QHeaderView, QLineEdit, QListWidget, QMessageBox,
                             QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from ..core import userblock as ub
from ..core.i18n import t
from . import theme
from .context import AppContext
from .widgets import label


class CodeEdit(QPlainTextEdit):
    """Plain code editor: fixed-width font, Tab inserts four spaces, Enter keeps the indentation."""

    def __init__(self):
        super().__init__()
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(False)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Tab:
            self.insertPlainText("    ")
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            line = self.textCursor().block().text()[:self.textCursor().positionInBlock()]
            indent = line[:len(line) - len(line.lstrip(" "))]
            if line.rstrip().endswith(":"):
                indent += "    "
            self.insertPlainText("\n" + indent)
            return
        super().keyPressEvent(event)


class RowsTable(QWidget):
    """Small editable table with + / - buttons. A column given `choices` is edited with a combo box."""
    changed = pyqtSignal()

    def __init__(self, headers: list[str], choices: dict[int, list[str]], new_row: list[str]):
        super().__init__()
        self.choices, self.new_row = choices, new_row
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setFixedHeight(118)
        self.table.itemChanged.connect(lambda _i: self.changed.emit())
        col.addWidget(self.table)
        row = QHBoxLayout()
        add, remove = QPushButton("+"), QPushButton("-")
        for btn, slot in ((add, lambda: self.add_row(self._fresh_row())), (remove, self._remove)):
            btn.setFixedWidth(34)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        row.addStretch(1)
        col.addLayout(row)

    def _fresh_row(self) -> list[str]:
        names = {r[0] for r in self.rows()}
        base, name, n = self.new_row[0], self.new_row[0], 1
        while name in names:
            n += 1
            name = f"{base}{n}"
        return [name] + self.new_row[1:]

    def add_row(self, values: list) -> None:
        r = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(r)
        for c, value in enumerate(values):
            if c in self.choices:
                box = QComboBox()
                box.addItems(self.choices[c])
                box.setCurrentText(str(value))
                box.currentTextChanged.connect(lambda _t: self.changed.emit())
                self.table.setCellWidget(r, c, box)
            else:
                self.table.setItem(r, c, QTableWidgetItem(str(value)))
        self.table.blockSignals(False)
        self.changed.emit()

    def _remove(self) -> None:
        row = self.table.currentRow() if self.table.currentRow() >= 0 else self.table.rowCount() - 1
        if row >= 0:
            self.table.removeRow(row)
            self.changed.emit()

    def set_rows(self, rows: list[list]) -> None:
        self.table.setRowCount(0)
        for values in rows:
            self.add_row(list(values))

    def rows(self) -> list[list[str]]:
        out = []
        for r in range(self.table.rowCount()):
            values = []
            for c in range(self.table.columnCount()):
                box = self.table.cellWidget(r, c)
                item = self.table.item(r, c)
                values.append(box.currentText() if box is not None else (item.text().strip() if item else ""))
            out.append(values)
        return out


class BlockDialog(QDialog):
    """Left: the user's blocks. Right: name, ports, parameters and the Python code of the selected block."""
    blocks_changed = pyqtSignal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.is_new = True
        self.setWindowTitle(t("Block Python tự tạo"))
        self.resize(1080, 760)
        outer = QHBoxLayout(self)
        split = QSplitter()
        outer.addWidget(split)

        left = QWidget()
        lcol = QVBoxLayout(left)
        lcol.setContentsMargins(0, 0, 6, 0)
        lcol.addWidget(label(t("BLOCK CỦA BẠN"), "section"))
        self.listing = QListWidget()
        self.listing.currentRowChanged.connect(self._pick)
        lcol.addWidget(self.listing, 1)
        new_btn = QPushButton(t("Block mới"))
        new_btn.setObjectName("primary")
        new_btn.clicked.connect(self.new_block)
        self.delete_btn = QPushButton(t("Xóa block"))
        self.delete_btn.clicked.connect(self._delete)
        lcol.addWidget(new_btn)
        lcol.addWidget(self.delete_btn)
        split.addWidget(left)

        right = QWidget()
        col = QVBoxLayout(right)
        col.setContentsMargins(6, 0, 0, 0)
        col.setSpacing(6)
        top = QHBoxLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText(t("Tên hiển thị, ví dụ: Kiểm tra diện tích"))
        self.title.textEdited.connect(self._title_edited)
        self.name = QLineEdit()
        self.name.setPlaceholderText(t("mã block, ví dụ: kiem_tra_dien_tich"))
        self.name.setMaximumWidth(260)
        top.addWidget(self.title, 2)
        top.addWidget(self.name, 1)
        col.addLayout(top)
        self.desc = QLineEdit()
        self.desc.setPlaceholderText(t("Mô tả ngắn (hiện trong Inspector)"))
        col.addWidget(self.desc)

        tables = QHBoxLayout()
        self.inputs = RowsTable([t("Cổng vào"), t("Kiểu")], {1: ub.PORT_TYPES}, ["image", "IMAGE"])
        self.outputs = RowsTable([t("Cổng ra"), t("Kiểu")], {1: ub.PORT_TYPES}, ["result", "RESULT"])
        self.params = RowsTable([t("Tham số"), t("Kiểu"), t("Mặc định"), t("Nhãn")], {1: ub.PARAM_KINDS},
                                ["value", "float", "0", ""])
        tables.addWidget(self.inputs, 2)
        tables.addWidget(self.outputs, 2)
        tables.addWidget(self.params, 3)
        col.addLayout(tables)

        self.signature = label("", "dim")
        self.signature.setStyleSheet(f"font-family:{theme.MONO}; color:{theme.INFO};")
        col.addWidget(self.signature)
        self.code = CodeEdit()
        col.addWidget(self.code, 3)
        buttons = QHBoxLayout()
        template = QPushButton(t("Tạo lại mã mẫu"))
        template.setToolTip(t("Thay mã hiện tại bằng mã mẫu khớp với các cổng và tham số đang khai báo"))
        template.clicked.connect(self._template)
        self.try_btn = QPushButton(t("Chạy thử"))
        self.try_btn.setToolTip(t("Chạy block một lần trên dữ liệu mẫu, không lưu"))
        self.try_btn.clicked.connect(self.try_block)
        self.save_btn = QPushButton(t("Lưu block"))
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.save_block)
        close = QPushButton(t("Đóng"))
        close.clicked.connect(self.accept)
        buttons.addWidget(template)
        buttons.addStretch(1)
        buttons.addWidget(self.try_btn)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(close)
        col.addLayout(buttons)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFixedHeight(120)
        self.output.setStyleSheet(f"font-family:{theme.MONO};")
        col.addWidget(self.output)
        split.addWidget(right)
        split.setSizes([220, 860])

        for table in (self.inputs, self.outputs, self.params):
            table.changed.connect(self._update_signature)
        self.reload_list()
        if self.listing.count():
            self.listing.setCurrentRow(0)
        else:
            self.new_block()

    # ---- list ----------------------------------------------------------------------------
    def reload_list(self, select: str = "") -> None:
        self.specs = ub.list_blocks()
        self.listing.blockSignals(True)
        self.listing.clear()
        self.listing.addItems([f"{s['title']}  ({s['name']})" for s in self.specs])
        self.listing.blockSignals(False)
        names = [s["name"] for s in self.specs]
        if select in names:
            self.listing.setCurrentRow(names.index(select))

    def _pick(self, row: int) -> None:
        if 0 <= row < len(self.specs):
            self.load_spec(self.specs[row], is_new=False)

    def new_block(self) -> None:
        self.listing.blockSignals(True)
        self.listing.setCurrentRow(-1)
        self.listing.blockSignals(False)
        self.load_spec(ub.new_spec(), is_new=True)
        self.title.setFocus()

    # ---- form <-> spec -------------------------------------------------------------------
    def load_spec(self, spec: dict, is_new: bool) -> None:
        self.is_new = is_new
        self.title.setText(spec["title"])
        self.name.setText(spec["name"])
        self.name.setEnabled(is_new)                       # the code identifies the block in recipes
        self.desc.setText(spec.get("desc", ""))
        self.inputs.set_rows(spec["inputs"])
        self.outputs.set_rows(spec["outputs"])
        self.params.set_rows(spec["params"])
        self.code.setPlainText(spec["code"])
        self.delete_btn.setEnabled(not is_new)
        self.output.setPlainText("")
        self._update_signature()

    def spec(self) -> dict:
        return {"name": self.name.text().strip(), "title": self.title.text().strip(), "desc": self.desc.text().strip(),
                "inputs": self.inputs.rows(), "outputs": self.outputs.rows(), "params": self.params.rows(),
                "code": self.code.toPlainText()}

    def _title_edited(self, text: str) -> None:
        if self.is_new:
            self.name.setText(ub.slugify(text))

    def _update_signature(self) -> None:
        args = "".join(f", {row[0]}" for row in self.inputs.rows())
        outs = ", ".join(f'"{row[0]}": ...' for row in self.outputs.rows())
        self.signature.setText(f"def run(self, ctx, params{args}):      # return {{{outs}}}")

    def _say(self, text: str, good: bool) -> None:
        self.output.setPlainText(text)
        self.output.setStyleSheet(f"font-family:{theme.MONO}; color:{theme.OK if good else theme.NG};")

    # ---- actions -------------------------------------------------------------------------
    def _template(self) -> None:
        self.code.setPlainText(ub.default_code(self.spec()))

    def try_block(self) -> bool:
        last = self.ctx.engine.last_job
        image = last.preview if last is not None and last.preview is not None else None
        try:
            ok, text, _outputs = ub.trial_run(self.spec(), image=image)
        except ub.BlockError as exc:
            ok, text = False, str(exc)
        self._say(text, ok)
        return ok

    def save_block(self) -> bool:
        spec = self.spec()
        try:
            ub.check_spec(spec)
            if not self.try_block():
                return False                               # a block that fails its trial run is not saved
            path = ub.save_block(spec, overwrite=not self.is_new)
        except ub.BlockError as exc:
            self._say(str(exc), False)
            return False
        self.ctx.audit("SAVE_BLOCK", f"{ub.type_id(spec)} -> {path.name}")
        self._say(self.output.toPlainText() + "\n" + t("Đã lưu: {0}").format(path), True)
        self.reload_list(select=spec["name"])
        self.is_new = False
        self.name.setEnabled(False)
        self.delete_btn.setEnabled(True)
        self.blocks_changed.emit()
        return True

    def _delete(self) -> None:
        name = self.name.text().strip()
        used = [n.id for n in self.ctx.engine.recipe.graph.nodes.values() if n.type == f"user.{name}"]
        text = t("Xóa block '{0}' và file của nó?").format(self.title.text())
        if used:
            text += "\n" + t("Recipe đang mở có node dùng block này: {0}. Các node đó sẽ báo thiếu plugin.").format(", ".join(used))
        if QMessageBox.question(self, t("Xóa block"), text) != QMessageBox.StandardButton.Yes:
            return
        ub.delete_block(name)
        self.ctx.audit("DELETE_BLOCK", f"user.{name}")
        self.reload_list()
        self.blocks_changed.emit()
        if self.listing.count():
            self.listing.setCurrentRow(0)
        else:
            self.new_block()