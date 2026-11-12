from __future__ import annotations

from ..core.i18n import t
from ..core.node_base import Node, Param, register
from ..core.schemas import PortType

CAT = "Nguồn ảnh & Đồng bộ (Source)"


@register
class CameraNode(Node):
    TYPE = "source.camera"
    TITLE = "Camera"
    DESC = "Lấy một ảnh từ camera khai báo trong tab Thiết bị."
    CATEGORY = CAT
    OUTPUTS = {"frame": PortType.IMAGE}
    PARAMS = [Param("device", "device:camera", "cam1", "Thiết bị")]

    def process(self, ctx, **_):
        camera = ctx.devices.camera(self.params["device"])
        if camera.status in ("Error", "No plugin"):          # it never opened: say why, do not try to read
            raise RuntimeError(t("Camera '{0}' chưa kết nối: {1}").format(camera.id, camera.error or camera.status))
        frame = camera.grab()
        if "serial" in frame.meta:
            ctx.shared.setdefault("serial", frame.meta["serial"])
        return {"frame": frame}