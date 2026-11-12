"""Camera interface and adapters.

Add a vendor: subclass Camera, implement open/grab/close, and call register_camera("name", Class).
Vendor SDKs must be imported inside open(), never at module top, so a missing SDK cannot break the app.
"""
from __future__ import annotations

from ..core.i18n import t

import sys
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from ..core.schemas import Frame


class Camera:
    INTERFACE = "?"
    SDK = "-"

    def __init__(self, dev_id: str, cfg: dict):
        self.id, self.cfg = dev_id, cfg
        self.name = cfg.get("name", dev_id)
        self.status = "Disconnected"
        self.error = ""
        self._frame_id = 0
        self._times: deque[float] = deque(maxlen=20)

    def open(self) -> None: ...
    def close(self) -> None: ...
    def _read(self) -> tuple[np.ndarray, dict]:
        raise NotImplementedError

    def grab(self) -> Frame:
        image, meta = self._read()
        self._frame_id += 1
        self._times.append(time.perf_counter())
        return Frame(image, time.time_ns(), self._frame_id, self.id, meta)

    @property
    def fps(self) -> float:
        if len(self._times) < 2 or time.perf_counter() - self._times[-1] > 3:
            return 0.0
        return (len(self._times) - 1) / (self._times[-1] - self._times[0])

    @property
    def address(self) -> str:
        return str(self.cfg.get("source", self.cfg.get("path", self.cfg.get("ip", "-"))))


# ---- simulation ---------------------------------------------------------------------------------
class SimWorld:
    """One simulated part seen by all simulated cameras: 4 connectors (top view), 2 screws (side view)."""
    CONNECTORS = [(170, 150), (470, 150), (170, 330), (470, 330)]
    SCREWS = [(220, 240), (420, 240)]

    def __init__(self):
        self.rng = np.random.default_rng()
        self.part_no = int(time.time()) % 100000
        self.advance()

    def advance(self) -> None:
        r = self.rng
        self.part_no += 1
        self.serial = f"SN-{88400000 + self.part_no}"
        self.connectors = [True] * 4
        self.screws = ["ok", "ok"]
        self.occlusion = float(r.uniform(0.35, 0.6))
        self.jitter = r.integers(-6, 7, size=(6, 2))
        self.gain = float(r.uniform(0.93, 1.07))
        u = r.random()
        if u < 0.03:
            self.connectors[int(r.integers(4))] = False
        elif u < 0.06:
            self.screws[int(r.integers(2))] = "missing"
        elif u < 0.12:
            self.screws[int(r.integers(2))] = "partial"

    def render(self, view: str) -> np.ndarray:
        if view == "side":
            img = np.full((480, 640, 3), (92, 92, 96), np.uint8)
            cv2.rectangle(img, (120, 150), (520, 330), (74, 74, 78), 3)
            for i, (cx, cy) in enumerate(self.SCREWS):
                state = self.screws[i]
                cx, cy = cx + int(self.jitter[4 + i][0]), cy + int(self.jitter[4 + i][1])
                if state == "missing":
                    cv2.circle(img, (cx, cy), 12, (50, 50, 54), -1)       # empty hole
                    continue
                cv2.circle(img, (cx, cy), 30, (205, 205, 210), -1)
                cv2.line(img, (cx - 12, cy), (cx + 12, cy), (70, 70, 75), 3)
                cv2.line(img, (cx, cy - 12), (cx, cy + 12), (70, 70, 75), 3)
                if state == "partial":                                     # part of the head hidden
                    x0 = cx + 30 - int(60 * self.occlusion)
                    cv2.rectangle(img, (x0, cy - 32), (cx + 32, cy + 32), (92, 92, 96), -1)
        else:
            img = np.full((480, 640, 3), (38, 72, 38), np.uint8)
            for y in range(60, 480, 90):
                cv2.line(img, (30, y), (610, y), (48, 96, 48), 2)
            for i, (cx, cy) in enumerate(self.CONNECTORS):
                cx, cy = cx + int(self.jitter[i][0]), cy + int(self.jitter[i][1])
                if not self.connectors[i]:
                    cv2.rectangle(img, (cx - 55, cy - 28), (cx + 55, cy + 28), (30, 58, 30), 2)
                    continue
                cv2.rectangle(img, (cx - 55, cy - 28), (cx + 55, cy + 28), (205, 120, 30), -1)
                for px in range(cx - 40, cx + 41, 20):
                    cv2.rectangle(img, (px - 4, cy - 10), (px + 4, cy + 10), (60, 40, 10), -1)
        img = cv2.convertScaleAbs(img, alpha=self.gain)
        noise = self.rng.integers(-4, 5, img.shape, dtype=np.int16)
        return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


SIM_WORLD = SimWorld()


class SimCamera(Camera):
    INTERFACE = "Simulated"
    SDK = "built-in"

    def open(self) -> None:
        self.status = "Connected"

    def _read(self):
        return SIM_WORLD.render(self.cfg.get("view", "top")), {"serial": SIM_WORLD.serial}

    @property
    def address(self) -> str:
        return f"view={self.cfg.get('view', 'top')}"


# ---- real sources -------------------------------------------------------------------------------
class OpenCVCamera(Camera):
    """Webcam (index) or IP camera (RTSP/HTTP URL) through OpenCV VideoCapture.

    A reader thread keeps only the newest frame, so a job always inspects the current image and
    not one that waited in the driver buffer. If the stream drops, the thread reconnects by itself.
    Optional config: "width", "height" (requested resolution).
    """
    INTERFACE = "UVC / RTSP"
    SDK = f"OpenCV {cv2.__version__}"
    STALE_S = 3.0

    def _open_capture(self):
        src = self.cfg.get("source", 0)
        if str(src).isdigit():
            # DirectShow opens USB webcams much faster than the default backend on Windows
            cap = cv2.VideoCapture(int(src), cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(int(src))
            if not cap.isOpened():
                cap = cv2.VideoCapture(int(src))
        else:
            cap = cv2.VideoCapture(str(src))
        if cap.isOpened():
            for key, prop in (("width", cv2.CAP_PROP_FRAME_WIDTH), ("height", cv2.CAP_PROP_FRAME_HEIGHT)):
                if self.cfg.get(key):
                    cap.set(prop, int(self.cfg[key]))
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def open(self) -> None:
        self.cap = self._open_capture()
        if not self.cap.isOpened():
            raise RuntimeError(t("Không mở được nguồn '{0}'").format(self.cfg.get('source', 0)))
        self._latest: tuple[np.ndarray, float] | None = None
        self._lock = threading.Lock()
        self._new = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._reader, name=f"cam-{self.id}", daemon=True)
        self._thread.start()
        self.status = "Connected"

    def _reader(self) -> None:
        while not self._stop.is_set():
            ok, image = self.cap.read()
            if ok:
                with self._lock:
                    self._latest = (image, time.monotonic())
                self._new.set()
                self.status = "Connected"
                continue
            self.status = "Disconnected"            # stream dropped (or a video file ended): reconnect
            self.cap.release()
            if self._stop.wait(1.0):
                break
            self.cap = self._open_capture()

    def _read(self):
        self._new.clear()
        with self._lock:
            latest = self._latest
        if latest is None or time.monotonic() - latest[1] > 0.2:      # wait for a fresh frame
            self._new.wait(self.STALE_S)
            with self._lock:
                latest = self._latest
        if latest is None or time.monotonic() - latest[1] > self.STALE_S:
            raise RuntimeError(t("Không nhận được ảnh từ camera"))
        return latest[0].copy(), {}

    def close(self) -> None:
        if getattr(self, "_thread", None) is not None:
            self._stop.set()
            self._thread.join(timeout=3)
            self._thread = None
        if getattr(self, "cap", None) is not None:
            self.cap.release()
        self.status = "Disconnected"


class FolderCamera(Camera):
    """Replays the images of a folder in a loop - for offline tests and tuning a recipe."""
    INTERFACE = "Folder"
    SDK = "built-in"

    def open(self) -> None:
        folder = Path(self.cfg.get("path", "."))
        if not folder.is_absolute() and not folder.exists():           # relative to the project root
            folder = Path(__file__).resolve().parents[2] / folder
        self.files = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"))
        if not self.files:
            raise RuntimeError(t("Thư mục '{0}' không có ảnh").format(folder))
        self.status = "Connected"

    def _read(self):
        path = self.files[self._frame_id % len(self.files)]
        image = cv2.imread(str(path))
        if image is None:
            raise RuntimeError(t("Không đọc được {0}").format(path.name))
        return image, {"serial": path.stem}


CAMERA_PROVIDERS: dict[str, type[Camera]] = {}


def register_camera(name: str, cls: type[Camera]) -> None:
    CAMERA_PROVIDERS[name] = cls


register_camera("sim", SimCamera)
register_camera("opencv", OpenCVCamera)
register_camera("folder", FolderCamera)