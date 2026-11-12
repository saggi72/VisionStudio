"""One test case per node type. A node added without a case here fails test_every_node_has_a_case."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from visionstudio.core.executor import JobContext
from visionstudio.core.node_base import REGISTRY
from visionstudio.core.schemas import Detection, Detections, Frame, InspectionResult, Measurement
from visionstudio.hardware.manager import DeviceManager

from conftest import ROOT


# ---- inputs --------------------------------------------------------------------------------
def color_image() -> Frame:
    img = np.full((240, 320, 3), 40, np.uint8)
    cv2.rectangle(img, (40, 40), (140, 110), (255, 0, 0), -1)        # blue block, 101 x 71 px
    cv2.circle(img, (240, 170), 30, (0, 0, 255), -1)                 # red disc
    return Frame(img, 1_000_000, 1, "cam")


def mask_image() -> Frame:
    m = np.zeros((300, 400), np.uint8)
    cv2.rectangle(m, (50, 50), (150, 120), 255, -1)                  # 101 x 71
    cv2.rectangle(m, (250, 200), (300, 260), 255, -1)                # 51 x 61
    m[5, 5] = 255                                                    # one-pixel speck
    return Frame(m)


def detections() -> Detections:
    items = [Detection("a", 0.9, (0, 0, 10, 10)), Detection("b", 0.6, (30, 40, 40, 50)),
             Detection("a", 0.3, (100, 100, 200, 180))]
    return Detections(items, (320, 240), "test", color_image())


class FakeStore:
    def __init__(self, path):
        self.dir = path


@pytest.fixture
def ctx(tmp_path):
    devices = DeviceManager()
    devices.configure({"cam1": {"kind": "camera", "provider": "sim", "view": "top"},
                       "cam2": {"kind": "camera", "provider": "sim", "view": "side"},
                       "plc1": {"kind": "plc", "provider": "sim"}})
    yield JobContext(devices, FakeStore(tmp_path), job_no=4)
    devices.close()


def run(ctx, type_id, params=None, **inputs):
    node = REGISTRY[type_id]("n1", params or {})
    node.setup(ctx)
    try:
        return node.process(ctx, **inputs)
    finally:
        node.teardown()


# ---- source ----------------------------------------------------------------------------------
def test_camera(ctx):
    frame = run(ctx, "source.camera", {"device": "cam1"})["frame"]
    assert frame.image.shape == (480, 640, 3) and ctx.shared["serial"].startswith("SN-")
    with pytest.raises(KeyError):
        run(ctx, "source.camera", {"device": "missing"})


def test_multicam_sync(ctx):
    a, b = Frame(np.zeros((100, 200, 3), np.uint8), 0), Frame(np.zeros((50, 80, 3), np.uint8), 10_000_000)
    out = run(ctx, "source.multicam_sync", {"max_tolerance_ms": 50.0}, cam1=a, cam2=b)["synced_pair"]
    assert out.image.shape == (100, 360, 3) and out.meta["sync_delta_ms"] == pytest.approx(10.0)
    with pytest.raises(RuntimeError):
        run(ctx, "source.multicam_sync", {"max_tolerance_ms": 5.0}, cam1=a, cam2=b)


# ---- preprocess ------------------------------------------------------------------------------
def test_threshold(ctx):
    for method in ("otsu", "binary", "adaptive"):
        out = run(ctx, "classic.threshold", {"method": method, "thresh": 100}, image=color_image())["mask"].image
        assert out.ndim == 2 and set(np.unique(out)) <= {0, 255}
    normal = run(ctx, "classic.threshold", {"method": "binary", "thresh": 100}, image=color_image())["mask"].image
    inverted = run(ctx, "classic.threshold", {"method": "binary", "thresh": 100, "invert": True}, image=color_image())["mask"].image
    assert np.array_equal(normal, 255 - inverted)


def test_gaussian_blur(ctx):
    out = run(ctx, "classic.gaussian_blur", {"ksize": 6}, image=color_image())["image"].image     # even -> made odd
    assert out.shape == (240, 320, 3) and out.std() < color_image().image.std()


def test_crop(ctx):
    out = run(ctx, "classic.crop", {"x": 40, "y": 40, "w": 100, "h": 70}, image=color_image())["image"]
    assert out.image.shape == (70, 100, 3) and out.meta["crop_offset"] == (40, 40)
    with pytest.raises(RuntimeError):
        run(ctx, "classic.crop", {"x": 5000, "y": 5000}, image=color_image())


def test_grayscale(ctx):
    assert run(ctx, "classic.grayscale", image=color_image())["image"].image.shape == (240, 320)
    assert run(ctx, "classic.grayscale", image=mask_image())["image"].image.shape == (300, 400)   # already grey


def test_resize(ctx):
    assert run(ctx, "classic.resize", {"scale_percent": 50}, image=color_image())["image"].image.shape == (120, 160, 3)
    assert run(ctx, "classic.resize", {"scale_percent": 200}, image=color_image())["image"].image.shape == (480, 640, 3)


def test_rotate_flip(ctx):
    assert run(ctx, "classic.rotate_flip", {"rotate": "90"}, image=color_image())["image"].image.shape == (320, 240, 3)
    src = color_image().image
    flipped = run(ctx, "classic.rotate_flip", {"flip": "horizontal"}, image=color_image())["image"].image
    assert np.array_equal(flipped, src[:, ::-1])
    turned = run(ctx, "classic.rotate_flip", {"rotate": "180"}, image=color_image())["image"].image
    assert np.array_equal(turned, src[::-1, ::-1])


def test_brightness_contrast(ctx):
    out = run(ctx, "classic.brightness_contrast", {"contrast": 1.0, "brightness": 50}, image=color_image())["image"].image
    assert out[0, 0, 0] == 90
    out = run(ctx, "classic.brightness_contrast", {"contrast": 2.0, "brightness": 0}, image=color_image())["image"].image
    assert out[0, 0, 0] == 80 and out.max() == 255                    # saturates, does not wrap


def test_clahe(ctx):
    out = run(ctx, "classic.clahe", image=color_image())["image"].image
    assert out.shape == (240, 320) and out.dtype == np.uint8


def test_canny(ctx):
    edges = run(ctx, "classic.canny", image=mask_image())["edges"].image
    assert set(np.unique(edges)) == {0, 255}
    assert edges[80, 47:53].any() and not edges[60:110, 60:140].any()     # line on the block's edge, none inside
    flat = run(ctx, "classic.canny", image=Frame(np.full((50, 50, 3), 90, np.uint8)))["edges"].image
    assert not flat.any()


def test_morphology(ctx):
    opened = run(ctx, "classic.morphology", {"operation": "open", "ksize": 3}, mask=mask_image())["mask"].image
    assert opened[5, 5] == 0 and opened[80, 100] == 255              # speck removed, block kept
    dilated = run(ctx, "classic.morphology", {"operation": "dilate", "ksize": 5}, mask=mask_image())["mask"].image
    eroded = run(ctx, "classic.morphology", {"operation": "erode", "ksize": 5}, mask=mask_image())["mask"].image
    assert cv2.countNonZero(dilated) > cv2.countNonZero(mask_image().image) > cv2.countNonZero(eroded)


def test_color_mask(ctx):
    blue = run(ctx, "classic.color_mask", {"h_min": 100, "h_max": 130}, image=color_image())["mask"].image
    assert blue[75, 90] == 255 and blue[170, 240] == 0 and blue[5, 5] == 0     # blue block only


def test_example_plugin_invert(ctx):
    assert run(ctx, "example.invert", image=mask_image())["image"].image[80, 100] == 0
    assert run(ctx, "example.invert", {"enabled": False}, image=mask_image())["image"].image[80, 100] == 255


# ---- classic vision --------------------------------------------------------------------------
def test_contours(ctx):
    dets = run(ctx, "classic.contours", {"min_area": 100, "class_name": "part"}, mask=mask_image())["detections"]
    assert sorted(d.box for d in dets.items) == [(50, 50, 151, 121), (250, 200, 301, 261)]
    assert all(d.cls_name == "part" for d in dets.items)
    assert len(run(ctx, "classic.contours", {"min_area": 5000}, mask=mask_image())["detections"].items) == 1
    small = run(ctx, "classic.contours", {"min_area": 100, "max_area": 4000}, mask=mask_image())["detections"]
    assert [d.box for d in small.items] == [(250, 200, 301, 261)]


def test_template_match(ctx, tmp_path):
    image = cv2.imread(str(ROOT / "samples" / "bus.jpg"))
    cv2.imwrite(str(tmp_path / "tpl.png"), image[400:500, 100:200])
    dets = run(ctx, "classic.template_match", {"template": str(tmp_path / "tpl.png")}, image=Frame(image))["detections"]
    assert [d.box for d in dets.items] == [(100, 400, 200, 500)] and dets.items[0].score > 0.99
    blank = Frame(np.zeros((600, 600, 3), np.uint8))
    assert run(ctx, "classic.template_match", {"template": str(tmp_path / "tpl.png")}, image=blank)["detections"].items == []
    with pytest.raises(RuntimeError):
        run(ctx, "classic.template_match", {}, image=Frame(image))                      # no template chosen
    with pytest.raises(FileNotFoundError):
        run(ctx, "classic.template_match", {"template": "no_such_file.png"}, image=Frame(image))


def test_code_reader_qr(ctx):
    code = cv2.QRCodeEncoder.create().encode("SN-12345678")
    code = cv2.copyMakeBorder(cv2.resize(code, (300, 300), interpolation=cv2.INTER_NEAREST), 60, 60, 60, 60,
                              cv2.BORDER_CONSTANT, value=255)
    dets = run(ctx, "classic.code_reader", {"kind": "qr"}, image=Frame(code))["detections"]
    assert [d.cls_name for d in dets.items] == ["qr"]
    assert ctx.shared["serial"] == "SN-12345678" and ctx.shared["codes"] == ["SN-12345678"]
    ctx.shared.clear()
    assert run(ctx, "classic.code_reader", {"kind": "qr"}, image=color_image())["detections"].items == []
    assert "serial" not in ctx.shared


# ---- AI --------------------------------------------------------------------------------------
def test_blob_detect_on_simulated_part(ctx):
    top = ctx.devices.camera("cam1").grab()
    dets = run(ctx, "ai.blob_detect", {"classes": "connector"}, image=top)["detections"]
    assert 3 <= len(dets.items) <= 4 and all(d.cls_name == "connector" for d in dets.items)
    with pytest.raises(ValueError):
        run(ctx, "ai.blob_detect", {"classes": "unknown"}, image=top)


def test_yolo_onnx(ctx):
    pytest.importorskip("onnxruntime")
    image = Frame(cv2.imread(str(ROOT / "samples" / "bus.jpg")))
    dets = run(ctx, "ai.yolo_onnx", {"model": "models/yolo11n.onnx", "conf_threshold": 0.4}, image=image)["detections"]
    assert sorted(d.cls_name for d in dets.items) == ["bus", "person", "person", "person"]
    w, h = dets.image_size
    assert all(0 <= d.box[0] < d.box[2] <= w and 0 <= d.box[1] < d.box[3] <= h for d in dets.items)
    only = run(ctx, "ai.yolo_onnx", {"model": "models/yolo11n.onnx", "only_classes": "bus"}, image=image)["detections"]
    assert [d.cls_name for d in only.items] == ["bus"]
    grey = Frame(cv2.cvtColor(image.image, cv2.COLOR_BGR2GRAY))                         # mono camera input
    assert run(ctx, "ai.yolo_onnx", {"model": "models/yolo11n.onnx"}, image=grey)["detections"].image_size == (810, 1080)
    with pytest.raises(RuntimeError):
        run(ctx, "ai.yolo_onnx", {"model": ""}, image=image)
    with pytest.raises(FileNotFoundError):
        run(ctx, "ai.yolo_onnx", {"model": "models/missing.onnx"}, image=image)


def test_yolo_ultralytics(ctx):
    weights = ROOT / "yolo11n.pt"
    if not weights.exists():
        pytest.skip("yolo11n.pt is not present (it is downloaded on first use of the node)")
    pytest.importorskip("ultralytics")
    image = Frame(cv2.imread(str(ROOT / "samples" / "bus.jpg")))
    dets = run(ctx, "ai.yolo_ultralytics", {"model": str(weights), "device": "cpu", "only_classes": "person"}, image=image)
    assert len(dets["detections"].items) >= 3


# ---- measure ---------------------------------------------------------------------------------
def test_mean_brightness(ctx):
    assert run(ctx, "measure.brightness", image=Frame(np.full((10, 10), 77, np.uint8)))["value"].value == 77.0


def test_sharpness(ctx):
    image = cv2.imread(str(ROOT / "samples" / "bus.jpg"))
    sharp = run(ctx, "measure.sharpness", image=Frame(image))["value"].value
    blurred = run(ctx, "measure.sharpness", image=Frame(cv2.GaussianBlur(image, (15, 15), 0)))["value"].value
    assert sharp > 20 * blurred


def test_white_ratio(ctx):
    m = run(ctx, "measure.white_ratio", mask=mask_image())["value"]
    assert m.unit == "%" and m.value == pytest.approx(100 * (101 * 71 + 51 * 61 + 1) / (300 * 400))


def test_detection_size(ctx):
    m = run(ctx, "measure.detection_size", {"dimension": "width", "mm_per_px": 0.5}, detections=detections())["value"]
    assert (m.value, m.unit) == (50.0, "mm")                                             # largest box is 100 px wide
    m = run(ctx, "measure.detection_size", {"dimension": "area", "class_name": "b"}, detections=detections())["value"]
    assert (m.value, m.unit) == (100.0, "px²")
    with pytest.raises(RuntimeError):
        run(ctx, "measure.detection_size", {"class_name": "zzz"}, detections=detections())


def test_detection_distance(ctx):
    m = run(ctx, "measure.detection_distance", {"class_a": "a", "class_b": "b"}, detections=detections())["value"]
    assert m.value == pytest.approx(50.0)                                                # centres (5,5) and (35,45)
    same = run(ctx, "measure.detection_distance", {"class_a": "a", "class_b": "a"}, detections=detections())["value"]
    assert same.value == pytest.approx(np.hypot(145, 135))
    with pytest.raises(RuntimeError):
        run(ctx, "measure.detection_distance", {"class_a": "a", "class_b": "zzz"}, detections=detections())


# ---- logic -----------------------------------------------------------------------------------
def test_count_by_class(ctx):
    count = lambda expect, strict=True: run(ctx, "logic.count_by_class", {"expect": expect, "strict": strict},
                                            detections=detections())["result"]
    assert count("a=2,b=1").status == "OK"
    assert count("a=3").reasons == ["MISSING_A"]
    assert count("a=1").reasons == ["EXTRA_A"] and count("a=1", strict=False).status == "OK"
    assert count("a=2").values == {"count_a": 2.0, "count_b": 1.0}


def test_tolerance(ctx):
    check = lambda v: run(ctx, "logic.tolerance", {"min": 10.0, "max": 60.0}, value=Measurement("width", v))["result"]
    assert (check(5).status, check(5).reasons) == ("NG", ["WIDTH_TOO_LOW"])
    assert (check(70).status, check(70).reasons) == ("NG", ["WIDTH_TOO_HIGH"])
    assert check(10).status == check(60).status == "OK" and check(33).values == {"width": 33.0}   # bounds included


def test_detection_filter(ctx):
    keep = lambda **p: [d.cls_name for d in run(ctx, "logic.detection_filter", p, detections=detections())["detections"].items]
    assert keep(keep_classes="b") == ["b"]
    assert keep(min_score=0.5) == ["a", "b"]
    assert keep(min_area=1000) == ["a"] and keep(max_area=150) == ["a", "b"]
    assert keep() == ["a", "b", "a"]


def test_presence(ctx):
    check = lambda **p: run(ctx, "logic.presence", p, detections=detections())["result"]
    assert check(required="a,b").status == "OK"
    assert check(required="a,c", forbidden="b").reasons == ["MISSING_C", "FOUND_B"]
    assert check().status == "OK"


def test_combine(ctx):
    both = lambda a, b: run(ctx, "logic.combine", a=InspectionResult(a, [a]), b=InspectionResult(b, [b]))["result"]
    assert [both(*p).status for p in (("OK", "OK"), ("OK", "NG"), ("NG", "ERROR"), ("ERROR", "OK"))] == \
        ["OK", "NG", "ERROR", "ERROR"]
    assert both("NG", "OK").reasons == ["NG", "OK"]


# ---- output ----------------------------------------------------------------------------------
def test_plc_handshake(ctx):
    plc = ctx.devices.plc("plc1")
    run(ctx, "io.plc_handshake", {"device": "plc1"}, result=InspectionResult("NG"))
    assert plc.tags == {"busy": False, "result_ok": False, "result_ng": True, "done": True}
    run(ctx, "io.plc_handshake", {"device": "plc1"}, result=InspectionResult("ERROR"))
    assert plc.tags["result_ok"] is False and plc.tags["result_ng"] is False              # ERROR is neither
    plc.status = "Error"
    with pytest.raises(RuntimeError):
        run(ctx, "io.plc_handshake", {"device": "plc1"}, result=InspectionResult("OK"))


def test_save_image(ctx, tmp_path):
    for job_no in range(1, 7):
        ctx.job_no = job_no
        run(ctx, "io.save_image", {"folder": "cap", "every_n": 3, "format": "png"}, image=color_image())
    files = sorted((tmp_path / "cap").glob("*.png"))
    assert len(files) == 2 and cv2.imread(str(files[0])).shape == (240, 320, 3)           # jobs 3 and 6


def test_data_output(ctx):
    """Covered in depth by tests/test_comm.py; here only that the node is wired to the device manager."""
    from visionstudio.hardware.comm import SimChannel
    channel = SimChannel("com1", {})
    channel.open()
    ctx.devices.comms["com1"] = channel
    ctx.shared["serial"] = "SN-9"
    run(ctx, "io.data_output", {"device": "com1", "template": "{status}|{serial}|{job_no}"}, result=InspectionResult("NG"))
    assert channel.log == [b"NG|SN-9|4\r\n"]


# ---- coverage of this file itself ----------------------------------------------------------------
def test_every_node_has_a_case():
    import inspect
    import sys
    source = inspect.getsource(sys.modules[__name__])
    untested = [type_id for type_id in REGISTRY
                if not type_id.startswith("user.") and f'"{type_id}"' not in source]
    assert not untested, f"add a test for: {untested}"