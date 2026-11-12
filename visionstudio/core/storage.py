"""SQLite results DB, audit trail, settings, image archive, and the retrain sample buffer."""
from __future__ import annotations

import shutil
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

import cv2

DEFAULTS = {
    "station_id": "STATION-LINE-01",
    "interval_ms": "500",          # time between software triggers in the demo loop
    "ng_days": "90",               # keep NG / ERROR images (PNG, lossless)
    "ok_days": "7",                # keep sampled OK images (JPEG)
    "ok_sample_n": "20",           # archive 1 of every N OK images
    "unc_lo": "0.45",              # detections scoring inside [lo, hi] go to the retrain buffer
    "unc_hi": "0.65",
    "buffer_max": "500",
    "theme": "dark",               # dark | light
    "language": "vi",              # vi | en
}


class Store:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        self.archive_dir = self.dir / "archive"
        self.buffer_dir = self.dir / "retrain_buffer"
        for d in (self.archive_dir, self.buffer_dir / "images", self.buffer_dir / "labels"):
            d.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.dir / "visionstudio.db", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS inspections(
                job_no INTEGER PRIMARY KEY, ts TEXT, recipe TEXT, serial TEXT, result TEXT,
                reason TEXT, cycle_ms REAL, detections INTEGER, image_path TEXT);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, user TEXT, action TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)
        self._settings = dict(DEFAULTS)
        self._settings.update(dict(self.db.execute("SELECT key, value FROM settings").fetchall()))
        self._ok_seen = 0

    # ---- settings ------------------------------------------------------------------------
    def get(self, key: str, cast=str):
        return cast(self._settings.get(key, DEFAULTS.get(key, "")))

    def set(self, key: str, value) -> None:
        with self.lock:
            self._settings[key] = str(value)
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, str(value)))
            self.db.commit()

    # ---- inspections ---------------------------------------------------------------------
    def max_job_no(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COALESCE(MAX(job_no), 0) FROM inspections").fetchone()[0]

    def save_inspection(self, job, recipe_label: str) -> str:
        image_path = self._archive(job)
        reason = job.result.reasons[0] if job.result.reasons else "ALL_PASS"
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO inspections VALUES(?,?,?,?,?,?,?,?,?)",
                            (job.job_no, job.timestamp, recipe_label, job.serial, job.result.status,
                             reason, round(job.cycle_ms, 2), job.n_detections, image_path))
            self.db.commit()
        return image_path

    def _archive(self, job) -> str:
        if job.preview is None:
            return ""
        status = job.result.status
        if status == "OK":
            self._ok_seen += 1
            if self._ok_seen % max(1, self.get("ok_sample_n", int)) != 0:
                return ""
        folder = self.archive_dir / job.timestamp[:10] / status
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{job.job_id}.{'jpg' if status == 'OK' else 'png'}"
        cv2.imwrite(str(path), job.preview)
        return str(path)

    def query(self, result: str | None = None, search: str = "", limit: int = 500) -> list[tuple]:
        sql, args = "SELECT * FROM inspections WHERE 1=1", []
        if result:
            sql += " AND result=?"
            args.append(result)
        if search:
            sql += " AND (serial LIKE ? OR reason LIKE ?)"
            args += [f"%{search}%", f"%{search}%"]
        with self.lock:
            return self.db.execute(sql + " ORDER BY job_no DESC LIMIT ?", (*args, limit)).fetchall()

    def counts(self) -> dict[str, int]:
        with self.lock:
            rows = dict(self.db.execute("SELECT result, COUNT(*) FROM inspections GROUP BY result").fetchall())
        out = {"ok": rows.get("OK", 0), "ng": rows.get("NG", 0), "error": rows.get("ERROR", 0)}
        out["total"] = sum(out.values())
        return out

    def pareto(self) -> list[tuple[str, int]]:
        with self.lock:
            return self.db.execute("SELECT reason, COUNT(*) c FROM inspections WHERE result!='OK' "
                                   "GROUP BY reason ORDER BY c DESC LIMIT 10").fetchall()

    # ---- audit trail ---------------------------------------------------------------------
    def audit(self, user: str, action: str, detail: str = "") -> None:
        with self.lock:
            self.db.execute("INSERT INTO audit(ts,user,action,detail) VALUES(?,?,?,?)",
                            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user, action, detail))
            self.db.commit()

    def audit_rows(self, limit: int = 200) -> list[tuple]:
        with self.lock:
            return self.db.execute("SELECT ts,user,action,detail FROM audit ORDER BY id DESC LIMIT ?",
                                   (limit,)).fetchall()

    # ---- retention -----------------------------------------------------------------------
    def cleanup(self) -> int:
        """Delete archived images older than the retention settings. Returns files removed."""
        removed, today = 0, datetime.now().date()
        for day_dir in self.archive_dir.iterdir():
            try:
                day = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
            except ValueError:
                continue
            for status_dir in list(day_dir.iterdir()):
                keep = self.get("ok_days", int) if status_dir.name == "OK" else self.get("ng_days", int)
                if day < today - timedelta(days=keep):
                    removed += sum(1 for _ in status_dir.iterdir())
                    shutil.rmtree(status_dir)
            if not any(day_dir.iterdir()):
                day_dir.rmdir()
        return removed

    # ---- retrain buffer (uncertain samples with pseudo-labels) -----------------------------
    def save_uncertain(self, job_id: str, image, dets) -> None:
        names = self.buffer_classes()
        w, h = dets.image_size
        lines = []
        for d in dets.items:
            if d.cls_name not in names:
                names.append(d.cls_name)
            x1, y1, x2, y2 = d.box
            lines.append(f"{names.index(d.cls_name)} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} "
                         f"{(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
        (self.buffer_dir / "classes.txt").write_text("\n".join(names), encoding="utf-8")
        cv2.imwrite(str(self.buffer_dir / "images" / f"{job_id}.jpg"), image)
        (self.buffer_dir / "labels" / f"{job_id}.txt").write_text("\n".join(lines), encoding="utf-8")
        files = self.uncertain_files()
        for old in files[: max(0, len(files) - self.get("buffer_max", int))]:
            old.unlink(missing_ok=True)
            (self.buffer_dir / "labels" / f"{old.stem}.txt").unlink(missing_ok=True)

    def buffer_classes(self) -> list[str]:
        path = self.buffer_dir / "classes.txt"
        return [s for s in path.read_text(encoding="utf-8").splitlines() if s] if path.exists() else []

    def uncertain_files(self) -> list[Path]:
        return sorted((self.buffer_dir / "images").glob("*.jpg"), key=lambda p: p.stat().st_mtime)

    def export_dataset(self, dst: str | Path) -> tuple[Path, int]:
        """Copy the buffer into a YOLO-format dataset folder and write data.yaml."""
        dst = Path(dst)
        (dst / "images" / "train").mkdir(parents=True, exist_ok=True)
        (dst / "labels" / "train").mkdir(parents=True, exist_ok=True)
        files = self.uncertain_files()
        for img in files:
            shutil.copy2(img, dst / "images" / "train" / img.name)
            label = self.buffer_dir / "labels" / f"{img.stem}.txt"
            if label.exists():
                shutil.copy2(label, dst / "labels" / "train" / label.name)
        names = self.buffer_classes()
        yaml = [f"path: {dst.resolve().as_posix()}", "train: images/train", "val: images/train", "names:"]
        yaml += [f"  {i}: {n}" for i, n in enumerate(names)]
        (dst / "data.yaml").write_text("\n".join(yaml) + "\n", encoding="utf-8")
        return dst / "data.yaml", len(files)