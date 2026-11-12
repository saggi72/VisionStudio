"""VisionStudio entry point.

    python main.py                              # desktop app (PyQt6), opens the last recipe
    python main.py --recipe recipes/assy_conn_01.json      # simulated demo, no hardware needed
    python main.py --headless --jobs 50         # run the recipe without UI (line service / tests)
"""
from __future__ import annotations

from visionstudio.core.i18n import t

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _log_exceptions(data_dir: str) -> None:
    """PyQt aborts the process on an unhandled exception inside a slot. Log it and keep running."""
    import traceback

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(text)
        try:
            with open(Path(data_dir) / "error.log", "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError:
            pass
    sys.excepthook = hook


def main() -> int:
    ap = argparse.ArgumentParser(description="VisionStudio")
    ap.add_argument("--recipe", default="", help="recipe file (default: last opened, else webcam + YOLO)")
    ap.add_argument("--data", default=str(ROOT / "data"), help="folder for DB, image archive, retrain buffer")
    ap.add_argument("--headless", action="store_true", help="run without UI")
    ap.add_argument("--jobs", type=int, default=0, help="headless: number of jobs (0 = until Ctrl+C)")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):      # a redirected Windows console is not UTF-8 by default
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    from visionstudio.core.engine import Engine
    from visionstudio.core.graph import Recipe
    from visionstudio.core.node_base import load_plugins
    from visionstudio.core.storage import Store

    load_plugins(ROOT / "plugins")
    store = Store(args.data)
    _log_exceptions(args.data)
    engine = Engine(store)
    if not args.recipe:
        last = store.get("last_recipe")
        args.recipe = last if last and Path(last).exists() else str(ROOT / "recipes" / "real_webcam_yolo.json")
    engine.load_recipe(Recipe.load(args.recipe))

    if args.headless:
        import time
        n = 0
        try:
            while args.jobs == 0 or n < args.jobs:
                job = engine.run_once()
                n += 1
                print(f"{job.job_id} {job.serial:<12} {job.result.status:<5} {job.cycle_ms:6.1f} ms  "
                      f"{','.join(job.result.reasons) or 'ALL_PASS'}")
                if args.jobs == 0:
                    time.sleep(store.get("interval_ms", int) / 1000.0)
        except KeyboardInterrupt:
            pass
        engine.shutdown()
        s = engine.stats
        print(t("Tổng {0} | OK {1} | NG {2} | ERROR {3}").format(s['total'], s['ok'], s['ng'], s['error']))
        return 0

    from PyQt6.QtWidgets import QApplication
    from visionstudio.ui.main_window import MainWindow, keep_alive
    from visionstudio.ui.theme import apply_theme

    from visionstudio.core.i18n import set_language

    app = QApplication(sys.argv)
    set_language(store.get("language"))
    apply_theme(app, store.get("theme"))
    win = MainWindow(engine, store, args.recipe)
    keep_alive(win)
    win.showMaximized()
    code = app.exec()
    engine.shutdown()
    return code


if __name__ == "__main__":
    sys.exit(main())