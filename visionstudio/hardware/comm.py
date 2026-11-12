"""Output communication channels: a pipeline sends its result as bytes through one of these.

Adapters (recipe `devices` entries with "kind": "comm"):
    serial    UART / RS-232 / RS-485 through any COM port (USB adapters included). Needs pyserial.
    tcp       raw TCP client            udp      UDP datagrams
    ethercat  cyclic process data to one EtherCAT slave through pysoem (SOEM master)
    sim       keeps what was sent in memory - for tests and for building a recipe without hardware

A new bus (CAN, PROFINET gateway, MQTT, ...) is one subclass of Channel plus register_comm().
SDKs are imported inside open(), so a PC without them still runs everything else.
"""
from __future__ import annotations

import socket
import threading
import time

from ..core.i18n import t


class Channel:
    INTERFACE = "?"
    SDK = "-"

    def __init__(self, dev_id: str, cfg: dict):
        self.id, self.cfg = dev_id, cfg
        self.name = cfg.get("name", dev_id)
        self.status, self.error = "Disconnected", ""
        self.sent_count, self.sent_bytes, self.last_send_ms = 0, 0, 0.0
        self.last_message = b""
        self._lock = threading.Lock()

    @property
    def address(self) -> str:
        return str(self.cfg.get("port", self.cfg.get("host", "-")))

    def open(self) -> None:
        self.status = "Connected"

    def close(self) -> None:
        self.status = "Disconnected"

    def _send(self, data: bytes) -> None:
        raise NotImplementedError

    def send(self, data: bytes) -> None:
        """Send one message. Raises when the channel is down, so the job becomes ERROR, not a silent loss."""
        if self.status != "Connected":
            raise RuntimeError(t("Kênh '{0}' chưa kết nối: {1}").format(self.id, self.error or self.status))
        t0 = time.perf_counter()
        with self._lock:
            self._send(bytes(data))
        self.last_send_ms = (time.perf_counter() - t0) * 1000.0
        self.sent_count += 1
        self.sent_bytes += len(data)
        self.last_message = bytes(data)


class SimChannel(Channel):
    """Loop-back channel: every message is kept in `log` (newest last, at most 1000)."""
    INTERFACE = "Simulated"

    def open(self) -> None:
        self.log: list[bytes] = []
        self.status = "Connected"

    def _send(self, data: bytes) -> None:
        self.log.append(data)
        del self.log[:-1000]


class SerialChannel(Channel):
    """UART / RS-232 / RS-485 through a serial port.

    Config: "port" ("COM3", "/dev/ttyUSB0", or a pyserial URL such as "loop://"), "baudrate",
    "bytesize" (5-8), "parity" (N/E/O/M/S), "stopbits" (1, 1.5, 2), "timeout_s", and
    "rs485": true to let the driver switch RTS around each frame (needed by RS-485 transceivers that
    do not switch direction by themselves; most USB-RS485 adapters do and need "rs485": false).
    The three standards differ in wiring and voltage, not in what the PC sends - pick the right
    adapter and the same settings as the receiving device.
    """
    INTERFACE = "UART / RS-232 / RS-485"
    SDK = "pyserial"

    def open(self) -> None:
        try:
            import serial                              # lazy: optional dependency
        except ImportError as exc:
            raise RuntimeError(t("Thiếu thư viện pyserial. Cài bằng: pip install pyserial")) from exc
        cfg = self.cfg
        self.port = serial.serial_for_url(
            str(cfg.get("port", "")), baudrate=int(cfg.get("baudrate", 9600)), bytesize=int(cfg.get("bytesize", 8)),
            parity=str(cfg.get("parity", "N")).upper()[:1], stopbits=float(cfg.get("stopbits", 1)),
            timeout=float(cfg.get("timeout_s", 1.0)), write_timeout=float(cfg.get("timeout_s", 1.0)))
        if cfg.get("rs485"):
            import serial.rs485
            self.port.rs485_mode = serial.rs485.RS485Settings(rts_level_for_tx=True, rts_level_for_rx=False)
        self.INTERFACE = "RS-485" if cfg.get("rs485") else "UART / RS-232"
        self.status = "Connected"

    def _send(self, data: bytes) -> None:
        self.port.write(data)
        self.port.flush()

    def read(self, size: int = 1024) -> bytes:
        """Read what the other side answered (up to `size` bytes, waits at most timeout_s)."""
        return self.port.read(size)

    def close(self) -> None:
        if getattr(self, "port", None) is not None:
            self.port.close()
            self.port = None
        self.status = "Disconnected"


class TcpChannel(Channel):
    """Raw TCP client. Config: "host", "port", "timeout_s". Reconnects once when the peer dropped the link."""
    INTERFACE = "TCP"

    @property
    def address(self) -> str:
        return f"{self.cfg.get('host', '-')}:{self.cfg.get('port', '-')}"

    def _connect(self) -> None:
        timeout = float(self.cfg.get("timeout_s", 2.0))
        self.sock = socket.create_connection((self.cfg["host"], int(self.cfg["port"])), timeout=timeout)
        self.sock.settimeout(timeout)

    def open(self) -> None:
        self._connect()
        self.status = "Connected"

    def _send(self, data: bytes) -> None:
        try:
            self.sock.sendall(data)
        except OSError:
            self.sock.close()
            self._connect()                            # the receiver restarted: one fresh attempt
            self.sock.sendall(data)

    def close(self) -> None:
        if getattr(self, "sock", None) is not None:
            self.sock.close()
            self.sock = None
        self.status = "Disconnected"


class UdpChannel(Channel):
    """UDP datagrams. Config: "host", "port". UDP has no connection: 'Connected' only means the socket exists."""
    INTERFACE = "UDP"
    address = TcpChannel.address

    def open(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target = (self.cfg["host"], int(self.cfg["port"]))
        self.status = "Connected"

    def _send(self, data: bytes) -> None:
        self.sock.sendto(data, self.target)

    close = TcpChannel.close


class EtherCatChannel(Channel):
    """EtherCAT master for ONE slave, through pysoem (SOEM).

    EtherCAT is cyclic process data, not a message bus: a background thread exchanges the process
    image every "cycle_ms", and send() copies the message into the slave's output bytes starting at
    "offset" (the message is cut or zero-padded to the size of the slave's output image).
    Config: "interface" (network adapter name as listed by pysoem.find_adapters()), "slave" (position
    on the bus, 0 = first), "offset", "cycle_ms".
    Needs `pip install pysoem`, a dedicated network port, and administrator rights (Npcap on Windows).
    NOTE: written against the pysoem 1.1 API; NOT verified on a real EtherCAT slave.
    """
    INTERFACE = "EtherCAT"
    SDK = "pysoem"

    @property
    def address(self) -> str:
        return f"{self.cfg.get('interface', '-')} / slave {self.cfg.get('slave', 0)}"

    def open(self) -> None:
        try:
            import pysoem                              # lazy: optional dependency
        except ImportError as exc:
            raise RuntimeError(t("Thiếu thư viện pysoem. Cài bằng: pip install pysoem")) from exc
        self.master = pysoem.Master()
        self.master.open(str(self.cfg.get("interface", "")))
        try:
            if self.master.config_init() <= 0:
                raise RuntimeError(t("Không tìm thấy slave EtherCAT nào trên '{0}'").format(self.cfg.get("interface", "")))
            index = int(self.cfg.get("slave", 0))
            if index >= len(self.master.slaves):
                raise RuntimeError(t("Bus chỉ có {0} slave, không có slave số {1}").format(len(self.master.slaves), index))
            self.master.config_map()
            self.slave = self.master.slaves[index]
            self.image = bytearray(len(self.slave.output))
            if not self.image:
                raise RuntimeError(t("Slave EtherCAT này không có dữ liệu đầu ra (output PDO)"))
            self.master.state = pysoem.OP_STATE
            self.master.send_processdata()             # slaves need valid outputs before they enter OP
            self.master.receive_processdata(2000)
            self.master.write_state()
            if self.master.state_check(pysoem.OP_STATE, 2_000_000) != pysoem.OP_STATE:
                raise RuntimeError(t("Slave EtherCAT không vào được trạng thái OP"))
        except Exception:
            self.master.close()
            raise
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._cycle, name=f"ecat-{self.id}", daemon=True)
        self._thread.start()
        self.status = "Connected"

    def _cycle(self) -> None:
        period = max(0.001, float(self.cfg.get("cycle_ms", 10)) / 1000.0)
        while not self._stop.wait(period):
            with self._lock:
                self.slave.output = bytes(self.image)
            self.master.send_processdata()
            if self.master.receive_processdata(2000) < self.master.expected_wkc:
                self.status, self.error = "Error", t("Mất trao đổi dữ liệu với slave (working counter thấp)")
            elif self.status == "Error":
                self.status, self.error = "Connected", ""

    def send(self, data: bytes) -> None:               # no bus I/O here: the cycle thread carries the image
        if self.status != "Connected":
            raise RuntimeError(t("Kênh '{0}' chưa kết nối: {1}").format(self.id, self.error or self.status))
        offset = int(self.cfg.get("offset", 0))
        room = max(0, len(self.image) - offset)
        chunk = bytes(data)[:room].ljust(room, b"\x00")
        with self._lock:
            self.image[offset:offset + room] = chunk
        self.sent_count += 1
        self.sent_bytes += min(len(data), room)
        self.last_message = bytes(data)[:room]

    def close(self) -> None:
        if getattr(self, "_thread", None) is not None:
            self._stop.set()
            self._thread.join(timeout=2)
            self._thread = None
        if getattr(self, "master", None) is not None:
            try:
                import pysoem
                self.master.state = pysoem.INIT_STATE
                self.master.write_state()
            finally:
                self.master.close()
                self.master = None
        self.status = "Disconnected"


COMM_PROVIDERS: dict[str, type[Channel]] = {}


def register_comm(name: str, cls: type[Channel]) -> None:
    COMM_PROVIDERS[name] = cls


register_comm("sim", SimChannel)
register_comm("serial", SerialChannel)
register_comm("tcp", TcpChannel)
register_comm("udp", UdpChannel)
register_comm("ethercat", EtherCatChannel)


def list_serial_ports() -> list[str]:
    """Names of the serial ports the operating system reports ([] when pyserial is missing)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [f"{p.device}" for p in sorted(list_ports.comports())]