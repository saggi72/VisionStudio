"""Results database, settings, image archive, retention, retrain buffer and audit trail."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from visionstudio.core.executor import JobResult
from visionstudio.core.schemas import Detection, Detections, Frame, InspectionResult
from visionstudio.core.storage import DEFAULTS, Store


def job(no: int, status: str = "OK", reasons=(), serial: str = "SN-1", with_image: bool = True) -> JobResult:
    preview = np.full((40, 60, 3), 128, np.uint8) if with_image else None
    return JobResult(no, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), InspectionResult(status, list(reasons)),
                     serial=serial, cycle_ms=12.345, preview=preview, n_detections=3)


def test_settings_defaults_persist_and_cast(tmp_path):
    store = Store(tmp_path)
    assert store.get("interval_ms", int) == int(DEFAULTS["interval_ms"]) and store.get("theme") == "dark"
    assert store.get("no_such_key") == ""
    store.set("interval_ms", 250)
    store.set("station_id", "Trạm số 7")
    store.db.close()
    again = Store(tmp_path)
    assert again.get("interval_ms", int) == 250 and again.get("station_id") == "Trạm số 7"
    assert again.get("unc_lo", float) == 0.45


def test_save_query_filter_search(store):
    store.set("ok_sample_n", 1)
    store.save_inspection(job(1, "OK", serial="SN-AAA"), "R1 (v1)")
    store.save_inspection(job(2, "NG", ["MISSING_SCREW"], serial="SN-BBB"), "R1 (v1)")
    store.save_inspection(job(3, "ERROR", ["NODE_FAILED:det1"], serial="SN-CCC"), "R1 (v1)")
    rows = store.query()
    assert [r[0] for r in rows] == [3, 2, 1]                                     # newest first
    assert rows[1][2:7] == ("R1 (v1)", "SN-BBB", "NG", "MISSING_SCREW", 12.35) and rows[2][5] == "ALL_PASS"
    assert [r[0] for r in store.query("NG")] == [2]
    assert [r[0] for r in store.query(search="CCC")] == [3]                      # by serial
    assert [r[0] for r in store.query(search="SCREW")] == [2]                    # by reason
    assert [r[0] for r in store.query(limit=2)] == [3, 2]
    assert store.max_job_no() == 3
    assert store.counts() == {"ok": 1, "ng": 1, "error": 1, "total": 3}


def test_pareto_orders_reasons(store):
    for i, reason in enumerate(["A", "B", "B", "C", "B", "A"], start=1):
        store.save_inspection(job(i, "NG", [reason]), "R")
    store.save_inspection(job(99, "OK"), "R")
    assert store.pareto() == [("B", 3), ("A", 2), ("C", 1)]


def test_archive_keeps_all_ng_and_samples_ok(store):
    store.set("ok_sample_n", 5)
    ok_paths = [store.save_inspection(job(i, "OK"), "R") for i in range(1, 11)]
    assert [bool(p) for p in ok_paths] == [False] * 4 + [True] + [False] * 4 + [True]
    assert ok_paths[4].endswith(".jpg")
    ng = store.save_inspection(job(11, "NG", ["X"]), "R")
    err = store.save_inspection(job(12, "ERROR", ["Y"]), "R")
    assert ng.endswith(".png") and err.endswith(".png")
    assert store.save_inspection(job(13, "NG", ["X"], with_image=False), "R") == ""    # nothing to archive


def test_cleanup_respects_retention(store):
    today = datetime.now().date()
    def make(days_ago, status):
        folder = store.archive_dir / (today - timedelta(days=days_ago)).isoformat() / status
        folder.mkdir(parents=True)
        (folder / "x.png").write_bytes(b"0")
        return folder
    store.set("ok_days", 7)
    store.set("ng_days", 90)
    old_ok, new_ok = make(8, "OK"), make(6, "OK")
    old_ng, mid_ng = make(91, "NG"), make(30, "NG")
    (store.archive_dir / "not-a-date").mkdir()
    assert store.cleanup() == 2
    assert not old_ok.exists() and not old_ng.exists() and new_ok.exists() and mid_ng.exists()
    assert not old_ng.parent.exists()                                            # empty day folder removed
    assert store.cleanup() == 0


def test_retrain_buffer_labels_cap_and_export(store, tmp_path):
    store.set("buffer_max", 3)
    frame = Frame(np.zeros((100, 200, 3), np.uint8))
    for i in range(5):
        dets = Detections([Detection("screw", 0.5, (20, 10, 60, 50)), Detection("nut", 0.6, (0, 0, 200, 100))],
                          (200, 100), "m", frame)
        store.save_uncertain(f"JOB-{i:05d}", frame.image, dets)
    files = store.uncertain_files()
    assert [f.stem for f in files] == ["JOB-00002", "JOB-00003", "JOB-00004"]    # oldest dropped
    assert store.buffer_classes() == ["screw", "nut"]
    label = (store.buffer_dir / "labels" / "JOB-00004.txt").read_text().splitlines()
    assert label == ["0 0.200000 0.300000 0.200000 0.400000", "1 0.500000 0.500000 1.000000 1.000000"]
    assert not (store.buffer_dir / "labels" / "JOB-00000.txt").exists()

    yaml, n = store.export_dataset(tmp_path / "ds")
    assert n == 3 and len(list((tmp_path / "ds" / "images" / "train").glob("*.jpg"))) == 3
    assert len(list((tmp_path / "ds" / "labels" / "train").glob("*.txt"))) == 3
    text = yaml.read_text(encoding="utf-8")
    assert "train: images/train" in text and "  0: screw" in text and "  1: nut" in text


def test_audit_trail_order_and_limit(store):
    for i in range(5):
        store.audit("dev (Developer)", "ACTION", f"detail {i}")
    rows = store.audit_rows(3)
    assert [r[3] for r in rows] == ["detail 4", "detail 3", "detail 2"]
    assert rows[0][1:3] == ("dev (Developer)", "ACTION") and len(rows[0][0]) == 19


def test_job_numbers_continue_after_restart(tmp_path):
    from visionstudio.core.engine import Engine
    store = Store(tmp_path)
    store.save_inspection(job(41), "R")
    store.db.close()
    engine = Engine(Store(tmp_path))
    assert engine.job_no == 41 and engine.stats["total"] == 1