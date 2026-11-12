"""User blocks: Python nodes written inside the Studio (spec checks, code generation, trial run,
saving as a plugin file, use in a pipeline, the editor dialog, and the permission that guards it)."""
from __future__ import annotations

import numpy as np
import pytest

from visionstudio.core import node_base
from visionstudio.core import userblock as ub
from visionstudio.core.auth import AuthManager
from visionstudio.core.engine import Engine
from visionstudio.core.graph import Recipe
from visionstudio.core.schemas import Detection, Detections, Frame, InspectionResult, Measurement
from visionstudio.core.storage import Store

from conftest import SIM_RECIPE

AREA = {"name": "area_check", "title": "Kiểm tra diện tích", "desc": "NG khi không có vùng đủ lớn",
        "inputs": [["dets", "DETECTIONS"]], "outputs": [["result", "RESULT"], ["area", "MEASUREMENT"]],
        "params": [["min_area", "float", "1000", "Diện tích tối thiểu"]],
        "code": "areas = [(d.box[2] - d.box[0]) * (d.box[3] - d.box[1]) for d in dets.items]\n"
                "biggest = max(areas, default=0)\n"
                "return {\"result\": biggest >= params[\"min_area\"], \"area\": biggest}\n"}


@pytest.fixture
def plugin_dir(tmp_path, monkeypatch):
    """A private plugins folder; blocks registered during the test are removed afterwards."""
    folder = tmp_path / "plugins"
    folder.mkdir()
    monkeypatch.setattr(node_base, "PLUGIN_DIR", folder)
    before = set(node_base.REGISTRY)
    yield folder
    for type_id in set(node_base.REGISTRY) - before:
        node_base.REGISTRY.pop(type_id)


def spec(**changes) -> dict:
    return {**AREA, **changes}


# ---- spec and code generation ------------------------------------------------------------------
def test_slugify_makes_a_valid_code_from_a_vietnamese_title():
    assert ub.slugify("Kiểm tra Ốc #2") == "kiem_tra_oc_2"
    assert ub.slugify("Đo độ dày") == "do_do_day"
    assert ub.slugify("123") == "block_123" and ub.slugify("") == "block"
    assert len(ub.slugify("a" * 80)) == 31


@pytest.mark.parametrize("changes", [
    {"name": "Bad Name"}, {"name": "1abc"}, {"name": ""}, {"title": "  "},
    {"inputs": [["ctx", "IMAGE"]]}, {"inputs": [["class", "IMAGE"]]}, {"inputs": [["Image", "IMAGE"]]},
    {"inputs": [["a", "IMAGE"], ["a", "IMAGE"]]}, {"inputs": [["min_area", "IMAGE"]]},
    {"inputs": [["a", "TENSOR"]]}, {"inputs": [], "outputs": []},
    {"params": [["n", "int", "abc", ""]]}, {"params": [["n", "list", "1", ""]]}, {"code": "   \n"},
])
def test_bad_specs_are_refused_with_a_message(changes):
    with pytest.raises(ub.BlockError) as err:
        ub.check_spec(spec(**changes))
    assert str(err.value)


def test_generated_source_is_a_normal_plugin_file():
    source, first_line = ub.generate_source(AREA)
    compile(source, "<test>", "exec")
    lines = source.splitlines()
    assert lines[first_line - 1].strip().startswith("areas = [")           # where the user's code starts
    assert "TYPE = 'user.area_check'" in source and "def run(self, ctx, params, dets):" in source
    assert "Param('min_area', 'float', 1000.0, 'Diện tích tối thiểu')" in source
    assert lines[2].startswith(ub.SPEC_MARK)


def test_default_code_matches_ports_and_runs():
    for inputs, outputs in ([[["image", "IMAGE"]], [["image", "IMAGE"]]],
                            [[["a", "DETECTIONS"], ["b", "MEASUREMENT"]], [["r", "RESULT"], ["m", "MEASUREMENT"]]],
                            [[], [["image", "IMAGE"], ["dets", "DETECTIONS"]]],
                            [[["r", "RESULT"]], []]):
        s = spec(name="tmpl", inputs=inputs, outputs=outputs, params=[["k", "int", "3", ""]])
        s["code"] = ub.default_code(s)
        ok, text, out = ub.trial_run(s)
        assert ok, text
        assert set(out) == {name for name, _ in outputs}


def test_syntax_and_runtime_errors_point_at_the_users_line():
    ok, text, _ = ub.trial_run(spec(code="x = 1\ny = (2,\nreturn {}\n"))
    assert not ok and "2" in text                                           # line 2 of the user's code
    ok, text, _ = ub.trial_run(spec(code="a = 1\nb = 2\nc = a / 0\nreturn {}\n"))
    assert not ok and "ZeroDivisionError" in text and "3" in text


def test_return_values_are_checked():
    cases = {"return 5": "dict", "return {\"area\": 1.0}": "result", "return {\"result\": 5, \"area\": 1.0}": "RESULT",
             "return {\"result\": True, \"area\": \"big\"}": "MEASUREMENT"}
    for code, expected in cases.items():
        ok, text, _ = ub.trial_run(spec(code=code + "\n"))
        assert not ok and expected in text, text


def test_plain_python_values_become_port_types():
    s = spec(name="conv", inputs=[["image", "IMAGE"]],
             outputs=[["gray", "IMAGE"], ["found", "DETECTIONS"], ["mean", "MEASUREMENT"], ["ok", "RESULT"], ["bad", "RESULT"]],
             params=[], code="g = cv2.cvtColor(image.image, cv2.COLOR_BGR2GRAY)\n"
                             "return {\"gray\": g, \"found\": [Detection(\"x\", 0.9, (1, 2, 30, 40))],\n"
                             "        \"mean\": np.float32(g.mean()), \"ok\": \"OK\", \"bad\": False}\n")
    ok, text, out = ub.trial_run(s)
    assert ok, text
    assert isinstance(out["gray"], Frame) and out["gray"].image.ndim == 2 and out["gray"].meta["serial"] == "SN-SAMPLE"
    assert isinstance(out["found"], Detections) and out["found"].image_size == (320, 240) and out["found"].source is not None
    assert isinstance(out["mean"], Measurement) and out["mean"].name == "mean" and out["mean"].value > 0
    assert out["ok"].status == "OK" and (out["bad"].status, out["bad"].reasons) == ("NG", ["BAD_FAILED"])


def test_trial_run_does_not_register_or_save(plugin_dir):
    before = dict(node_base.REGISTRY)
    assert ub.trial_run(AREA)[0]
    assert node_base.REGISTRY == before and list(plugin_dir.iterdir()) == []


# ---- files -----------------------------------------------------------------------------------
def test_save_load_edit_delete(plugin_dir):
    path = ub.save_block(AREA)
    assert path == plugin_dir / "user_area_check.py" and ub.read_spec(path) == AREA
    cls = node_base.REGISTRY["user.area_check"]
    assert (cls.TITLE, cls.CATEGORY) == ("Kiểm tra diện tích", ub.CATEGORY) and "user.area_check" in [
        c.TYPE for c in node_base.catalog()[ub.CATEGORY]]
    assert [s["name"] for s in ub.list_blocks()] == ["area_check"]
    with pytest.raises(ub.BlockError):
        ub.save_block(AREA, overwrite=False)                                # creating it a second time

    edited = spec(title="Diện tích v2", params=[["min_area", "float", "5", ""], ["scale", "float", "2.5", "Hệ số"]])
    ub.save_block(edited)                                                   # hot reload
    assert [p.name for p in node_base.REGISTRY["user.area_check"].PARAMS] == ["min_area", "scale"]
    assert node_base.REGISTRY["user.area_check"].TITLE == "Diện tích v2"

    ub.delete_block("area_check")
    assert not path.exists() and "user.area_check" not in node_base.REGISTRY and ub.list_blocks() == []
    ub.delete_block("area_check")                                           # deleting twice is harmless


def test_failed_save_keeps_the_previous_version(plugin_dir):
    ub.save_block(AREA)
    broken = spec(code="import module_that_does_not_exist\nreturn {}\n")
    assert ub.trial_run(broken)[0] is False
    with pytest.raises(ub.BlockError):
        ub.save_block(spec(code="return {\n"))                              # syntax error: nothing written
    assert ub.read_spec(plugin_dir / "user_area_check.py") == AREA
    assert node_base.REGISTRY["user.area_check"]("n").params == {"min_area": 1000.0}


def test_saved_block_is_loaded_like_any_plugin_at_startup(plugin_dir):
    ub.save_block(AREA)
    node_base.REGISTRY.pop("user.area_check")
    node_base.load_plugins(plugin_dir)                                      # what main.py does at start
    assert "user.area_check" in node_base.REGISTRY


def test_hand_written_plugin_without_a_spec_is_left_alone(plugin_dir):
    (plugin_dir / "user_handmade.py").write_text("x = 1\n", encoding="utf-8")
    (plugin_dir / "other_plugin.py").write_text("x = 1\n", encoding="utf-8")
    ub.save_block(AREA)
    assert [s["name"] for s in ub.list_blocks()] == ["area_check"]


# ---- in a pipeline ---------------------------------------------------------------------------
def test_block_runs_in_a_recipe_and_survives_save_and_reload(plugin_dir, store, tmp_path):
    ub.save_block(AREA)
    recipe = Recipe.load(SIM_RECIPE)
    node = recipe.graph.add_node("user.area_check", params={"min_area": 50.0})
    recipe.graph.add_edge("det1", "detections", node.id, "dets")
    engine = Engine(store)
    engine.load_recipe(recipe)
    job = engine.run_once()
    assert job.result.status in ("OK", "NG") and job.result.values["area"] > 50 if "area" in job.result.values else True
    assert job.outputs[node.id]["area"].value > 50 and job.outputs[node.id]["result"].status == "OK"

    recipe.graph.nodes[node.id].params["min_area"] = 1e9                    # impossible -> this branch says NG
    engine.update_graph(recipe.graph)
    job = engine.run_once()
    assert job.result.status == "NG" and "RESULT_FAILED" in job.result.reasons

    path = tmp_path / "with_block.json"
    recipe.save(path)
    again = Recipe.load(path)
    assert again.graph.nodes[node.id].type == "user.area_check" and again.graph.validate() == []

    ub.delete_block("area_check")                                           # block removed from the PC
    assert again.graph.validate()[0][0] == node.id                          # reported as a missing plugin
    engine.update_graph(again.graph)
    job = engine.run_once()
    assert (job.result.status, job.result.reasons[0]) == ("ERROR", "INVALID_GRAPH")
    engine.shutdown()


def test_exception_in_a_block_makes_the_job_error_not_ok(plugin_dir, store):
    ub.save_block(spec(name="crashy", outputs=[["result", "RESULT"]], params=[],
                       code="if ctx.job_no >= 2:\n    raise ValueError(\"bad value\")\nreturn {\"result\": True}\n"))
    recipe = Recipe.load(SIM_RECIPE)
    node = recipe.graph.add_node("user.crashy")
    recipe.graph.add_edge("det1", "detections", node.id, "dets")
    engine = Engine(store)
    engine.load_recipe(recipe)
    assert engine.run_once().result.status in ("OK", "NG")
    job = engine.run_once()
    assert job.result.status == "ERROR" and job.result.reasons[0] == f"NODE_FAILED:{node.id}"
    assert "bad value" in job.result.reasons[1]
    engine.shutdown()


def test_block_can_use_devices_and_shared_job_data(plugin_dir):
    """A block may talk to a channel itself, e.g. to send a custom binary frame."""
    from visionstudio.core.executor import JobContext
    from visionstudio.hardware.manager import DeviceManager
    ub.save_block({"name": "send_frame", "title": "Send frame", "desc": "", "inputs": [["result", "RESULT"]],
                   "outputs": [], "params": [["channel", "str", "com1", ""]],
                   "code": "flag = 1 if result.status == \"OK\" else 0\n"
                           "frame = bytes([0xAA, flag, ctx.job_no & 0xFF]) + ctx.shared[\"serial\"].encode()\n"
                           "ctx.devices.comm(params[\"channel\"]).send(frame)\nreturn {}\n"})
    devices = DeviceManager()
    devices.configure({"com1": {"kind": "comm", "provider": "sim"}})
    ctx = JobContext(devices, None, job_no=9)
    ctx.shared["serial"] = "SN-7"
    node_base.REGISTRY["user.send_frame"]("n").process(ctx, result=InspectionResult("NG"))
    assert devices.comm("com1").log == [b"\xaa\x00\x09SN-7"]


def test_edges_to_removed_ports_are_dropped(plugin_dir):
    ub.save_block(AREA)
    recipe = Recipe.load(SIM_RECIPE)
    node = recipe.graph.add_node("user.area_check")
    tol = recipe.graph.add_node("logic.tolerance")
    recipe.graph.add_edge("det1", "detections", node.id, "dets")
    recipe.graph.add_edge(node.id, "area", tol.id, "value")
    edges = len(recipe.graph.edges)
    assert recipe.graph.drop_stale_edges() == 0
    ub.save_block(spec(outputs=[["result", "RESULT"]],                      # the 'area' output is gone
                       code="return {\"result\": True}\n"))
    assert recipe.graph.drop_stale_edges() == 1 and len(recipe.graph.edges) == edges - 1
    assert (tol.id, "Cổng vào 'value' chưa được nối") in recipe.graph.validate()


# ---- permission ------------------------------------------------------------------------------
def test_block_permission_defaults_and_upgrade_of_an_old_database(tmp_path):
    auth = AuthManager(Store(tmp_path / "new"))
    assert "blocks.edit" in auth.role_perms("Admin") and "blocks.edit" in auth.role_perms("Developer")
    assert "blocks.edit" not in auth.role_perms("Engineer") and "blocks.edit" not in auth.role_perms("Operator")

    old = Store(tmp_path / "old")                                           # a database made before this permission
    first = AuthManager(old)
    for role in ("Admin", "Engineer"):
        first.set_role_perm(role, "blocks.edit", False)
    first.set_role_perm("Engineer", "settings.edit", True)                  # a rule the factory changed
    old.set("auth_known_perms", "")
    upgraded = AuthManager(old)
    assert "blocks.edit" in upgraded.role_perms("Admin") and "blocks.edit" not in upgraded.role_perms("Engineer")
    assert "settings.edit" in upgraded.role_perms("Engineer")               # their own rules are untouched
    upgraded.set_role_perm("Admin", "blocks.edit", False)
    assert "blocks.edit" not in AuthManager(old).role_perms("Admin")        # ... and a later choice is kept


# ---- editor dialog ---------------------------------------------------------------------------
@pytest.fixture
def dialog(window, plugin_dir, pump):
    from visionstudio.ui.block_editor import BlockDialog
    dlg = BlockDialog(window.ctx, window)
    dlg.blocks_changed.connect(window.views["studio"].blocks_changed)
    dlg.show()
    pump(0.05)
    yield dlg
    dlg.close()


def test_dialog_creates_a_block_that_appears_in_the_palette(dialog, window, plugin_dir, pump):
    studio = window.views["studio"]
    assert dialog.is_new and dialog.listing.count() == 0
    dialog.title.setText("Kiểm tra độ sáng")
    dialog.title.textEdited.emit("Kiểm tra độ sáng")
    assert dialog.name.text() == "kiem_tra_do_sang"
    dialog.outputs.set_rows([["result", "RESULT"], ["mean", "MEASUREMENT"]])
    dialog.params.set_rows([["limit", "float", "20", "Ngưỡng sáng"]])
    assert dialog.signature.text().startswith("def run(self, ctx, params, image):")
    dialog._template()
    assert "params[\"limit\"]" in dialog.code.toPlainText()
    dialog.code.setPlainText("mean = float(image.image.mean())\nreturn {\"result\": mean > params[\"limit\"], \"mean\": mean}\n")
    assert dialog.try_block() and "RESULT OK" in dialog.output.toPlainText()
    assert dialog.save_block() and (plugin_dir / "user_kiem_tra_do_sang.py").exists()
    assert dialog.listing.count() == 1 and not dialog.is_new and not dialog.name.isEnabled()
    titles = [studio.tree.topLevelItem(i).child(j).text(0) for i in range(studio.tree.topLevelItemCount())
              for j in range(studio.tree.topLevelItem(i).childCount())]
    assert "Kiểm tra độ sáng" in titles
    assert window.ctx.store.audit_rows(1)[0][2] == "SAVE_BLOCK"

    from PyQt6.QtCore import QPointF
    node_id = studio.scene.add_node("user.kiem_tra_do_sang", QPointF(0, 300))
    studio.scene._connect(studio.scene.node_items["cam1"].out_ports["frame"], studio.scene.node_items[node_id].in_ports["image"])
    job = window.ctx.engine.run_once()
    assert job.outputs[node_id]["mean"].value > 20 and job.result.status in ("OK", "NG")


def test_dialog_refuses_to_save_a_block_that_fails(dialog, plugin_dir):
    dialog.title.setText("Hỏng")
    dialog.name.setText("hong")
    dialog.code.setPlainText("return {\"image\": image.image / 0 +\n")
    assert not dialog.save_block() and list(plugin_dir.iterdir()) == []
    dialog.code.setPlainText("return {\"image\": undefined_name}\n")
    assert not dialog.save_block() and "NameError" in dialog.output.toPlainText()
    dialog.name.setText("Bad Name")
    assert not dialog.save_block() and list(plugin_dir.iterdir()) == []


def test_dialog_edit_changes_ports_and_studio_drops_stale_edges(dialog, window, pump):
    from PyQt6.QtCore import QPointF
    studio = window.views["studio"]
    dialog.load_spec(dict(AREA), is_new=True)
    assert dialog.save_block()
    node_id = studio.scene.add_node("user.area_check", QPointF(0, 300))
    tol = studio.scene.add_node("logic.tolerance", QPointF(300, 300))
    items = studio.scene.node_items
    studio.scene._connect(items["det1"].out_ports["detections"], items[node_id].in_ports["dets"])
    studio.scene._connect(items[node_id].out_ports["area"], items[tol].in_ports["value"])
    edges = len(studio.scene.graph.edges)
    dialog.outputs.set_rows([["result", "RESULT"]])                         # remove the 'area' port
    dialog.code.setPlainText("return {\"result\": len(dets.items) > 0}\n")
    assert dialog.save_block()
    pump(0.05)
    assert len(studio.scene.graph.edges) == edges - 1 and "area" not in studio.scene.node_items[node_id].out_ports
    assert "lỗi cấu hình" in studio.status.text() or "gỡ" in studio.status.text()


def test_dialog_delete_block(dialog, window, plugin_dir, pump):
    dialog.load_spec(dict(AREA), is_new=True)
    assert dialog.save_block() and dialog.listing.count() == 1
    dialog._delete()                                                        # the test fixture answers "Yes"
    pump(0.05)
    assert dialog.listing.count() == 0 and list(plugin_dir.iterdir()) == [] and dialog.is_new
    assert "user.area_check" not in node_base.REGISTRY
    assert window.ctx.store.audit_rows(1)[0][2] == "DELETE_BLOCK"


def test_code_editor_tab_and_auto_indent(dialog, pump):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    dialog.code.setPlainText("")
    dialog.code.setFocus()
    QTest.keyClicks(dialog.code, "if x:")
    QTest.keyClick(dialog.code, Qt.Key.Key_Return)
    QTest.keyClicks(dialog.code, "y = 1")
    QTest.keyClick(dialog.code, Qt.Key.Key_Return)
    QTest.keyClick(dialog.code, Qt.Key.Key_Tab)
    QTest.keyClicks(dialog.code, "z")
    assert dialog.code.toPlainText() == "if x:\n    y = 1\n        z"


def test_block_button_needs_the_permission(window, pump):
    studio = window.views["studio"]
    assert studio.block_btn.isEnabled()                                     # Developer
    window.ctx.login("engineer", "1111")
    pump(0.05)
    assert studio.save_btn.isEnabled() and not studio.block_btn.isEnabled()  # may edit recipes, not write code
    window.ctx.auth.set_role_perm("Engineer", "blocks.edit", True)
    window.ctx.rules_changed()
    pump(0.05)
    assert studio.block_btn.isEnabled()