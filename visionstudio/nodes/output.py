from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import cv2

from ..core.i18n import t
from ..core.node_base import Node, Param, register
from ..core.schemas import PortType

CAT = "Đầu ra & Truyền thông (Output)"
LINE_ENDINGS = {"CRLF": "\r\n", "LF": "\n", "CR": "\r", "none": ""}
_ESCAPES = {"\\r": "\r", "\\n": "\n", "\\t": "\t", "\\\\": "\\"}


def unescape(text: str) -> str:
    """Turn the typed escapes \\r \\n \\t \\xHH into the real characters (e.g. \\x02 = STX, \\x03 = ETX)."""
    def repl(m: re.Match) -> str:
        token = m.group(0)
        return chr(int(token[2:], 16)) if token.startswith("\\x") else _ESCAPES[token]
    return re.sub(r"\\x[0-9a-fA-F]{2}|\\[rnt\\]", repl, text)


def message_fields(ctx, result) -> dict:
    """Everything a message template may use. Result values (count_x, width, ...) are added by name."""
    now = datetime.now()
    fields = {"status": result.status, "ok": 1 if result.status == "OK" else 0,
              "reasons": ";".join(result.reasons), "serial": ctx.shared.get("serial", ""),
              "job_no": ctx.job_no, "job_id": f"JOB-{ctx.job_no:05d}",
              "time": now.strftime("%H:%M:%S"), "date": now.strftime("%Y-%m-%d")}
    for key, value in result.values.items():
        fields.setdefault(key, round(value, 4))
    return fields


@register
class PlcHandshake(Node):
    """Writes the verdict to the PLC: busy on -> result_ok / result_ng -> done on -> busy off.
    An ERROR verdict sets neither result bit, so the PLC can tell 'no judgement' from OK."""
    TYPE = "io.plc_handshake"
    TITLE = "PLC Handshake"
    DESC = "Ghi kết quả xuống PLC theo trình tự busy, result_ok / result_ng, done. Kết quả ERROR không bật bit nào."
    CATEGORY = CAT
    INPUTS = {"result": PortType.RESULT}
    PARAMS = [Param("device", "device:plc", "plc1", "PLC")]

    def process(self, ctx, result):
        plc = ctx.devices.plc(self.params["device"])
        if plc.status != "Connected":
            raise RuntimeError(t("PLC '{0}' chưa kết nối: {1}").format(plc.id, plc.error or plc.status))
        plc.write("busy", True)
        plc.write("result_ok", result.status == "OK")
        plc.write("result_ng", result.status == "NG")
        plc.write("done", True)
        plc.write("busy", False)
        return {}


@register
class SaveImage(Node):
    TYPE = "io.save_image"
    TITLE = "Save Image"
    DESC = ("Lưu ảnh đi qua node vào một thư mục, mỗi N job một ảnh. Dùng để gom ảnh gốc làm dữ liệu huấn luyện. "
            "Thư mục tương đối được tính từ thư mục dữ liệu của ứng dụng.")
    CATEGORY = CAT
    INPUTS = {"image": PortType.IMAGE}
    PARAMS = [Param("folder", "str", "captures", "Thư mục lưu"),
              Param("every_n", "int", 1, "Lưu mỗi N job", 1, 100000),
              Param("format", "choice", "jpg", "Định dạng", choices=["jpg", "png", "bmp"])]

    def process(self, ctx, image):
        if ctx.job_no % max(1, self.params["every_n"]) == 0:
            folder = Path(self.params["folder"])
            if not folder.is_absolute():
                folder = Path(ctx.store.dir) / folder
            folder.mkdir(parents=True, exist_ok=True)
            name = f"{datetime.now():%Y%m%d_%H%M%S}_{ctx.job_no:06d}.{self.params['format']}"
            if not cv2.imwrite(str(folder / name), image.image):
                raise RuntimeError(t("Không ghi được ảnh vào {0}").format(folder))
        return {}


@register
class DataOutput(Node):
    """Sends the verdict as one message through a communication channel declared in the Devices tab."""
    TYPE = "io.data_output"
    TITLE = "Data Output"
    DESC = ("Gửi kết quả ra ngoài qua một kênh truyền khai báo trong tab Thiết bị: serial (UART, RS-232, RS-485), "
            "TCP, UDP hoặc EtherCAT. Bản tin dựng theo mẫu, JSON hoặc CSV. Trường dùng trong mẫu: {status} {ok} {serial} "
            "{job_no} {job_id} {reasons} {date} {time} và tên các giá trị đo (ví dụ {count_screw}); \\x02 là ký tự mã 02. "
            "Gửi lỗi thì job báo ERROR.")
    CATEGORY = CAT
    INPUTS = {"result": PortType.RESULT}
    PARAMS = [Param("device", "device:comm", "", "Kênh truyền"),
              Param("format", "choice", "template", "Định dạng bản tin", choices=["template", "json", "csv"]),
              Param("template", "str", "{status},{serial},{reasons}", "Mẫu bản tin"),
              Param("line_ending", "choice", "CRLF", "Ký tự kết thúc", choices=list(LINE_ENDINGS)),
              Param("encoding", "choice", "ascii", "Bảng mã", choices=["ascii", "utf-8"]),
              Param("send_when", "choice", "always", "Gửi khi", choices=["always", "ok_only", "ng_only", "not_ok"])]

    def build(self, ctx, result) -> bytes:
        p = self.params
        fields = message_fields(ctx, result)
        if p["format"] == "json":
            text = json.dumps({"job": fields["job_no"], "date": fields["date"], "time": fields["time"],
                               "serial": fields["serial"], "status": result.status, "reasons": result.reasons,
                               "values": result.values}, ensure_ascii=False)
        elif p["format"] == "csv":
            text = ",".join(str(fields[k]) for k in ("date", "time", "job_no", "serial", "status", "reasons"))
        else:
            try:
                text = unescape(p["template"]).format_map(fields)
            except KeyError as exc:
                raise ValueError(t("Mẫu bản tin dùng trường {0} không có. Các trường có sẵn: {1}").format(
                    exc, ", ".join(sorted(fields)))) from exc
        return (text + LINE_ENDINGS[p["line_ending"]]).encode(p["encoding"], errors="replace")

    def process(self, ctx, result):
        when = self.params["send_when"]
        wanted = (when == "always" or (when == "ok_only" and result.status == "OK")
                  or (when == "ng_only" and result.status == "NG") or (when == "not_ok" and result.status != "OK"))
        if wanted:
            data = self.build(ctx, result)
            ctx.devices.comm(self.params["device"]).send(data)
            ctx.shared["last_message"] = data
        return {}