"""Shared fixtures. Run everything with:  python -m pytest tests -q

The UI tests run without showing windows (Qt "offscreen" platform), so they also work on a line PC
or a CI machine with no screen. Nothing here needs a camera, a PLC or a network connection.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from visionstudio.core import i18n                      # noqa: E402
from visionstudio.core.engine import Engine             # noqa: E402
from visionstudio.core.graph import Recipe              # noqa: E402
from visionstudio.core.node_base import load_plugins    # noqa: E402
from visionstudio.core.storage import Store             # noqa: E402

load_plugins(ROOT / "plugins")
SIM_RECIPE = ROOT / "recipes" / "assy_conn_01.json"
FOLDER_RECIPE = ROOT / "recipes" / "real_folder_yolo.json"


def pytest_addoption(parser):
    parser.addoption("--stress-scale", type=float, default=1.0,
                     help="multiply the size of every stress test (1 = about a minute in total)")


@pytest.fixture
def scale(request) -> float:
    return request.config.getoption("--stress-scale")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    yield s
    s.db.close()


@pytest.fixture
def engine(store):
    """Engine running the simulated two-camera recipe (no hardware, about 15 ms per job)."""
    e = Engine(store)
    e.load_recipe(Recipe.load(SIM_RECIPE))
    yield e
    e.shutdown()


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def pump(qapp):
    """pump(seconds): let the Qt event loop run so queued signals and timers are delivered."""
    def run(seconds: float = 0.1) -> None:
        end = time.time() + seconds
        from PyQt6.QtCore import QEvent
        while time.time() < end:
            qapp.processEvents()
            # processEvents() alone never runs deleteLater(); app.exec() does. Do it here too, so
            # closed windows are really destroyed between tests, as in the running application.
            qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            time.sleep(0.005)
    return run


@pytest.fixture
def window(qapp, engine, store, tmp_path, pump, monkeypatch):
    """Main window on a private copy of the simulated recipe, logged in as the Developer account."""
    import shutil
    from PyQt6.QtWidgets import QMessageBox
    from visionstudio.ui import theme
    from visionstudio.ui.main_window import MainWindow, keep_alive
    recipe_path = tmp_path / "recipes" / SIM_RECIPE.name
    recipe_path.parent.mkdir()
    shutil.copy(SIM_RECIPE, recipe_path)
    engine.load_recipe(Recipe.load(recipe_path))
    i18n.set_language("vi")
    theme.apply_theme(qapp, "dark")
    # a modal box would block the test run: answer "Yes" / "OK" automatically
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    win = MainWindow(engine, store, str(recipe_path))
    keep_alive(win)
    win.resize(1500, 880)
    win.show()
    assert win.ctx.login("dev", "dev1234")
    pump(0.2)
    yield win
    current = qapp.property("main_window") or win          # the window may have been rebuilt
    engine.stop()
    current.ctx.set_dirty(False)
    current.close()
    current.deleteLater()
    qapp.setProperty("main_window", None)
    i18n.set_language("vi")
    theme.apply_theme(qapp, "dark")
    pump(0.05)