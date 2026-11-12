"""Graph model, recipe files, executor verdicts and the engine's job loop."""
from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

from visionstudio.core.engine import Engine
from visionstudio.core.executor import Executor
from visionstudio.core.graph import Graph, GraphError, Recipe
from visionstudio.core.node_base import PLUGIN_ERRORS, REGISTRY, catalog, load_plugins
from visionstudio.hardware.manager import DeviceManager

from conftest import ROOT, SIM_RECIPE


# ---- graph -----------------------------------------------------------------------------------
def test_graph_ids_defaults_and_removal():
    g = Graph()
    a, b = g.add_node("classic.gaussian_blur"), g.add_node("classic.gaussian_blur")
    assert (a.id, b.id) == ("gaussian_blur1", "gaussian_blur2") and a.params == {"ksize": 5}
    assert a.title == "Gaussian Blur"
    g.add_edge(a.id, "image", b.id, "image")
    g.remove_node(a.id)
    assert list(g.nodes) == [b.id] and g.edges == []
    with pytest.raises(GraphError):
        g.add_node("no.such.type")


def test_graph_connection_rules():
    g = Graph()
    cam, blur, blur2 = g.add_node("source.camera"), g.add_node("classic.gaussian_blur"), g.add_node("classic.gaussian_blur")
    count = g.add_node("logic.count_by_class")
    assert g.can_connect(cam.id, "frame", blur.id, "image") is None
    assert g.can_connect(blur.id, "image", blur.id, "image")                      # itself
    assert g.can_connect(cam.id, "nope", blur.id, "image")                        # unknown port
    assert g.can_connect(cam.id, "frame", count.id, "detections")                 # IMAGE -> DETECTIONS
    g.add_edge(blur.id, "image", blur2.id, "image")
    assert g.can_connect(blur2.id, "image", blur.id, "image")                     # would close a loop
    g.add_edge(cam.id, "frame", blur2.id, "image")                                # an input keeps one edge
    assert [(e.src, e.dst) for e in g.edges] == [(cam.id, blur2.id)]


def test_topological_order_and_validation():
    recipe = Recipe.load(SIM_RECIPE)
    order = recipe.graph.topo_order()
    assert order.index("cam1") < order.index("sync1") < order.index("det1") < order.index("cnt1") < order.index("plc1")
    assert recipe.graph.validate() == []
    recipe.graph.edges = [e for e in recipe.graph.edges if e.dst != "det1"]
    assert recipe.graph.validate() == [("det1", "Cổng vào 'image' chưa được nối")]


def test_missing_plugin_is_reported_not_fatal():
    data = {"nodes": [{"id": "x", "type": "vendor.unknown", "params": {}}], "edges": []}
    problems = Graph.from_dict(data).validate()
    assert problems and problems[0][0] == "x"


def test_recipe_file_roundtrip_version_and_unicode(tmp_path):
    recipe = Recipe.load(SIM_RECIPE)
    recipe.name = "Kiểm tra ốc - ca đêm"
    path = tmp_path / "r.json"
    recipe.save(path)
    again = Recipe.load(path)
    assert again.version == recipe.version == 8 and again.name == "Kiểm tra ốc - ca đêm"
    assert again.graph.to_dict() == recipe.graph.to_dict() and again.devices == recipe.devices
    assert again.label == "ASSY-CONN-01 (v8)"
    recipe.save(path, bump_version=False)
    assert Recipe.load(path).version == 8


def test_recipe_from_newer_version_is_refused(tmp_path):
    data = json.loads(SIM_RECIPE.read_text(encoding="utf-8"))
    data["schema_version"] = 999
    path = tmp_path / "future.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(GraphError):
        Recipe.load(path)


def test_shipped_recipes_are_valid():
    for path in (ROOT / "recipes").glob("*.json"):
        recipe = Recipe.load(path)
        assert recipe.graph.validate() == [], path.name
        for node in recipe.graph.nodes.values():
            if "device" in node.params:
                assert node.params["device"] in recipe.devices, (path.name, node.id)


# ---- plugins ---------------------------------------------------------------------------------
def test_plugin_loading_good_and_broken(tmp_path):
    (tmp_path / "good_plugin.py").write_text(
        "from visionstudio.core.node_base import Node, register\n"
        "from visionstudio.core.schemas import PortType\n"
        "@register\nclass T(Node):\n    TYPE = 'test.tmp_plugin'\n    TITLE = 'Tmp'\n    DESC = 'x'\n"
        "    CATEGORY = 'Test'\n    INPUTS = {'image': PortType.IMAGE}\n    OUTPUTS = {'image': PortType.IMAGE}\n"
        "    def process(self, ctx, image):\n        return {'image': image}\n", encoding="utf-8")
    (tmp_path / "broken_plugin.py").write_text("import a_module_that_does_not_exist\n", encoding="utf-8")
    try:
        load_plugins(tmp_path)
        assert "test.tmp_plugin" in REGISTRY and "Test" in catalog()
        assert any("broken_plugin" in e for e in PLUGIN_ERRORS)                  # skipped, app keeps going
    finally:
        REGISTRY.pop("test.tmp_plugin", None)
        PLUGIN_ERRORS[:] = [e for e in PLUGIN_ERRORS if "broken_plugin" not in e]


# ---- executor verdicts ---------------------------------------------------------------------------
def sim_devices():
    devices = DeviceManager()
    devices.configure({"cam1": {"kind": "camera", "provider": "sim"}})
    return devices


def test_no_result_node_is_error(store):
    g = Graph()
    cam, blur = g.add_node("source.camera", params={"device": "cam1"}), g.add_node("classic.gaussian_blur")
    g.add_edge(cam.id, "frame", blur.id, "image")
    job = Executor(g, sim_devices(), store).run_job(1)
    assert (job.result.status, job.result.reasons) == ("ERROR", ["NO_RESULT_NODE"])


def test_failing_node_is_error_with_node_id_and_timings(store):
    g = Graph()
    cam = g.add_node("source.camera", params={"device": "cam1"})
    crop = g.add_node("classic.crop", params={"x": 9000, "y": 9000})              # outside the image -> raises
    bright, tol = g.add_node("measure.brightness"), g.add_node("logic.tolerance")
    g.add_edge(cam.id, "frame", crop.id, "image")
    g.add_edge(crop.id, "image", bright.id, "image")
    g.add_edge(bright.id, "value", tol.id, "value")
    job = Executor(g, sim_devices(), store).run_job(1)
    assert job.result.status == "ERROR" and job.result.reasons[0] == f"NODE_FAILED:{crop.id}"
    assert "ROI" in job.result.reasons[1]
    assert set(job.timings) == {cam.id, crop.id} and bright.id not in job.outputs   # stopped at the failure


def test_executor_refuses_invalid_graph(store):
    g = Graph()
    g.add_node("classic.gaussian_blur")
    with pytest.raises(ValueError):
        Executor(g, sim_devices(), store)


def test_job_carries_serial_preview_and_timings(engine):
    job = engine.run_once()
    assert job.job_id == "JOB-00001" and job.serial.startswith("SN-")
    assert job.preview is not None and job.preview.shape[1] == 1280              # two 640 px views side by side
    assert set(job.timings) == {"cam1", "cam2", "sync1", "det1", "cnt1", "plc1"} and job.cycle_ms > 0
    assert job.n_detections in (4, 5, 6)


# ---- engine ----------------------------------------------------------------------------------
def test_edit_is_applied_on_next_job(engine):
    assert engine.run_once().result.status in ("OK", "NG")
    graph = engine.recipe.graph
    graph.nodes["cnt1"].params["expect"] = "connector=99"
    engine.update_graph(graph)
    job = engine.run_once()
    assert job.result.status == "NG" and "MISSING_CONNECTOR" in job.result.reasons
    graph.remove_node("cnt1")                                                     # plc1 input now unwired
    engine.update_graph(graph)
    job = engine.run_once()
    assert job.result.status == "ERROR" and job.result.reasons[0] == "INVALID_GRAPH"
    engine.update_graph(Recipe.load(SIM_RECIPE).graph)                            # repaired
    assert engine.run_once().result.status in ("OK", "NG")


def test_engine_keeps_inspecting_after_errors(engine):
    engine.devices.cameras["cam2"].status = "Connected"
    engine.devices.cameras.pop("cam2")                                            # camera vanishes
    engine.update_graph(engine.recipe.graph)
    bad = engine.run_once()
    assert bad.result.status == "ERROR" and bad.result.reasons[0] == "NODE_FAILED:cam2"
    engine.devices.configure(engine.recipe.devices)                               # reconnect
    engine.update_graph(engine.recipe.graph)
    assert engine.run_once().result.status in ("OK", "NG")
    assert engine.stats["error"] == 1 and engine.stats["total"] == 2
    assert engine.store.counts() == engine.stats


def test_camera_that_never_opened_gives_a_clear_error(store, tmp_path):
    engine = Engine(store)
    recipe = Recipe.load(SIM_RECIPE)
    recipe.devices["cam1"] = {"kind": "camera", "provider": "opencv", "source": str(tmp_path / "no_camera.avi")}
    engine.load_recipe(recipe)
    job = engine.run_once()
    engine.shutdown()
    assert job.result.status == "ERROR" and job.result.reasons[0] == "NODE_FAILED:cam1"
    assert "cam1" in job.result.reasons[1] and "AttributeError" not in job.result.reasons[1]


def test_threaded_loop_start_stop_and_listeners(engine):
    engine.store.set("interval_ms", 20)
    jobs, states = [], []
    engine.listeners.append(jobs.append)
    engine.state_listeners.append(states.append)
    engine.start()
    engine.start()                                                                # second start is ignored
    time.sleep(0.6)
    assert engine.running
    engine.stop()
    assert not engine.running and states == [True, False]
    n = len(jobs)
    assert n >= 5 and [j.job_no for j in jobs] == list(range(1, n + 1))
    time.sleep(0.15)
    assert len(jobs) == n                                                         # really stopped
    engine.stop()                                                                 # stopping twice is harmless


def test_storage_failure_does_not_stop_the_line(engine, monkeypatch):
    monkeypatch.setattr(engine.store, "save_inspection", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    job = engine.run_once()
    assert job.result.status in ("OK", "NG") and job.result.values["storage_error"] == 1.0


def test_uncertain_detections_go_to_retrain_buffer(engine):
    engine.store.set("unc_lo", 0.0)
    engine.store.set("unc_hi", 1.0)                                               # every detection is "uncertain"
    engine.run_once()
    assert len(engine.store.uncertain_files()) == 1 and engine.store.buffer_classes()
    engine.store.set("unc_lo", 0.0)
    engine.store.set("unc_hi", 0.01)
    engine.run_once()
    assert len(engine.store.uncertain_files()) == 1


def test_load_recipe_swaps_devices_and_graph(engine):
    pytest.importorskip("onnxruntime")
    engine.run_once()
    from conftest import FOLDER_RECIPE
    engine.load_recipe(Recipe.load(FOLDER_RECIPE))
    assert list(engine.devices.cameras) == ["cam1"] and engine.devices.plcs == {}
    job = engine.run_once()
    assert job.serial == "bus" and job.result.status == "OK" and job.n_detections == 3


def test_headless_command_line(tmp_path):
    out = subprocess.run([sys.executable, str(ROOT / "main.py"), "--headless", "--jobs", "5", "--data", str(tmp_path),
                          "--recipe", str(SIM_RECIPE)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr
    lines = out.stdout.strip().splitlines()
    assert len(lines) == 6 and lines[0].startswith("JOB-00001") and "5" in lines[-1]
    assert (tmp_path / "visionstudio.db").exists()