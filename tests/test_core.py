"""Core tests - run without any hardware:  python -m pytest tests -q"""
from pathlib import Path

import pytest

from visionstudio.core.engine import Engine
from visionstudio.core.graph import Graph, GraphError, Recipe
from visionstudio.core.node_base import REGISTRY, load_plugins
from visionstudio.core.storage import Store

ROOT = Path(__file__).resolve().parents[1]
load_plugins(ROOT / "plugins")


def test_builtin_nodes_registered():
    for type_id in ("source.camera", "source.multicam_sync", "ai.blob_detect", "ai.yolo_onnx",
                    "logic.count_by_class", "io.plc_handshake", "classic.threshold"):
        assert type_id in REGISTRY


def test_port_type_and_cycle_are_rejected():
    g = Graph()
    cam = g.add_node("source.camera")
    blur = g.add_node("classic.gaussian_blur")
    cnt = g.add_node("logic.count_by_class")
    assert g.can_connect(cam.id, "frame", cnt.id, "detections") is not None      # IMAGE -> DETECTIONS
    g.add_edge(cam.id, "frame", blur.id, "image")
    blur2 = g.add_node("classic.gaussian_blur")
    g.add_edge(blur.id, "image", blur2.id, "image")
    with pytest.raises(GraphError):
        g.add_edge(blur2.id, "image", blur.id, "image")                           # cycle


def test_validate_reports_unwired_input():
    g = Graph()
    g.add_node("logic.count_by_class")
    assert any("chưa được nối" in msg for _nid, msg in g.validate())


def test_recipe_roundtrip(tmp_path):
    recipe = Recipe.load(ROOT / "recipes" / "assy_conn_01.json")
    recipe.save(tmp_path / "r.json")
    again = Recipe.load(tmp_path / "r.json")
    assert again.version == recipe.version and len(again.graph.nodes) == 6 and len(again.graph.edges) == 5


def test_demo_pipeline_runs_and_is_stored(tmp_path):
    store = Store(tmp_path)
    engine = Engine(store)
    engine.load_recipe(Recipe.load(ROOT / "recipes" / "assy_conn_01.json"))
    jobs = [engine.run_once() for _ in range(80)]
    engine.shutdown()
    assert all(j.result.status in ("OK", "NG") for j in jobs)                    # no ERROR on the sim line
    assert sum(j.result.status == "OK" for j in jobs) > 50
    assert store.counts()["total"] == 80
    assert all(set(j.timings) == set(engine.recipe.graph.nodes) for j in jobs)


def test_invalid_graph_gives_error_not_ok(tmp_path):
    engine = Engine(Store(tmp_path))
    recipe = Recipe.load(ROOT / "recipes" / "assy_conn_01.json")
    recipe.graph.edges.pop()                                                      # unwire the PLC node
    engine.load_recipe(recipe)
    assert engine.run_once().result.status == "ERROR"
    engine.shutdown()


# ---- accounts and permission rules -----------------------------------------------------------
def test_accounts_and_rules(tmp_path):
    from visionstudio.core.auth import ALL_PERMS, AuthError, AuthManager
    auth = AuthManager(Store(tmp_path))
    assert auth.verify("dev", "dev1234")["role"] == "Developer"
    assert auth.verify("admin", "wrong") is None
    assert auth.role_perms("Developer") == ALL_PERMS and auth.role_perms("Operator") == {"engine.run"}

    auth.create_user("QC01", "Nguyen Van A", "Operator", "abcd", actor_role="Admin")
    assert auth.verify("qc01", "abcd")["role"] == "Operator"
    with pytest.raises(AuthError):
        auth.create_user("qc01", "", "Operator", "abcd")                     # duplicate
    with pytest.raises(AuthError):
        auth.create_user("x2", "", "Operator", "12")                         # password too short
    with pytest.raises(AuthError):
        auth.create_user("x3", "", "Developer", "abcd", actor_role="Admin")  # only Developer grants Developer
    with pytest.raises(AuthError):
        auth.set_password("dev", "hacked", actor_role="Admin")

    auth.set_role_perm("Operator", "report.export", True)
    assert "report.export" in auth.role_perms("Operator")
    with pytest.raises(AuthError):
        auth.set_role_perm("Developer", "engine.run", False)                 # Developer stays full access

    auth.add_role("QC_Leader", "Engineer")
    auth.update_user("qc01", role="QC_Leader")
    assert "recipe.edit" in auth.role_perms(auth.user("qc01")["role"])
    with pytest.raises(AuthError):
        auth.delete_role("QC_Leader")                                        # still in use
    auth.update_user("qc01", active=False)
    assert auth.verify("qc01", "abcd") is None                               # locked account


def test_cannot_lock_everyone_out(tmp_path):
    from visionstudio.core.auth import AuthError, AuthManager
    auth = AuthManager(Store(tmp_path))
    auth.delete_user("dev", actor_role="Developer")
    with pytest.raises(AuthError):
        auth.set_role_perm("Admin", "users.manage", False)
    with pytest.raises(AuthError):
        auth.delete_user("admin")
    assert auth.verify("admin", "0000") is not None                          # change was rolled back


def test_accounts_persist(tmp_path):
    from visionstudio.core.auth import AuthManager
    store = Store(tmp_path)
    AuthManager(store).set_password("admin", "newpass")
    store.db.close()
    auth = AuthManager(Store(tmp_path))
    assert auth.verify("admin", "newpass") and auth.verify("admin", "0000") is None


# ---- real detection ------------------------------------------------------------------------
def test_real_yolo_onnx_on_sample_image(tmp_path):
    pytest.importorskip("onnxruntime")
    engine = Engine(Store(tmp_path))
    engine.load_recipe(Recipe.load(ROOT / "recipes" / "real_folder_yolo.json"))
    job = engine.run_once()
    engine.shutdown()
    assert job.result.status == "OK", job.result.reasons
    dets = job.outputs["det1"]["detections"].items
    assert len(dets) == 3 and all(d.cls_name == "person" and d.score > 0.8 for d in dets)


# ---- new nodes, verdict rule, translations ---------------------------------------------------
def test_multi_branch_verdict_and_new_nodes(tmp_path):
    """Two checks on one image: the job is NG as soon as one branch is NG; ERROR is never hidden."""
    from visionstudio.core.executor import Executor
    from visionstudio.hardware.manager import DeviceManager
    devices = DeviceManager()
    devices.configure({"cam1": {"kind": "camera", "provider": "folder", "path": "samples"}})
    g = Graph()
    cam = g.add_node("source.camera", params={"device": "cam1"})
    bright = g.add_node("measure.brightness")
    tol = g.add_node("logic.tolerance", params={"min": 50.0, "max": 200.0})          # passes on bus.jpg
    sharp = g.add_node("measure.sharpness")
    tol2 = g.add_node("logic.tolerance", params={"min": 1e7, "max": 1e9})            # fails
    g.add_edge(cam.id, "frame", bright.id, "image")
    g.add_edge(bright.id, "value", tol.id, "value")
    g.add_edge(cam.id, "frame", sharp.id, "image")
    g.add_edge(sharp.id, "value", tol2.id, "value")
    job = Executor(g, devices, Store(tmp_path)).run_job(1)
    assert job.result.status == "NG" and job.result.reasons == ["SHARPNESS_TOO_LOW"]
    assert set(job.result.values) == {"brightness", "sharpness"}
    comb = g.add_node("logic.combine")                                               # explicit AND gives the same verdict
    g.add_edge(tol.id, "result", comb.id, "a")
    g.add_edge(tol2.id, "result", comb.id, "b")
    assert Executor(g, devices, Store(tmp_path)).run_job(2).result.status == "NG"
    devices.close()


def test_every_ui_string_has_an_english_translation():
    import ast
    from visionstudio.core import i18n
    from visionstudio.core.lang_en import EN

    def vietnamese(s):
        return any(ord(c) > 127 and c.isalpha() for c in s)

    missing = set()
    files = list((ROOT / "visionstudio").rglob("*.py")) + [ROOT / "main.py"] + list((ROOT / "plugins").glob("*.py"))
    for path in files:
        if path.name in ("i18n.py", "lang_en.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "t" and node.args \
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value not in EN:
                missing.add(node.args[0].value)
    for cls in REGISTRY.values():                         # node texts are translated where they are shown
        if cls.TYPE.startswith("user."):                # the user's own blocks are theirs to word
            continue
        for text in [cls.TITLE, cls.DESC, cls.CATEGORY] + [p.label for p in cls.PARAMS]:
            if vietnamese(text) and text not in EN:
                missing.add(text)
        assert cls.DESC, f"{cls.TYPE} has no DESC"
    assert not missing, f"no English text for: {sorted(missing)}"

    i18n.set_language("en")
    try:
        assert i18n.t("Lưu") == "Save" and i18n.t("no such key") == "no such key"
    finally:
        i18n.set_language("vi")
    assert i18n.t("Lưu") == "Lưu"