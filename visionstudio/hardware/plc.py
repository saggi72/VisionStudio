"""PLC interface and adapters. Pipelines use logical tag names (busy, done, result_ok, result_ng);
each adapter maps them to protocol addresses from the recipe's device config.
"""
from __future__ import annotations

from ..core.i18n import t

import time


class Plc:
    INTERFACE = "?"
    SDK = "-"

    def __init__(self, dev_id: str, cfg: dict):
        self.id, self.cfg = dev_id, cfg
        self.name = cfg.get("name", dev_id)
        self.status = "Disconnected"
        self.error = ""
        self.last_write_ms = 0.0

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def read(self, tag: str): ...
    def _write(self, tag: str, value) -> None: ...

    def write(self, tag: str, value) -> None:
        t0 = time.perf_counter()
        self._write(tag, value)
        self.last_write_ms = (time.perf_counter() - t0) * 1000.0

    @property
    def address(self) -> str:
        return str(self.cfg.get("host", "-"))


class SimPlc(Plc):
    INTERFACE = "Simulated"
    SDK = "built-in"

    def connect(self) -> None:
        self.tags: dict[str, object] = {}
        self.status = "Connected"

    def read(self, tag: str):
        return self.tags.get(tag, False)

    def _write(self, tag: str, value) -> None:
        self.tags[tag] = value


class ModbusTcpPlc(Plc):
    """Modbus TCP coils. Recipe config: {"provider": "modbus", "host": "192.168.0.10", "port": 502,
    "tags": {"busy": 0, "done": 1, "result_ok": 2, "result_ng": 3}}. Requires `pip install pymodbus`.
    NOTE: written against the pymodbus 3.x client API and not yet verified on a real PLC.
    """
    INTERFACE = "Modbus TCP"
    SDK = "pymodbus"

    def connect(self) -> None:
        from pymodbus.client import ModbusTcpClient   # lazy: optional dependency
        self.client = ModbusTcpClient(self.cfg["host"], port=int(self.cfg.get("port", 502)))
        if not self.client.connect():
            raise RuntimeError(t("Không kết nối được Modbus {0}").format(self.cfg['host']))
        self.status = "Connected"

    def disconnect(self) -> None:
        if getattr(self, "client", None) is not None:
            self.client.close()
        self.status = "Disconnected"

    def _call(self, func, *args, **kwargs):
        """Call a pymodbus request with the station number ("unit" in the recipe, default 1).
        pymodbus named that argument `slave` up to 3.9 and `device_id` from 3.10 on."""
        unit = int(self.cfg.get("unit", 1))
        try:
            return func(*args, device_id=unit, **kwargs)
        except TypeError:
            return func(*args, slave=unit, **kwargs)

    def _addr(self, tag: str) -> int:
        tags = self.cfg.get("tags", {})
        if tag not in tags:
            raise KeyError(t("Tag '{0}' chưa được khai báo trong recipe").format(tag))
        return int(tags[tag])

    def read(self, tag: str):
        rr = self._call(self.client.read_coils, self._addr(tag), count=1)
        if rr.isError():
            raise RuntimeError(t("Modbus read lỗi: {0}").format(rr))
        return bool(rr.bits[0])

    def _write(self, tag: str, value) -> None:
        rr = self._call(self.client.write_coil, self._addr(tag), bool(value))
        if rr.isError():
            raise RuntimeError(t("Modbus write lỗi: {0}").format(rr))



class ModbusRtuPlc(ModbusTcpPlc):
    """Modbus RTU coils over a serial line (normally RS-485). Recipe config: {"provider": "modbus_rtu",
    "port": "COM3", "baudrate": 9600, "parity": "N", "stopbits": 1, "unit": 1, "tags": {...}}.
    Requires `pip install pymodbus pyserial`. Checked against a simulated slave, not a real PLC.
    """
    INTERFACE = "Modbus RTU (RS-485)"

    @property
    def address(self) -> str:
        return f"{self.cfg.get('port', '-')} @ {self.cfg.get('baudrate', 9600)}"

    def connect(self) -> None:
        from pymodbus.client import ModbusSerialClient   # lazy: optional dependency
        self.client = ModbusSerialClient(str(self.cfg["port"]), baudrate=int(self.cfg.get("baudrate", 9600)),
                                         bytesize=int(self.cfg.get("bytesize", 8)),
                                         parity=str(self.cfg.get("parity", "N")).upper()[:1],
                                         stopbits=int(self.cfg.get("stopbits", 1)),
                                         timeout=float(self.cfg.get("timeout_s", 1.0)), retries=1)
        if not self.client.connect():
            raise RuntimeError(t("Không mở được cổng serial {0}").format(self.cfg["port"]))
        self.status = "Connected"

PLC_PROVIDERS: dict[str, type[Plc]] = {}


def register_plc(name: str, cls: type[Plc]) -> None:
    PLC_PROVIDERS[name] = cls


register_plc("sim", SimPlc)
register_plc("modbus", ModbusTcpPlc)
register_plc("modbus_rtu", ModbusRtuPlc)