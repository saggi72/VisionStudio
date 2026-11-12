"""Stress tests: long runs, edits while running, rapid start/stop, big graphs, many accounts, UI churn.

    python -m pytest tests/test_stress.py -q -s                    # about one minute
    python -m pytest tests/test_stress.py -q -s --stress-scale 10  # ten times the load

Each test prints one line with what it measured (shown with -s). They use only simulated devices.
"""
from __future__ import annotations

import gc
import random
import threading
import time

import numpy as np
import pytest
from PyQt6.QtCore import QPointF

from visionstudio.core.auth import AuthError, AuthManager
from visionstudio.core.engine import Engine
from visionstudio.core.executor import Executor
from visionstudio.core.graph import Graph, GraphError, Recipe
from visionstudio.core.node_base import REGISTRY
from visionstudio.core.schemas import Detection, Detections, Frame, PortType
from visionstudio.hardware.manager import DeviceManager

from conftest import SIM_RECIPE


def rss_mb() -> float:
    """Memory of this process in MB. Without psutil (pip install psutil) memory checks are skipped."""
    try:
        import psutil
    except ImportError:
        return 0.0
    return psutil.Process().memory_info().rss / 1e6


def report(name: str, text: str) -> None:
    print(f"\n[stress] {name}: {text}")


# ---- engine ----------------------------------------------------------------------------------
def test_long_run_is_stable_and_leak_free(engine, scale):
    """Thousands of jobs: every job is judged and stored, cycle time does not drift, memory is flat."""
    n = int(1500 * scale)
    engine.store.set("ok_sample_n", 50)
    for _ in range(200):
        engine.run_once()                                  # warm-up (caches, first allocations)
    gc.collect()
    mem0, t0, cycles = rss_mb(), time.perf_counter(), []
    for _ in range(n):
        job = engine.run_once()
        assert job.result.status in ("OK", "NG"), job.result.reasons
        cycles.append(job.cycle_ms)
    elapsed = time.perf_counter() - t0
    gc.collect()
    growth = rss_mb() - mem0
    first, last = np.median(cycles[:200]), np.median(cycles[-200:])
    counts = engine.store.counts()
    report("long run", f"{n} jobs in {elapsed:.1f} s ({n / elapsed:.0f} jobs/s), median cycle {np.median(cycles):.2f} ms, "
                       f"p99 {np.percentile(cycles, 99):.2f} ms, first/last 200 median {first:.2f}/{last:.2f} ms, "
                       f"memory {growth:+.1f} MB, OK {counts['ok']} NG {counts['ng']}")
    assert counts["total"] == n + 200 == engine.job_no and counts == engine.stats
    assert counts["ng"] > 0 and counts["ok"] > counts["ng"]            # the simulator injects a few defects
    assert last < first * 2 + 2, "cycle time drifts upwards"
    assert growth < 60 * max(1.0, scale), "memory keeps growing"
    assert len(engine.store.uncertain_files()) <= engine.store.get("buffer_max", int)


def test_graph_edits_while_the_line_runs(engine, scale):
    """A second thread keeps replacing the graph (valid, invalid, failing) while jobs run flat out."""
    engine.store.set("interval_ms", 0)
    jobs = []
    engine.listeners.append(jobs.append)
    good = Recipe.load(SIM_RECIPE).graph

    def variant(kind: str) -> Graph:
        g = Graph.from_dict(good.to_dict())
        if kind == "strict":
            g.nodes["cnt1"].params["expect"] = "connector=99"
        elif kind == "invalid":
            g.remove_node("cnt1")
        elif kind == "failing":
            g.nodes["cam2"].params["device"] = "no_such_camera"
        elif kind == "empty":
            return Graph()
        return g

    engine.start()
    kinds = ["good", "strict", "invalid", "failing", "empty"]
    edits = int(300 * scale)
    for i in range(edits):
        engine.update_graph(variant(kinds[i % len(kinds)]))
        time.sleep(0.004)
    engine.update_graph(variant("good"))
    time.sleep(0.3)
    assert engine.running, "the engine thread died"
    engine.stop()
    statuses = {s: sum(1 for j in jobs if j.result.status == s) for s in ("OK", "NG", "ERROR")}
    report("edits while running", f"{edits} graph swaps, {len(jobs)} jobs: {statuses}")
    assert len(jobs) > edits / 4 and sum(statuses.values()) == len(jobs)
    assert statuses["ERROR"] > 0 and statuses["NG"] > 0 and jobs[-1].result.status in ("OK", "NG")
    assert [j.job_no for j in jobs] == list(range(1, len(jobs) + 1))    # no job lost or duplicated
    assert engine.store.counts()["total"] == len(jobs)


def test_rapid_start_stop_and_recipe_reload(engine, scale):
    engine.store.set("interval_ms", 0)
    before = threading.active_count()
    cycles = int(60 * scale)
    for i in range(cycles):
        engine.start()
        if i % 3 == 0:
            engine.load_recipe(Recipe.load(SIM_RECIPE))    # reload while running: stops, swaps, restarts
            assert engine.running
        time.sleep(0.01)
        engine.stop()
        assert not engine.running
    assert threading.active_count() == before, "engine threads were left behind"
    report("start/stop", f"{cycles} cycles, {engine.stats['total']} jobs, threads back to {before}")
    assert engine.stats == engine.store.counts() and engine.stats["error"] == 0


def test_stop_waits_for_a_slow_job(store):
    """stop() must not return while a job is still running, or a second loop could start beside it."""
    from visionstudio.core.node_base import Node, register

    @register
    class Slow(Node):
        TYPE, TITLE, DESC, CATEGORY = "test.slow", "Slow", "x", "Test"
        INPUTS = {"image": PortType.IMAGE}
        OUTPUTS = {"image": PortType.IMAGE}
        active = 0
        worst = 0

        def process(self, ctx, image):
            Slow.active += 1
            Slow.worst = max(Slow.worst, Slow.active)
            time.sleep(0.25)
            Slow.active -= 1
            return {"image": image}

    try:
        engine = Engine(store)
        recipe = Recipe.load(SIM_RECIPE)
        slow = recipe.graph.add_node("test.slow")
        recipe.graph.edges = [e for e in recipe.graph.edges if e.dst != "det1"]
        recipe.graph.add_edge("sync1", "synced_pair", slow.id, "image")
        recipe.graph.add_edge(slow.id, "image", "det1", "image")
        engine.load_recipe(recipe)
        store.set("interval_ms", 0)
        for _ in range(4):
            engine.start()
            time.sleep(0.05)                               # stop arrives in the middle of a job
            engine.stop()
            assert Slow.active == 0, "stop() returned while a job was still running"
        engine.shutdown()
        assert Slow.worst == 1, "two jobs ran at the same time"
    finally:
        REGISTRY.pop("test.slow", None)


def test_wide_and_deep_graphs(store, scale):
    """A 300-node chain and a 60-branch fan-out validate, sort and execute."""
    devices = DeviceManager()
    devices.configure({"cam1": {"kind": "camera", "provider": "sim"}})
    n = int(300 * scale)
    chain = Graph()
    prev = chain.add_node("source.camera", params={"device": "cam1"})
    port = "frame"
    for i in range(n):
        node = chain.add_node("classic.brightness_contrast", params={"contrast": 1.0, "brightness": 0})
        chain.add_edge(prev.id, port, node.id, "image")
        prev, port = node, "image"
    m, tol = chain.add_node("measure.brightness"), chain.add_node("logic.tolerance", params={"min": 0.0, "max": 255.0})
    chain.add_edge(prev.id, "image", m.id, "image")
    chain.add_edge(m.id, "value", tol.id, "value")
    t0 = time.perf_counter()
    assert chain.validate() == [] and len(chain.topo_order()) == n + 3
    t_validate = time.perf_counter() - t0
    assert chain.can_connect(tol.id, "result", prev.id, "image")        # type mismatch, found quickly
    executor = Executor(chain, devices, store)
    job = executor.run_job(1)
    assert job.result.status == "OK" and len(job.timings) == n + 3

    fan = Graph()
    cam = fan.add_node("source.camera", params={"device": "cam1"})
    branches = int(60 * scale)
    for i in range(branches):
        b = fan.add_node("measure.brightness")
        t = fan.add_node("logic.tolerance", params={"min": 0.0, "max": 255.0 if i else 1.0})   # branch 0 fails
        fan.add_edge(cam.id, "frame", b.id, "image")
        fan.add_edge(b.id, "value", t.id, "value")
    job2 = Executor(fan, devices, store).run_job(2)
    report("big graphs", f"chain of {n + 3} nodes: validate+sort {t_validate * 1000:.0f} ms, job {job.cycle_ms:.0f} ms; "
                         f"fan-out of {branches} branches: job {job2.cycle_ms:.0f} ms -> {job2.result.status}")
    assert job2.result.status == "NG" and job2.result.reasons == ["BRIGHTNESS_TOO_HIGH"]
    assert t_validate < 5 * max(1.0, scale ** 2)
    devices.close()


def test_random_graph_edits_never_corrupt_the_model(scale):
    """Fuzz: random add / connect / remove. Only GraphError may be raised, and the graph stays a DAG."""
    rng = random.Random(1234)
    types = sorted(REGISTRY)
    g = Graph()
    ops = int(4000 * scale)
    refused = 0
    for _ in range(ops):
        roll = rng.random()
        if roll < 0.35 or len(g.nodes) < 2:
            g.add_node(rng.choice(types), rng.uniform(0, 2000), rng.uniform(0, 1000))
        elif roll < 0.85:
            a, b = rng.sample(list(g.nodes), 2)
            outs, ins = REGISTRY[g.nodes[a].type].OUTPUTS, REGISTRY[g.nodes[b].type].INPUTS
            if outs and ins:
                try:
                    g.add_edge(a, rng.choice(list(outs)), b, rng.choice(list(ins)))
                except GraphError:
                    refused += 1
        elif roll < 0.95:
            g.remove_node(rng.choice(list(g.nodes)))
        elif g.edges:
            g.remove_edge(rng.choice(g.edges))
        if len(g.nodes) > 120:
            g.remove_node(rng.choice(list(g.nodes)))
    order = g.topo_order()                                 # raises if a loop slipped in
    assert sorted(order) == sorted(g.nodes)
    assert all(e.src in g.nodes and e.dst in g.nodes for e in g.edges)
    targets = [(e.dst, e.dst_port) for e in g.edges]
    assert len(targets) == len(set(targets)), "an input port has two edges"
    again = Graph.from_dict(g.to_dict())
    assert again.to_dict() == g.to_dict()
    g.validate()
    report("graph fuzz", f"{ops} random edits, {refused} connections refused, final {len(g.nodes)} nodes / {len(g.edges)} edges")


# ---- storage and accounts ----------------------------------------------------------------------
def test_database_under_concurrent_access(engine, scale):
    """UI-like threads query, audit and change settings while the engine thread stores jobs."""
    store = engine.store
    store.set("interval_ms", 0)
    errors, done = [], threading.Event()
    counters = {"query": 0, "audit": 0, "set": 0}

    def worker(kind: str) -> None:
        try:
            i = 0
            while not done.is_set():
                i += 1
                if kind == "query":
                    store.query("NG" if i % 2 else None, "SN" if i % 3 == 0 else "", 200)
                    store.counts()
                    store.pareto()
                elif kind == "audit":
                    store.audit("stress", "PING", str(i))
                    store.audit_rows(50)
                else:
                    store.set("station_id", f"LINE-{i}")
                    store.get("station_id")
                counters[kind] += 1
        except Exception as exc:                           # pragma: no cover - reported below
            errors.append(f"{kind}: {type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(k,)) for k in ("query", "query", "audit", "set")]
    engine.start()
    for t in threads:
        t.start()
    time.sleep(3.0 * scale)
    done.set()
    for t in threads:
        t.join(timeout=10)
    engine.stop()
    report("database", f"{engine.stats['total']} jobs stored while {counters['query']} queries, {counters['audit']} audit "
                       f"writes and {counters['set']} setting writes ran")
    assert not errors, errors
    assert engine.stats["total"] > 20 and store.counts() == engine.stats
    assert all(v > 20 for v in counters.values())
    assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_many_accounts_and_roles(store, scale):
    auth = AuthManager(store)
    n = int(150 * scale)
    t0 = time.perf_counter()
    for i in range(n):
        auth.create_user(f"user{i:04d}", f"Người dùng {i}", ("Operator", "Engineer", "Admin")[i % 3], f"pw-{i:04d}")
    t_create = time.perf_counter() - t0
    assert len(auth.users()) == n + 3
    assert auth.verify("user0007", "pw-0007")["role"] == "Engineer" and auth.verify("user0007", "pw-0008") is None
    for i in range(20):
        auth.add_role(f"Role_{i}", "Engineer")
        auth.set_role_perm(f"Role_{i}", "users.manage", i % 2 == 0)
    assert len(auth.roles()) == 24
    for i in range(0, n, 2):
        auth.update_user(f"user{i:04d}", role=f"Role_{i % 20}", active=i % 4 == 0)
    for i in range(n):
        auth.delete_user(f"user{i:04d}")
    with pytest.raises(AuthError):
        for name in ("dev", "admin"):                      # the last manager cannot be removed
            auth.delete_user(name, actor_role="Developer")
    assert [u["username"] for u in auth.users() if "users.manage" in auth.role_perms(u["role"])]
    report("accounts", f"{n} accounts created in {t_create:.1f} s ({t_create / n * 1000:.0f} ms each, password hashing), "
                       f"20 roles, all removed again")


def test_retrain_buffer_and_archive_stay_bounded(store, scale):
    store.set("buffer_max", 50)
    store.set("ok_sample_n", 10)
    frame = Frame(np.zeros((120, 160, 3), np.uint8))
    n = int(600 * scale)
    for i in range(n):
        dets = Detections([Detection(f"class{i % 7}", 0.5, (10, 10, 60, 60))], (160, 120), "m", frame)
        store.save_uncertain(f"JOB-{i:06d}", frame.image, dets)
    files = store.uncertain_files()
    labels = list((store.buffer_dir / "labels").glob("*.txt"))
    report("retrain buffer", f"{n} samples offered, {len(files)} images and {len(labels)} labels kept")
    assert len(files) == 50 == len(labels) and files[-1].stem == f"JOB-{n - 1:06d}"
    assert store.buffer_classes() == [f"class{i}" for i in range(7)]


# ---- hardware --------------------------------------------------------------------------------
def test_camera_open_close_cycles_leave_no_threads(tmp_path, scale):
    import cv2
    from visionstudio.hardware.camera import OpenCVCamera
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30, (160, 120))
    for i in range(30):
        writer.write(np.full((120, 160, 3), i * 8, np.uint8))
    writer.release()
    before, mem0 = threading.active_count(), rss_mb()
    cycles = int(40 * scale)
    for _ in range(cycles):
        cam = OpenCVCamera("c", {"source": str(path)})
        cam.open()
        assert cam.grab().image.shape == (120, 160, 3)
        cam.close()
    report("camera cycles", f"{cycles} open/grab/close cycles, threads {before} -> {threading.active_count()}, "
                            f"memory {rss_mb() - mem0:+.1f} MB")
    assert threading.active_count() == before


# ---- user interface --------------------------------------------------------------------------
def test_ui_survives_a_flood_of_jobs(window, pump, scale):
    """Engine at full speed while the operator, studio and history tabs are shown in turn."""
    ctx = window.ctx
    ctx.store.set("interval_ms", 0)
    window.views["studio"].scene.node_items["det1"].setSelected(True)
    window.run_btn.click()
    t0, switches, slowest = time.time(), 0, 0.0
    while time.time() - t0 < 4.0 * scale:
        key = ("operator", "studio", "history", "reports", "devices", "retrain", "settings")[switches % 7]
        t1 = time.perf_counter()
        window.tab_buttons[key].click()
        pump(0.08)
        slowest = max(slowest, time.perf_counter() - t1 - 0.08)
        switches += 1
    window.run_btn.click()
    pump(0.2)
    total = ctx.engine.stats["total"]
    report("UI flood", f"{total} jobs in {4.0 * scale:.0f} s with {switches} tab switches, slowest UI step {slowest * 1000:.0f} ms")
    assert not ctx.engine.running and total > 40
    assert window.views["operator"].total.text().replace(",", "") == str(total)
    assert slowest < 1.5, "the UI froze while jobs were arriving"


def test_editor_handles_hundreds_of_nodes_and_edits(window, pump, scale):
    studio = window.views["studio"]
    scene = studio.scene
    scene.select_all()
    scene.delete_selected()
    n = int(150 * scale)
    t0 = time.perf_counter()
    prev = scene.add_node("source.camera", QPointF(0, 0))
    port = "frame"
    for i in range(n):
        node = scene.add_node("classic.gaussian_blur", QPointF(30 * (i % 40), 60 * (i // 40)))
        scene._connect(scene.node_items[prev].out_ports[port], scene.node_items[node].in_ports["image"])
        prev, port = node, "image"
    t_build = time.perf_counter() - t0
    assert len(scene.graph.nodes) == n + 1 and len(scene.graph.edges) == n
    t0 = time.perf_counter()
    scene.auto_layout()
    studio.fit_view()
    pump(0.2)
    t_layout = time.perf_counter() - t0 - 0.2
    xs = [scene.node_items[nid].pos().x() for nid in scene.graph.topo_order()]
    assert xs == sorted(xs) and len(set(xs)) == n + 1                   # a clean left-to-right chain
    undone = 0
    while scene.can_undo():
        scene.undo()
        undone += 1
    assert undone == 60                                                # history is capped, not unbounded
    while scene.can_redo():
        scene.redo()
    assert len(scene.graph.nodes) == n + 1 and len(scene.graph.edges) == n
    scene.select_all()
    scene.copy_selected()
    scene.paste()
    assert len(scene.graph.nodes) == 2 * (n + 1) and len(scene.graph.edges) == 2 * n
    scene.select_all()
    scene.delete_selected()
    pump(0.1)
    assert len(scene.graph.nodes) == 0 and len(scene.items()) == 0
    report("editor", f"{n + 1} nodes built with {2 * n + 1} undoable edits in {t_build:.1f} s, layout+fit {t_layout * 1000:.0f} ms, "
                     f"undo history capped at {undone}")
    assert t_build < 60 * max(1.0, scale ** 2)


def test_repeated_theme_and_language_switches_do_not_leak(window, qapp, pump, scale):
    """Each switch rebuilds the window. Old windows must really go away, and jobs must keep flowing."""
    ctx = window.ctx
    ctx.store.set("interval_ms", 10)
    window.run_btn.click()
    pump(0.2)
    switches = int(24 * scale)

    def census():
        gc.collect()
        pump(0.05)
        return len(qapp.allWidgets()), rss_mb()

    for i in range(4):                                     # warm-up: both themes and both languages once
        current = qapp.property("main_window")
        (current.theme_btn if i % 2 == 0 else current.lang_btn).click()
        pump(0.25)
    widgets0, mem0 = census()
    for i in range(switches):
        current = qapp.property("main_window")
        (current.theme_btn if i % 2 == 0 else current.lang_btn).click()
        pump(0.25)
    widgets1, mem1 = census()
    current = qapp.property("main_window")
    jobs_before = current.ctx.engine.stats["total"]
    pump(0.3)
    report("rebuilds", f"{switches} theme/language switches while running: widgets {widgets0} -> {widgets1}, "
                       f"memory {mem1 - mem0:+.1f} MB, engine listeners {len(current.ctx.engine.listeners)}")
    assert current.ctx.engine.running and current.ctx.engine.stats["total"] > jobs_before
    assert current.ctx.user["username"] == "dev"
    assert len(current.ctx.engine.listeners) == 1 and len(current.ctx.engine.state_listeners) == 1
    assert widgets1 <= widgets0 * 1.1, "old windows are not being destroyed"
    assert mem1 - mem0 < 80 * max(1.0, scale)


def test_login_logout_and_rule_changes_in_a_loop(window, pump, scale):
    ctx = window.ctx
    rounds = int(30 * scale)
    for i in range(rounds):
        ctx.logout()
        assert not window.views["studio"].save_btn.isEnabled()
        assert ctx.login(("engineer", "admin", "dev")[i % 3], ("1111", "0000", "dev1234")[i % 3])
        assert not ctx.login("admin", "wrong-password") and ctx.user["username"] != "guest"
        assert window.views["studio"].save_btn.isEnabled()
        ctx.auth.set_role_perm("Operator", "report.export", i % 2 == 0)
        ctx.rules_changed()
        if i % 5 == 0:
            pump(0.02)
    pump(0.1)
    assert len(ctx.store.audit_rows(10_000)) >= rounds * 3
    report("sessions", f"{rounds} logout/login/failed-login rounds with rule changes, "
                       f"{len(ctx.store.audit_rows(10_000))} audit rows")