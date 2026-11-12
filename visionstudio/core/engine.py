"""Engine: owns devices, runs the job loop in a worker thread, notifies listeners.

The engine is Qt-free. The UI and the headless runner both drive it through this class.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from ..hardware.manager import DeviceManager
from .executor import Executor, JobResult, last_detections
from .graph import Graph, Recipe
from .schemas import InspectionResult
from .storage import Store


class Engine:
    def __init__(self, store: Store):
        self.store = store
        self.devices = DeviceManager()
        self.recipe: Recipe | None = None
        self.listeners: list[Callable[[JobResult], None]] = []
        self.state_listeners: list[Callable[[bool], None]] = []
        self.stats = store.counts()
        self.last_job: JobResult | None = None
        self.job_no = store.max_job_no()
        self._lock = threading.Lock()
        self._pending: Graph | None = None
        self._executor: Executor | None = None
        self._build_error = ""
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ---- configuration -------------------------------------------------------------------
    def load_recipe(self, recipe: Recipe) -> None:
        was_running = self.running
        self.stop()
        self.recipe = recipe
        self.devices.configure(recipe.devices)
        self.update_graph(recipe.graph)
        if was_running:
            self.start()

    def update_graph(self, graph: Graph) -> None:
        """Hand a snapshot of the edited graph to the worker; applied before the next job."""
        with self._lock:
            self._pending = Graph.from_dict(graph.to_dict())

    # ---- run control ---------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="vs-engine", daemon=True)
        self._thread.start()
        self._notify_state(True)

    def stop(self) -> None:
        if not self.running:
            return
        self._stop.set()
        while self._thread.is_alive():       # a job in progress is allowed to finish, however long it takes;
            self._thread.join(timeout=1)     # returning early would let a second loop start beside it
        self._thread = None
        self._notify_state(False)

    def shutdown(self) -> None:
        self.stop()
        if self._executor:
            self._executor.close()
        self.devices.close()

    def _notify_state(self, running: bool) -> None:
        for cb in list(self.state_listeners):
            cb(running)

    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            self.run_once()
            interval = self.store.get("interval_ms", int) / 1000.0
            self._stop.wait(max(0.0, interval - (time.perf_counter() - t0)))

    # ---- one job -------------------------------------------------------------------------
    def _apply_pending(self) -> None:
        with self._lock:
            graph, self._pending = self._pending, None
        if graph is None:
            return
        if self._executor:
            self._executor.close()
            self._executor = None
        try:
            self._executor = Executor(graph, self.devices, self.store)
            self._build_error = ""
        except Exception as exc:
            self._build_error = str(exc)

    def run_once(self) -> JobResult:
        self._apply_pending()
        self.job_no += 1
        if self._executor is None:
            from datetime import datetime
            job = JobResult(self.job_no, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            InspectionResult("ERROR", ["INVALID_GRAPH", self._build_error[:160]]))
        else:
            self.devices.trigger()
            job = self._executor.run_job(self.job_no)
        self._post_process(job)
        return job

    def _post_process(self, job: JobResult) -> None:
        self.stats["total"] += 1
        self.stats[job.result.status.lower()] = self.stats.get(job.result.status.lower(), 0) + 1
        try:
            self.store.save_inspection(job, self.recipe.label if self.recipe else "")
            dets = last_detections(job)
            if dets and dets.source is not None:
                lo, hi = self.store.get("unc_lo", float), self.store.get("unc_hi", float)
                if any(lo <= d.score <= hi for d in dets.items):
                    self.store.save_uncertain(job.job_id, dets.source.image, dets)
        except Exception as exc:   # storage problems must not stop the line
            job.result.values["storage_error"] = 1.0
            print(f"[storage] {exc}")
        self.last_job = job
        for cb in list(self.listeners):      # a copy: the UI thread may add or remove listeners meanwhile
            cb(job)