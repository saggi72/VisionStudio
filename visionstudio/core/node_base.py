"""Node base class, parameter declaration, registry and plugin loading.

To add a node: subclass Node, decorate with @register, and place the module in
visionstudio/nodes/ (built-in), in the project's plugins/ folder, or expose it through the
"visionstudio.plugins" entry-point group of an installed package.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import types
import pkgutil
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from .schemas import PortType

log = logging.getLogger("visionstudio.plugins")


@dataclass
class Param:
    """One editable node parameter. The UI builds its editor from `kind`.

    kind: int | float | bool | str | choice | file | device:camera | device:plc | device:comm
    """
    name: str
    kind: str
    default: Any
    label: str = ""
    min: float | None = None
    max: float | None = None
    choices: list[str] | None = None


class Node:
    TYPE = ""                               # unique id, e.g. "classic.threshold"
    TITLE = ""
    CATEGORY = ""
    DESC = ""                               # one-line description shown in the inspector (Vietnamese source text)
    INPUTS: dict[str, PortType] = {}
    OUTPUTS: dict[str, PortType] = {}
    PARAMS: list[Param] = []

    def __init__(self, node_id: str, params: dict[str, Any] | None = None):
        self.id = node_id
        self.params = {p.name: p.default for p in self.PARAMS}
        self.params.update(params or {})

    def setup(self, ctx) -> None:           # load models, open resources
        pass

    def process(self, ctx, **inputs) -> dict[str, Any]:
        raise NotImplementedError

    def teardown(self) -> None:
        pass


REGISTRY: dict[str, type[Node]] = {}
PLUGIN_ERRORS: list[str] = []
PLUGIN_DIR: Path | None = None              # folder given to load_plugins(); user blocks are saved there


def register(cls: type[Node]) -> type[Node]:
    if not cls.TYPE:
        raise ValueError(f"{cls.__name__} has no TYPE")
    REGISTRY[cls.TYPE] = cls
    return cls


CATEGORY_ORDER = ["Nguồn ảnh & Đồng bộ (Source)", "Tiền xử lý (Preprocess)", "Thị giác cổ điển (Classic Vision)",
                  "Trí tuệ nhân tạo (AI Vision)", "Đo lường (Measure)", "Logic", "Đầu ra & Truyền thông (Output)",
                  "Block tự tạo (User)"]


def catalog() -> dict[str, list[type[Node]]]:
    """Node classes by category, in pipeline order (source first, output last); plugin categories follow."""
    out: dict[str, list[type[Node]]] = {}
    for cls in REGISTRY.values():
        out.setdefault(cls.CATEGORY, []).append(cls)
    rank = {name: i for i, name in enumerate(CATEGORY_ORDER)}
    return dict(sorted(out.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[0])))


def load_plugins(plugin_dir: str | Path | None = None) -> None:
    """Import built-in nodes, entry-point plugins and *.py files in plugin_dir.

    A plugin that fails to import (missing SDK, bug) is recorded and skipped; the app keeps running.
    """
    global PLUGIN_DIR
    if plugin_dir:
        PLUGIN_DIR = Path(plugin_dir)
    from .. import nodes as builtin
    for mod in pkgutil.iter_modules(builtin.__path__):
        _safe_import(lambda m=mod: importlib.import_module(f"{builtin.__name__}.{m.name}"), mod.name)

    try:
        for ep in metadata.entry_points(group="visionstudio.plugins"):
            _safe_import(ep.load, ep.name)
    except Exception as exc:  # pragma: no cover - depends on the environment
        PLUGIN_ERRORS.append(f"entry points: {exc}")

    if plugin_dir and Path(plugin_dir).is_dir():
        for path in sorted(Path(plugin_dir).glob("*.py")):
            _safe_import(lambda p=path: load_plugin_file(p), path.name)


def load_plugin_file(path: str | Path) -> None:
    """Import (or re-import after an edit) one plugin file. Its @register calls update REGISTRY.

    The source is compiled directly instead of going through the import cache: a block saved twice
    within the same second must not come back as the previous version from a stale .pyc file.
    """
    path = Path(path)
    module = types.ModuleType(f"vs_plugin_{path.stem}")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module                  # dataclasses and pickling look the module up
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)


def _safe_import(loader, name: str) -> None:
    try:
        loader()
    except Exception as exc:
        msg = f"{name}: {type(exc).__name__}: {exc}"
        PLUGIN_ERRORS.append(msg)
        log.warning("plugin skipped - %s", msg)