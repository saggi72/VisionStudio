"""Cameras, PLCs and the DeviceManager, using only simulated devices, image folders and video files."""
from __future__ import annotations

import threading
import time

import cv2
import numpy as np
import pytest

from visionstudio.hardware import camera as cam_mod
from visionstudio.hardware import plc as plc_mod
from visionstudio.hardware.manager import DeviceManager

from conftest import ROOT


@pytest.fixture
def video(tmp_path):
    """A 15-frame video file: stands in for a webcam / RTSP stream."""
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    for i in range(15):
        writer.write(np.full((240, 320, 3), i * 10, np.uint8))
    writer.release()
    return str(path)


def test_sim_camera_views_and_serial():
    top = cam_mod.SimCamera("c1", {"view": "top"})
    side = cam_mod.SimCamera("c2", {"view": "side"})
    top.open()
    side.open()
    a, b = top.grab(), side.grab()
    assert a.image.shape == b.image.shape == (480, 640, 3) and not np.array_equal(a.image, b.image)
    assert a.meta["serial"] == b.meta["serial"]                       # both cameras see the same part
    assert (a.frame_id, top.grab().frame_id) == (1, 2) and top.status == "Connected"
    serial = a.meta["serial"]
    cam_mod.SIM_WORLD.advance()
    assert top.grab().meta["serial"] != serial


def test_folder_camera_loops_and_uses_file_name_as_serial(tmp_path):
    for name in ("a.png", "b.jpg"):
        cv2.imwrite(str(tmp_path / name), np.zeros((20, 30, 3), np.uint8))
    (tmp_path / "notes.txt").write_text("not an image")
    cam = cam_mod.FolderCamera("c", {"path": str(tmp_path)})
    cam.open()
    assert [cam.grab().meta["serial"] for _ in range(5)] == ["a", "b", "a", "b", "a"]
    assert cam.address == str(tmp_path)


def test_folder_camera_errors(tmp_path):
    with pytest.raises(RuntimeError):
        cam_mod.FolderCamera("c", {"path": str(tmp_path)}).open()                # empty folder
    relative = cam_mod.FolderCamera("c", {"path": "samples"})                     # resolved from the project root
    relative.open()
    assert relative.grab().image.shape == (1080, 810, 3)


def test_opencv_camera_reads_reconnects_and_closes(video):
    before = threading.active_count()
    cam = cam_mod.OpenCVCamera("c", {"source": video})
    cam.open()
    assert cam.grab().image.shape == (240, 320, 3) and cam.status == "Connected"
    time.sleep(1.6)                                    # the file ends -> reader thread reopens it
    assert cam.grab().image.shape == (240, 320, 3)
    cam.close()
    assert cam.status == "Disconnected" and threading.active_count() == before
    cam.close()                                        # closing twice is harmless


def test_opencv_camera_bad_source():
    with pytest.raises(RuntimeError):
        cam_mod.OpenCVCamera("c", {"source": "/no/such/stream.avi"}).open()


def test_camera_fps_counter():
    cam = cam_mod.SimCamera("c", {})
    cam.open()
    assert cam.fps == 0.0
    for _ in range(5):
        cam.grab()
        time.sleep(0.02)
    assert 10 < cam.fps < 200


def test_register_custom_camera_adapter():
    class Dummy(cam_mod.Camera):
        INTERFACE = "Dummy"

        def open(self):
            self.status = "Connected"

        def _read(self):
            return np.zeros((4, 4), np.uint8), {"serial": "X1"}

    cam_mod.register_camera("dummy_test", Dummy)
    try:
        manager = DeviceManager()
        manager.configure({"d": {"kind": "camera", "provider": "dummy_test", "name": "My cam"}})
        assert manager.camera("d").grab().meta["serial"] == "X1"
        assert manager.info()[0]["interface"] == "Dummy" and manager.info()[0]["name"] == "My cam"
    finally:
        cam_mod.CAMERA_PROVIDERS.pop("dummy_test")


def test_sim_plc_read_write_and_timing():
    plc = plc_mod.SimPlc("p", {})
    plc.connect()
    assert plc.read("busy") is False
    plc.write("busy", True)
    assert plc.read("busy") is True and plc.last_write_ms >= 0 and plc.status == "Connected"


def test_modbus_plc_failure_is_contained():
    """No PLC on the bench: the adapter must fail cleanly (missing library or refused connection)."""
    manager = DeviceManager()
    manager.configure({"p": {"kind": "plc", "provider": "modbus", "host": "127.0.0.1", "port": 1}})
    info = manager.info()[0]
    assert info["status"] == "Error" and info["error"]
    manager.close()


def test_manager_keeps_running_with_broken_devices(tmp_path):
    manager = DeviceManager()
    manager.configure({
        "good": {"kind": "camera", "provider": "sim"},
        "bad": {"kind": "camera", "provider": "folder", "path": str(tmp_path / "nothing")},
        "ghost": {"kind": "camera", "provider": "vendor_not_installed"},
        "plc": {"kind": "plc", "provider": "sim"}})
    status = {d["id"]: d["status"] for d in manager.info()}
    assert status == {"good": "Connected", "bad": "Error", "ghost": "No plugin", "plc": "Connected"}
    assert manager.camera("good").grab().image is not None
    with pytest.raises(KeyError):
        manager.camera("nope")
    with pytest.raises(KeyError):
        manager.plc("nope")
    manager.close()
    assert manager.cameras == {} and manager.plcs == {}


def test_manager_reconfigure_closes_old_devices(video):
    before = threading.active_count()
    manager = DeviceManager()
    manager.configure({"c": {"kind": "camera", "provider": "opencv", "source": video}})
    assert threading.active_count() == before + 1
    manager.configure({"c": {"kind": "camera", "provider": "sim"}})                # replaces the video camera
    assert threading.active_count() == before
    manager.close()


def test_trigger_advances_simulated_part():
    manager = DeviceManager()
    manager.configure({"c": {"kind": "camera", "provider": "sim"}})
    first = manager.camera("c").grab().meta["serial"]
    manager.trigger()
    assert manager.camera("c").grab().meta["serial"] != first
    manager.close()