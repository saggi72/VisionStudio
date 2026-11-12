"""User blocks: nodes written by the user in Python from inside the Studio (Qt-free part).

A block is described by a small spec (title, ports, parameters, code). Saving it writes an ordinary
plugin file `plugins/user_<name>.py` and loads it, so the block appears in the node list at once and
is loaded like any other plugin at the next start. The spec is kept in the file's header so the
editor can open the block again.

The code the user writes is the body of   def run(self, ctx, params, <one argument per input port>):
and must return a dict with one entry per output port. For convenience the return values may be
plain Python: a numpy image for an IMAGE port, a number for MEASUREMENT, True / False / "OK" / "NG"
for RESULT.
"""
from __future__ import annotations

import json
import keyword
import re
import textwrap
import traceback
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np

from . import node_base
from .i18n import t
from .node_base import Node
from .schemas import Detection, Detections, Frame, InspectionResult, Measurement, PortType

CATEGORY = "Block tự tạo (User)"
SPEC_MARK = "# VS_BLOCK_SPEC: "
FILE_PREFIX = "user_"
PORT_TYPES = [pt.name for pt in (PortType.IMAGE, PortType.DETECTIONS, PortType.MEASUREMENT, PortType.RESULT)]
PARAM_KINDS = ["int", "float", "bool", "str"]
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
_RESERVED = {"self", "ctx", "params"}


class BlockError(Exception):
    """A problem with a block spec or its code, with a message for the user."""


# ---- runtime base class ----------------------------------------------------------------------
class UserNode(Node):
    """Base class of every generated block: calls the user's run() and checks what it returned."""
    CATEGORY = CATEGORY

    def run(self, ctx, params, **inputs) -> dict[str, Any]:
        raise NotImplementedError

    def process(self, ctx, **inputs):
        out = self.run(ctx, self.params, **inputs)
        if not self.OUTPUTS:
            return {}
        if not isinstance(out, dict):
            raise TypeError(t("Block phải return một dict có các khóa: {0}").format(", ".join(self.OUTPUTS)))
        source = next((v for v in inputs.values() if isinstance(v, Frame)), None)
        if source is None:
            source = next((v.source for v in inputs.values() if getattr(v, "source", None) is not None), None)
        result = {}
        for port, ptype in self.OUTPUTS.items():
            if port not in out:
                raise KeyError(t("Block chưa return cổng ra '{0}'").format(port))
            result[port] = self._coerce(port, ptype, out[port], source)
        return result

    @staticmethod
    def _coerce(port: str, ptype: PortType, value, source: Frame | None):
        if ptype is PortType.IMAGE:
            if isinstance(value, np.ndarray):
                return source.with_image(value) if source is not None else Frame(value)
            if isinstance(value, Frame):
                return value
        elif ptype is PortType.DETECTIONS:
            if isinstance(value, Detections):
                return value
            if isinstance(value, (list, tuple)) and all(isinstance(d, Detection) for d in value):
                size = (source.image.shape[1], source.image.shape[0]) if source is not None else (0, 0)
                return Detections(list(value), size, "user", source)
        elif ptype is PortType.MEASUREMENT:
            if isinstance(value, Measurement):
                return value
            if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
                return Measurement(port, float(value), "", source)
        elif ptype is PortType.RESULT:
            if isinstance(value, InspectionResult):
                return value
            if isinstance(value, (bool, np.bool_)):
                return InspectionResult("OK" if value else "NG", [] if value else [f"{port.upper()}_FAILED"])
            if value in ("OK", "NG", "ERROR"):
                return InspectionResult(value)
        raise TypeError(t("Cổng ra '{0}' cần kiểu {1}, nhưng block trả về {2}").format(
            port, ptype.name, type(value).__name__))


# ---- spec ------------------------------------------------------------------------------------
def new_spec() -> dict:
    spec = {"name": "", "title": "", "desc": "", "inputs": [["image", "IMAGE"]], "outputs": [["image", "IMAGE"]],
            "params": [], "code": ""}
    spec["code"] = default_code(spec)
    return spec


def slugify(title: str) -> str:
    """'Kiểm tra Ốc #2' -> 'kiem_tra_oc_2': a valid block code made from the display name."""
    plain = unicodedata.normalize("NFD", title.replace("\u0111", "d").replace("\u0110", "D"))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = ("block_" + slug).rstrip("_")
    return slug[:31].rstrip("_")


def type_id(spec: dict) -> str:
    return f"user.{spec['name']}"


def check_spec(spec: dict) -> None:
    """Raise BlockError for the first problem in the spec (names, types, duplicates)."""
    if not _NAME.match(spec.get("name", "")):
        raise BlockError(t("Mã block gồm chữ thường không dấu, số và '_', bắt đầu bằng chữ (tối đa 31 ký tự)."))
    if not spec.get("title", "").strip():
        raise BlockError(t("Hãy nhập tên hiển thị của block."))
    seen: set[str] = set()
    for group, rows in (("inputs", spec["inputs"]), ("outputs", spec["outputs"]), ("params", spec["params"])):
        names = [row[0] for row in rows]
        for name in names:
            if not _NAME.match(name) or keyword.iskeyword(name) or name in _RESERVED:
                raise BlockError(t("Tên '{0}' không hợp lệ: dùng chữ thường không dấu, số và '_', bắt đầu bằng chữ, "
                                   "không trùng từ khóa Python hay self / ctx / params.").format(name))
        if len(names) != len(set(names)):
            raise BlockError(t("Có tên bị trùng trong danh sách {0}.").format(group))
        if group != "outputs":
            if seen & set(names):
                raise BlockError(t("Tên cổng vào và tên tham số không được trùng nhau: {0}").format(
                    ", ".join(sorted(seen & set(names)))))
            seen |= set(names)
    for _name, ptype in spec["inputs"] + spec["outputs"]:
        if ptype not in PORT_TYPES:
            raise BlockError(t("Kiểu cổng '{0}' không hợp lệ.").format(ptype))
    if not spec["inputs"] and not spec["outputs"]:
        raise BlockError(t("Block cần ít nhất một cổng vào hoặc một cổng ra."))
    for name, kind, default, _label in spec["params"]:
        if kind not in PARAM_KINDS:
            raise BlockError(t("Kiểu tham số '{0}' không hợp lệ.").format(kind))
        try:
            _cast_default(kind, default)
        except ValueError:
            raise BlockError(t("Giá trị mặc định '{0}' của tham số '{1}' không đúng kiểu {2}.").format(default, name, kind))
    if not spec.get("code", "").strip():
        raise BlockError(t("Block chưa có mã Python."))


def _cast_default(kind: str, value):
    if kind == "int":
        return int(float(value))
    if kind == "float":
        return float(value)
    if kind == "bool":
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return str(value)


_EXAMPLE_IN = {"IMAGE": "{0}.image là ảnh numpy (BGR hoặc xám); {0}.meta là thông tin kèm theo",
               "DETECTIONS": "{0}.items là danh sách Detection(cls_name, score, box=(x1, y1, x2, y2))",
               "MEASUREMENT": "{0}.value là số đo, {0}.unit là đơn vị",
               "RESULT": "{0}.status là \"OK\" / \"NG\" / \"ERROR\", {0}.reasons là danh sách lý do"}
_EXAMPLE_OUT = {"IMAGE": "ảnh numpy", "DETECTIONS": "danh sách Detection(...)", "MEASUREMENT": "một số",
                "RESULT": "True / False, hoặc InspectionResult(\"NG\", [\"LY_DO\"])"}
_DEFAULT_OUT = {"IMAGE": "None", "DETECTIONS": "[]", "MEASUREMENT": "0.0", "RESULT": "True"}


def default_code(spec: dict) -> str:
    """A commented starting point that matches the block's ports and already runs."""
    lines = [t("# Có sẵn: cv2, np (numpy), math, Frame, Detection, Detections, Measurement, InspectionResult."),
             t("# ctx.shared[\"serial\"] là số serial của job; params[\"ten\"] là giá trị tham số.")]
    first_image = next((n for n, ty in spec["inputs"] if ty == "IMAGE"), None)
    for name, ptype in spec["inputs"]:
        lines.append(t("# Cổng vào ") + name + ": " + t(_EXAMPLE_IN[ptype]).format(name))
    for name, kind, _default, _label in spec["params"]:
        lines.append(t("# Tham số {0} ({1}): params[\"{2}\"]").format(name, kind, name))
    lines.append("")
    returns = []
    for name, ptype in spec["outputs"]:
        value = _DEFAULT_OUT[ptype]
        if ptype == "IMAGE" and first_image:
            value = f"{first_image}.image"
        elif ptype == "IMAGE":
            value = "np.zeros((100, 100, 3), np.uint8)"
        returns.append(f"\"{name}\": {value},   # {t(_EXAMPLE_OUT[ptype])}")
    if returns:
        lines += ["return {"] + ["    " + r for r in returns] + ["}"]
    else:
        lines.append("return {}")
    return "\n".join(lines) + "\n"


# ---- source generation -----------------------------------------------------------------------
_HEADER = '''"""User block made in VisionStudio (Studio > Block Python). Edit it there; hand edits are kept
as long as the VS_BLOCK_SPEC line stays in step with the code below."""
{mark}{spec}
import math

import cv2
import numpy as np

from visionstudio.core.node_base import Param, register
from visionstudio.core.schemas import Detection, Detections, Frame, InspectionResult, Measurement, PortType
from visionstudio.core.userblock import UserNode


@register
class {cls}(UserNode):
    TYPE = {type_id!r}
    TITLE = {title!r}
    DESC = {desc!r}
    INPUTS = {{{inputs}}}
    OUTPUTS = {{{outputs}}}
    PARAMS = [{params}]

    def run(self, ctx, params{args}):
'''


def generate_source(spec: dict) -> tuple[str, int]:
    """Return (python source, line number where the user's code starts)."""
    check_spec(spec)
    ports = lambda rows: ", ".join(f"{name!r}: PortType.{ptype}" for name, ptype in rows)
    params = ", ".join(f"Param({name!r}, {kind!r}, {_cast_default(kind, default)!r}, {(label or name)!r})"
                       for name, kind, default, label in spec["params"])
    head = _HEADER.format(mark=SPEC_MARK, spec=json.dumps(spec, ensure_ascii=False),
                          cls="Block_" + spec["name"], type_id=type_id(spec), title=spec["title"].strip(),
                          desc=spec.get("desc", "").strip() or spec["title"].strip(),
                          inputs=ports(spec["inputs"]), outputs=ports(spec["outputs"]), params=params,
                          args="".join(f", {name}" for name, _ in spec["inputs"]))
    code = spec["code"].replace("\t", "    ").rstrip() + "\n"
    return head + textwrap.indent(code, " " * 8, lambda line: True), head.count("\n") + 1


def compile_block(spec: dict):
    """Syntax-check the block. Raises BlockError with the line number inside the user's code."""
    source, first_line = generate_source(spec)
    try:
        return compile(source, f"<block {spec['name']}>", "exec"), source, first_line
    except SyntaxError as exc:
        line = (exc.lineno or first_line) - first_line + 1
        raise BlockError(t("Lỗi cú pháp ở dòng {0}: {1}").format(max(1, line), exc.msg)) from exc


# ---- files -----------------------------------------------------------------------------------
def plugin_dir() -> Path:
    if node_base.PLUGIN_DIR is None:
        raise BlockError(t("Chưa có thư mục plugins."))
    node_base.PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
    return node_base.PLUGIN_DIR


def block_path(name: str) -> Path:
    return plugin_dir() / f"{FILE_PREFIX}{name}.py"


def read_spec(path: Path) -> dict | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[:8]:
            if line.startswith(SPEC_MARK):
                return json.loads(line[len(SPEC_MARK):])
    except (OSError, ValueError):
        pass
    return None


def list_blocks() -> list[dict]:
    """Specs of all user blocks in the plugin folder, by title."""
    if node_base.PLUGIN_DIR is None or not node_base.PLUGIN_DIR.is_dir():
        return []
    specs = [read_spec(p) for p in sorted(node_base.PLUGIN_DIR.glob(f"{FILE_PREFIX}*.py"))]
    return sorted((s for s in specs if s), key=lambda s: s["title"].lower())


def save_block(spec: dict, overwrite: bool = True) -> Path:
    """Check, write and (re)load the block. After this it is in REGISTRY under 'user.<name>'."""
    _code, source, _line = compile_block(spec)
    path = block_path(spec["name"])
    if path.exists() and not overwrite:
        raise BlockError(t("Đã có block mang mã '{0}'.").format(spec["name"]))
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(source, encoding="utf-8")
    try:
        node_base.load_plugin_file(path)
    except Exception as exc:                               # e.g. an import the user added does not exist
        if previous is None:
            path.unlink()
        else:
            path.write_text(previous, encoding="utf-8")
        raise BlockError(f"{type(exc).__name__}: {exc}") from exc
    return path


def delete_block(name: str) -> None:
    path = block_path(name)
    if path.exists():
        path.unlink()
    node_base.REGISTRY.pop(f"user.{name}", None)


# ---- trial run -------------------------------------------------------------------------------
def sample_inputs(spec: dict, image: np.ndarray | None = None) -> dict[str, Any]:
    """Made-up inputs of the right types, so a block can be tried without running the line."""
    if image is None:
        image = np.full((240, 320, 3), 60, np.uint8)
        image[60:180, 80:240] = (40, 160, 220)
    frame = Frame(image, 0, 1, "sample", {"serial": "SN-SAMPLE"})
    h, w = image.shape[:2]
    samples = {"IMAGE": frame,
               "DETECTIONS": Detections([Detection("part", 0.92, (w * 0.25, h * 0.25, w * 0.75, h * 0.75)),
                                         Detection("screw", 0.55, (10, 10, 40, 40))], (w, h), "sample", frame),
               "MEASUREMENT": Measurement("sample", 12.5, "mm", frame),
               "RESULT": InspectionResult("OK", [], {"sample": 1.0})}
    return {name: samples[ptype] for name, ptype in spec["inputs"]}


def describe(value) -> str:
    if isinstance(value, Frame):
        return f"IMAGE {value.image.shape[1]}x{value.image.shape[0]}, {value.image.dtype}, " \
               f"{1 if value.image.ndim == 2 else value.image.shape[2]} ch"
    if isinstance(value, Detections):
        shown = ", ".join(f"{d.cls_name} {d.score:.2f}" for d in value.items[:6])
        return f"DETECTIONS x{len(value.items)}" + (f": {shown}" if shown else "")
    if isinstance(value, Measurement):
        return f"MEASUREMENT {value.name} = {value.value:g} {value.unit}".rstrip()
    if isinstance(value, InspectionResult):
        return f"RESULT {value.status} {value.reasons}"
    return repr(value)


def trial_run(spec: dict, ctx=None, image: np.ndarray | None = None) -> tuple[bool, str, dict]:
    """Compile the block and run it once on sample inputs, without registering or saving anything.
    Returns (ok, report text, outputs)."""
    try:
        code, source, first_line = compile_block(spec)
    except BlockError as exc:
        return False, str(exc), {}
    captured: list[type] = []
    namespace: dict[str, Any] = {"__name__": f"vs_trial_{spec['name']}"}
    saved = node_base.REGISTRY.get(type_id(spec))
    try:
        exec(code, namespace)                              # @register runs here ...
        captured.append(namespace["Block_" + spec["name"]])
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", {}
    finally:                                               # ... so put the registry back as it was
        if saved is None:
            node_base.REGISTRY.pop(type_id(spec), None)
        else:
            node_base.REGISTRY[type_id(spec)] = saved
    if ctx is None:
        from .executor import JobContext
        ctx = JobContext(None, None, job_no=1)
        ctx.shared["serial"] = "SN-SAMPLE"
    inputs = sample_inputs(spec, image)
    node = captured[0]("trial")
    try:
        node.setup(ctx)
        outputs = node.process(ctx, **inputs)
        node.teardown()
    except Exception as exc:
        frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename.startswith("<block")]
        where = t(" (dòng {0})").format(frames[-1].lineno - first_line + 1) if frames else ""
        return False, f"{type(exc).__name__}{where}: {exc}", {}
    lines = [t("Chạy thử thành công.")]
    lines += [f"  {name}  <-  {describe(value)}" for name, value in inputs.items()]
    lines += [f"  {name}  ->  {describe(value)}" for name, value in outputs.items()]
    return True, "\n".join(lines), outputs