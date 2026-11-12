"""Output channels (serial / TCP / UDP / EtherCAT / simulated), Modbus RTU and TCP, and the Data Output node.

No hardware is used: serial goes through pyserial's loop-back port, TCP / UDP / Modbus TCP through
sockets on this PC, Modbus RTU through a pseudo-terminal with a tiny fake slave (Linux / macOS only).
"""
from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time

import pytest

from visionstudio.core.executor import JobContext
from visionstudio.core.graph import Recipe
from visionstudio.core.node_base import REGISTRY
from visionstudio.core.schemas import InspectionResult
from visionstudio.hardware import comm as comm_mod
from visionstudio.hardware.manager import DeviceManager

from conftest import SIM_RECIPE


# ---- helpers ---------------------------------------------------------------------------------
class TcpSink:
    """A TCP server on this PC that records every byte it receives."""

    def __init__(self):
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.data, self.connections = b"", 0
        self._conn = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                self._conn, _ = self.server.accept()
            except OSError:
                return
            self.connections += 1
            while True:
                try:
                    chunk = self._conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                self.data += chunk

    def wait(self, n: int, timeout: float = 2.0) -> bytes:
        end = time.time() + timeout
        while len(self.data) < n and time.time() < end:
            time.sleep(0.01)
        return self.data

    def drop_client(self):
        self._conn.shutdown(socket.SHUT_RDWR)
        self._conn.close()

    def close(self):
        self.server.close()


def comm_ctx(devices_cfg: dict, job_no: int = 7, serial: str = "SN-0042"):
    devices = DeviceManager()
    devices.configure(devices_cfg)
    ctx = JobContext(devices, None, job_no=job_no)
    ctx.shared["serial"] = serial
    return ctx


def send(ctx, result, **params):
    node = REGISTRY["io.data_output"]("out1", {"device": "com1", **params})
    node.setup(ctx)
    node.process(ctx, result=result)
    return ctx.devices.comm("com1")


NG = InspectionResult("NG", ["MISSING_SCREW", "EXTRA_NUT"], {"count_screw": 1.0, "width": 12.34567})
OK = InspectionResult("OK", [], {"count_screw": 2.0})


# ---- channels --------------------------------------------------------------------------------
def test_sim_channel_counts_and_logs():
    ch = comm_mod.SimChannel("c", {})
    with pytest.raises(RuntimeError):
        ch.send(b"x")                                      # not opened yet
    ch.open()
    ch.send(b"abc")
    ch.send(b"de")
    assert ch.log == [b"abc", b"de"] and (ch.sent_count, ch.sent_bytes, ch.last_message) == (2, 5, b"de")


def test_serial_channel_loopback_and_settings():
    pytest.importorskip("serial")
    ch = comm_mod.SerialChannel("c", {"port": "loop://", "baudrate": 115200, "bytesize": 7, "parity": "e",
                                      "stopbits": 2, "timeout_s": 0.2})
    ch.open()
    assert (ch.port.baudrate, ch.port.bytesize, ch.port.parity, ch.port.stopbits) == (115200, 7, "E", 2)
    ch.send(b"OK,SN-1\r\n")
    assert ch.read(64) == b"OK,SN-1\r\n" and ch.status == "Connected" and ch.INTERFACE == "UART / RS-232"
    ch.close()
    assert ch.status == "Disconnected"
    ch.close()                                             # closing twice is harmless


def test_serial_channel_rs485_mode():
    pytest.importorskip("serial")
    ch = comm_mod.SerialChannel("c", {"port": "loop://", "rs485": True})
    ch.open()
    assert ch.port.rs485_mode is not None and ch.port.rs485_mode.rts_level_for_tx is True
    assert ch.INTERFACE == "RS-485"
    ch.send(b"\x01\x02")
    assert ch.read(2) == b"\x01\x02"
    ch.close()


@pytest.mark.skipif(os.name == "nt", reason="pseudo-terminals are not available on Windows")
def test_serial_channel_on_a_real_port_device():
    """A pty behaves like a COM port: the bytes written by the channel arrive on the other end."""
    import pty
    pytest.importorskip("serial")
    master, slave = pty.openpty()
    ch = comm_mod.SerialChannel("c", {"port": os.ttyname(slave), "baudrate": 9600})
    ch.open()
    ch.send(b"NG,SN-0042,MISSING_SCREW\r\n")
    assert os.read(master, 100) == b"NG,SN-0042,MISSING_SCREW\r\n"
    ch.close()
    os.close(master)
    os.close(slave)


def test_serial_port_listing_returns_names():
    assert all(isinstance(name, str) for name in comm_mod.list_serial_ports())


def test_tcp_channel_sends_and_reconnects():
    sink = TcpSink()
    ch = comm_mod.TcpChannel("c", {"host": "127.0.0.1", "port": sink.port})
    ch.open()
    ch.send(b"first\n")
    assert sink.wait(6) == b"first\n" and ch.address == f"127.0.0.1:{sink.port}"
    sink.drop_client()                                     # the receiver drops the connection
    time.sleep(0.1)
    for i in range(5):                                     # the loss shows up on a later send; it reconnects
        ch.send(b"again\n")
        time.sleep(0.05)
    assert sink.connections == 2 and sink.wait(12).endswith(b"again\n")
    ch.close()
    sink.close()


def test_tcp_channel_refused_connection_is_an_error():
    port = socket.create_server(("127.0.0.1", 0)).getsockname()[1]          # closed again at once
    with pytest.raises(OSError):
        comm_mod.TcpChannel("c", {"host": "127.0.0.1", "port": port, "timeout_s": 0.5}).open()


def test_udp_channel_datagrams():
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(2)
    ch = comm_mod.UdpChannel("c", {"host": "127.0.0.1", "port": receiver.getsockname()[1]})
    ch.open()
    ch.send(b"OK;1")
    ch.send(b"NG;2")
    assert [receiver.recv(100), receiver.recv(100)] == [b"OK;1", b"NG;2"]
    ch.close()
    receiver.close()


def test_ethercat_fails_cleanly_without_a_bus():
    """No EtherCAT slave here: the adapter must report why, not crash (missing pysoem, no rights, no slave)."""
    devices = DeviceManager()
    devices.configure({"e": {"kind": "comm", "provider": "ethercat", "interface": "no_such_adapter0"}})
    info = devices.info()[0]
    assert info["status"] == "Error" and info["error"] and info["interface"] == "EtherCAT"
    with pytest.raises(RuntimeError):
        devices.comm("e").send(b"x")
    devices.close()


def test_ethercat_send_maps_bytes_into_the_output_image():
    """The mapping logic alone, on a stand-in for the slave (the bus exchange itself needs hardware)."""
    ch = comm_mod.EtherCatChannel("e", {"offset": 2})
    ch.image, ch.status = bytearray(8), "Connected"
    ch.send(b"\x01\x02\x03")
    assert bytes(ch.image) == b"\x00\x00\x01\x02\x03\x00\x00\x00"
    ch.send(b"ABCDEFGHIJ")                                 # longer than the room left: cut, never overflows
    assert bytes(ch.image) == b"\x00\x00ABCDEF" and ch.last_message == b"ABCDEF" and ch.sent_count == 2
    ch.send(b"")                                           # empty message clears the mapped bytes
    assert bytes(ch.image) == bytes(8)


def test_custom_channel_adapter_can_be_registered():
    class Upper(comm_mod.Channel):
        INTERFACE = "Custom"

        def open(self):
            self.out, self.status = [], "Connected"

        def _send(self, data):
            self.out.append(data.upper())

    comm_mod.register_comm("upper_test", Upper)
    try:
        ctx = comm_ctx({"com1": {"kind": "comm", "provider": "upper_test"}})
        send(ctx, OK, template="{status}-{serial}", line_ending="none")
        assert ctx.devices.comm("com1").out == [b"OK-SN-0042"]
    finally:
        comm_mod.COMM_PROVIDERS.pop("upper_test")


# ---- device manager --------------------------------------------------------------------------
def test_manager_handles_comm_devices_next_to_cameras_and_plcs():
    devices = DeviceManager()
    devices.configure({"cam1": {"kind": "camera", "provider": "sim"}, "plc1": {"kind": "plc", "provider": "sim"},
                       "com1": {"kind": "comm", "provider": "sim", "name": "Máy in nhãn"},
                       "com2": {"kind": "comm", "provider": "serial", "port": "NO_SUCH_PORT_99"},
                       "com3": {"kind": "comm", "provider": "profinet_not_installed"}})
    rows = {r["id"]: r for r in devices.info()}
    assert rows["com1"]["status"] == "Connected" and rows["com1"]["type"] == "Comm" and rows["com1"]["name"] == "Máy in nhãn"
    assert rows["com2"]["status"] == "Error" and rows["com3"]["status"] == "No plugin"
    assert rows["cam1"]["status"] == rows["plc1"]["status"] == "Connected"
    devices.comm("com1").send(b"12345")
    assert "1" in devices.info()[2]["metric"] and "5" in devices.info()[2]["metric"]
    with pytest.raises(KeyError):
        devices.comm("nope")
    devices.close()
    assert devices.comms == {}


# ---- Data Output node ------------------------------------------------------------------------
def test_template_fields_line_ending_and_values():
    ctx = comm_ctx({"com1": {"kind": "comm", "provider": "sim"}})
    ch = send(ctx, NG, template="{status},{ok},{serial},{job_no},{job_id},{reasons},{count_screw},{width}")
    assert ch.log == [b"NG,0,SN-0042,7,JOB-00007,MISSING_SCREW;EXTRA_NUT,1.0,12.3457\r\n"]
    send(ctx, OK, template="{status}:{ok}", line_ending="LF")
    send(ctx, OK, template="{status}", line_ending="CR")
    send(ctx, OK, template="{status}", line_ending="none")
    assert ch.log[1:] == [b"OK:1\n", b"OK\r", b"OK"]
    assert ctx.shared["last_message"] == b"OK"


def test_template_escapes_for_framed_protocols():
    ctx = comm_ctx({"com1": {"kind": "comm", "provider": "sim"}})
    ch = send(ctx, OK, template=r"\x02{status}\t{serial}\x03", line_ending="none")
    assert ch.log == [b"\x02OK\tSN-0042\x03"]              # STX ... ETX
    send(ctx, OK, template=r"{status}\r\n{serial}\\", line_ending="none")
    assert ch.log[-1] == b"OK\r\nSN-0042\\"


def test_date_and_time_fields():
    ctx = comm_ctx({"com1": {"kind": "comm", "provider": "sim"}})
    text = send(ctx, OK, template="{date} {time}", line_ending="none").log[0].decode()
    assert time.strptime(text, "%Y-%m-%d %H:%M:%S")


def test_unknown_template_field_is_a_clear_error():
    ctx = comm_ctx({"com1": {"kind": "comm", "provider": "sim"}})
    with pytest.raises(ValueError) as err:
        send(ctx, OK, template="{status},{no_such_field}")
    assert "no_such_field" in str(err.value) and "serial" in str(err.value)
    assert ctx.devices.comm("com1").log == []


def test_json_and_csv_formats():
    ctx = comm_ctx({"com1": {"kind": "comm", "provider": "sim"}})
    ch = send(ctx, NG, format="json", line_ending="LF")
    data = json.loads(ch.log[0])
    assert data["status"] == "NG" and data["reasons"] == ["MISSING_SCREW", "EXTRA_NUT"] and data["job"] == 7
    assert data["serial"] == "SN-0042" and data["values"]["count_screw"] == 1.0 and ch.log[0].endswith(b"\n")
    row = send(ctx, NG, format="csv", line_ending="none").log[1].decode().split(",")
    assert row[2:] == ["7", "SN-0042", "NG", "MISSING_SCREW;EXTRA_NUT"] and len(row[0]) == 10


def test_encoding_of_non_ascii_text():
    ctx = comm_ctx({"com1": {"kind": "comm", "provider": "sim"}}, serial="Lô-số-7")
    ch = send(ctx, OK, template="{serial}", line_ending="none", encoding="utf-8")
    assert ch.log[0].decode("utf-8") == "Lô-số-7"
    send(ctx, OK, template="{serial}", line_ending="none", encoding="ascii")
    assert ch.log[1] == b"L?-s?-7"                         # replaced, never an exception in the middle of a job


def test_send_when_filters():
    ctx = comm_ctx({"com1": {"kind": "comm", "provider": "sim"}})
    error = InspectionResult("ERROR", ["NODE_FAILED:cam1"])
    sent = {}
    for when in ("always", "ok_only", "ng_only", "not_ok"):
        ch = ctx.devices.comm("com1")
        ch.log.clear()
        for result in (OK, NG, error):
            send(ctx, result, template="{status}", line_ending="none", send_when=when)
        sent[when] = [m.decode() for m in ch.log]
    assert sent == {"always": ["OK", "NG", "ERROR"], "ok_only": ["OK"], "ng_only": ["NG"], "not_ok": ["NG", "ERROR"]}


def test_channel_down_or_missing_fails_the_node():
    ctx = comm_ctx({"com1": {"kind": "comm", "provider": "serial", "port": "NO_SUCH_PORT_99"}})
    with pytest.raises(RuntimeError) as err:
        send(ctx, OK)
    assert "com1" in str(err.value)
    with pytest.raises(KeyError):
        send(comm_ctx({}), OK)


def test_pipeline_sends_one_message_per_job_over_serial_and_tcp(store):
    """The whole chain: simulated cameras -> detect -> count -> Data Output on two channels."""
    pytest.importorskip("serial")
    from visionstudio.core.engine import Engine
    sink = TcpSink()
    recipe = Recipe.load(SIM_RECIPE)
    recipe.devices["com1"] = {"kind": "comm", "provider": "serial", "port": "loop://", "timeout_s": 0.2}
    recipe.devices["com2"] = {"kind": "comm", "provider": "tcp", "host": "127.0.0.1", "port": sink.port}
    for dev, fmt in (("com1", "template"), ("com2", "json")):
        node = recipe.graph.add_node("io.data_output", params={"device": dev, "format": fmt, "line_ending": "LF",
                                                              "template": "{job_id};{status};{serial};{count_connector}"})
        recipe.graph.add_edge("cnt1", "result", node.id, "result")
    engine = Engine(store)
    engine.load_recipe(recipe)
    jobs = [engine.run_once() for _ in range(5)]
    assert all(j.result.status in ("OK", "NG") for j in jobs)
    lines = engine.devices.comm("com1").read(4096).decode().strip().split("\n")
    assert len(lines) == 5
    for job, line in zip(jobs, lines):
        job_id, status, serial, count = line.split(";")
        assert (job_id, status, serial) == (job.job_id, job.result.status, job.serial) and float(count) >= 3
    received = [json.loads(x) for x in sink.wait(200).decode().strip().split("\n")]
    assert [m["job"] for m in received] == [1, 2, 3, 4, 5] and received[0]["status"] == jobs[0].result.status

    engine.devices.comm("com2").close()                    # the cable is pulled
    broken = engine.run_once()
    assert broken.result.status == "ERROR" and broken.result.reasons[0].startswith("NODE_FAILED:data_output")
    engine.shutdown()
    sink.close()


# ---- Modbus ----------------------------------------------------------------------------------
def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


@pytest.mark.skipif(os.name == "nt", reason="pseudo-terminals are not available on Windows")
def test_modbus_rtu_handshake_frames_on_the_wire():
    """PLC Handshake over Modbus RTU: a fake slave on a pty checks every frame (station, function, CRC)."""
    import pty
    pytest.importorskip("pymodbus")
    pytest.importorskip("serial")
    master, slave = pty.openpty()
    frames, stop = [], threading.Event()

    def fake_slave():
        buffer = b""
        while not stop.is_set():
            try:
                buffer += os.read(master, 64)
            except OSError:
                return
            while len(buffer) >= 8:                        # "write single coil" request = 8 bytes
                frame, buffer = buffer[:8], buffer[8:]
                frames.append(frame)
                os.write(master, frame)                    # the correct reply to function 05 is an echo

    threading.Thread(target=fake_slave, daemon=True).start()
    devices = DeviceManager()
    devices.configure({"plc1": {"kind": "plc", "provider": "modbus_rtu", "port": os.ttyname(slave), "baudrate": 19200,
                                "unit": 17, "timeout_s": 1.0,
                                "tags": {"busy": 10, "done": 11, "result_ok": 12, "result_ng": 13}}})
    info = devices.info()[0]
    assert info["status"] == "Connected", info["error"]
    assert info["interface"] == "Modbus RTU (RS-485)" and "19200" in info["address"]
    ctx = JobContext(devices, None, job_no=1)
    REGISTRY["io.plc_handshake"]("plc", {"device": "plc1"}).process(ctx, result=InspectionResult("NG"))
    stop.set()
    devices.close()
    os.close(master)
    os.close(slave)
    decoded = [(f[0], f[1], struct.unpack(">H", f[2:4])[0], f[4:6] == b"\xff\x00") for f in frames]
    assert decoded == [(17, 5, 10, True), (17, 5, 12, False), (17, 5, 13, True), (17, 5, 11, True), (17, 5, 10, False)]
    assert all(f[6:8] == crc16(f[:6]) for f in frames)


def test_modbus_tcp_handshake_against_a_local_server():
    """PLC Handshake over Modbus TCP: a minimal server on this PC answers 'write single coil'."""
    pytest.importorskip("pymodbus")
    server = socket.create_server(("127.0.0.1", 0))
    writes = []

    def serve():
        conn, _ = server.accept()
        with conn:
            while True:
                header = conn.recv(7)
                if len(header) < 7:
                    return
                length = struct.unpack(">H", header[4:6])[0]
                pdu = conn.recv(length - 1)
                if pdu[0] == 5:
                    writes.append((header[6], struct.unpack(">H", pdu[1:3])[0], pdu[3:5] == b"\xff\x00"))
                conn.sendall(header + pdu)

    threading.Thread(target=serve, daemon=True).start()
    devices = DeviceManager()
    devices.configure({"plc1": {"kind": "plc", "provider": "modbus", "host": "127.0.0.1",
                                "port": server.getsockname()[1], "unit": 3,
                                "tags": {"busy": 0, "done": 1, "result_ok": 2, "result_ng": 3}}})
    assert devices.info()[0]["status"] == "Connected", devices.info()[0]["error"]
    ctx = JobContext(devices, None, job_no=1)
    REGISTRY["io.plc_handshake"]("plc", {"device": "plc1"}).process(ctx, result=InspectionResult("OK"))
    devices.close()
    server.close()
    assert writes == [(3, 0, True), (3, 2, True), (3, 3, False), (3, 1, True), (3, 0, False)]