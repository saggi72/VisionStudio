"""Example plugin: drop any .py file like this one into plugins/ and its nodes appear in the palette.
No change to the core is needed. Use it as the template for your own nodes."""
import cv2

from visionstudio.core.node_base import Node, Param, register
from visionstudio.core.schemas import PortType


@register
class InvertImage(Node):
    """Đảo sáng tối của ảnh (ví dụ plugin)."""
    TYPE = "example.invert"
    TITLE = "Invert (plugin mẫu)"
    DESC = "Đảo sáng tối của ảnh. Đây là plugin mẫu để tham khảo cách viết node."
    CATEGORY = "Tiền xử lý (Preprocess)"
    INPUTS = {"image": PortType.IMAGE}
    OUTPUTS = {"image": PortType.IMAGE}
    PARAMS = [Param("enabled", "bool", True, "Bật")]

    def process(self, ctx, image):
        out = cv2.bitwise_not(image.image) if self.params["enabled"] else image.image
        return {"image": image.with_image(out)}