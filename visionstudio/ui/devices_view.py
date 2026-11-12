"""Devices tab: status of every camera and PLC of the recipe; add, edit and remove devices."""
from __future__ import annotations

from ..core.i18n import t

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
                             QWidget)

from ..hardware.camera import CAMERA_PROVIDERS
from ..hardware.comm import COMM_PROVIDERS, list_serial_ports
from ..hardware.plc import PLC_PROVIDERS
from . import theme
from .context import AppContext
from .widgets import Card, ImageView, label, view_header

PROVIDER_HINT = {
    ("camera", "sim"): "Camera mô phỏng: vẽ sản phẩm giả, không cần phần cứng.",
    ("camera", "opencv"): "Webcam USB: nhập số thứ tự (0, 1, ...). Camera IP: nhập URL rtsp://... hoặc http://...",
    ("camera", "folder"): "Phát lại ảnh trong một thư mục (png, jpg, bmp) theo vòng lặp.",
    ("plc", "sim"): "PLC mô phỏng: ghi tag vào bộ nhớ, không cần phần cứng.",
    ("plc", "modbus"): "Modbus TCP (coil). Cần: pip install pymodbus. Tag mặc định: busy=0, done=1, result_ok=2, result_ng=3.",
    ("plc", "modbus_rtu"): "Modbus RTU (coil) qua cổng serial, thường là RS-485. Cần: pip install pymodbus pyserial. Thông số serial phải giống thiết bị nhận.",
    ("comm", "sim"): "Kênh mô phỏng: giữ bản tin trong bộ nhớ, không cần phần cứng.",
    ("comm", "serial"): "UART, RS-232 và RS-485 đều đi qua một cổng COM; khác nhau ở bộ chuyển đổi và cách đấu dây. Cần: pip install pyserial. Chỉ tick 'RS-485 điều khiển RTS' khi bộ chuyển đổi không tự đổi chiều.",
    ("comm", "tcp"): "TCP client: kết nối tới một máy đang lắng nghe ở địa chỉ IP và cổng đã nhập.",
    ("comm", "udp"): "UDP: gửi từng bản tin tới địa chỉ IP và cổng đã nhập, không có bắt tay kết nối.",
    ("comm", "ethercat"): "EtherCAT master cho một slave: bản tin được chép vào vùng dữ liệu đầu ra của slave. Cần: pip install pysoem, một cổng mạng riêng và quyền quản trị (Npcap trên Windows). Chưa được thử với slave thật.",
}
SERIAL_USERS = {("comm", "serial"), ("plc", "modbus_rtu")}
NET_USERS = {("plc", "modbus"), ("comm", "tcp"), ("comm", "udp")}


def ethercat_adapters() -> list[str]:
    """Network adapter names as pysoem sees them ([] when pysoem is not installed)."""
    try:
        import pysoem
        return [a.name for a in pysoem.find_adapters()]
    except Exception:
        return []


class DeviceDialog(QDialog):
    """Create or edit one entry of the recipe's `devices` block."""

    def __init__(self, existing_ids: list[str], dev_id: str = "", cfg: dict | None = None, parent=None,
                 live=None, engine_running: bool = False):
        super().__init__(parent)
        self.existing, self.editing = existing_ids, bool(dev_id)
        self.live, self.engine_running = live, engine_running   # camera currently opened by the engine
        cfg = dict(cfg or {})
        self.extra = cfg                       # keys this dialog does not edit are kept as they are
        self.setWindowTitle(t("Sửa thiết bị") if dev_id else t("Thêm thiết bị"))
        self.setMinimumWidth(460)
        col = QVBoxLayout(self)
        self.form = QFormLayout()
        self.id_edit = QLineEdit(dev_id)
        self.id_edit.setEnabled(not self.editing)
        self.id_edit.setPlaceholderText(t("ví dụ: cam1, plc1"))
        self.kind = QComboBox()
        self.kind.addItems(["camera", "plc", "comm"])
        self.kind.setCurrentText(cfg.get("kind", "camera"))
        self.kind.setEnabled(not self.editing)
        self.provider = QComboBox()
        self.name = QLineEdit(cfg.get("name", ""))
        self.view = QComboBox()
        self.view.addItems(["top", "side"])
        self.view.setCurrentText(cfg.get("view", "top"))
        self.source = QLineEdit(str(cfg.get("source", "0")))
        scan = QPushButton(t("Dò webcam"))
        scan.setToolTip(t("Thử mở webcam số 0 đến 5 và liệt kê những số mở được"))
        scan.clicked.connect(self._scan)
        self.source_row = QWidget()
        srow = QHBoxLayout(self.source_row)
        srow.setContentsMargins(0, 0, 0, 0)
        srow.addWidget(self.source, 1)
        srow.addWidget(scan)
        self.size_row = QWidget()
        zrow = QHBoxLayout(self.size_row)
        zrow.setContentsMargins(0, 0, 0, 0)
        self.width, self.height = QSpinBox(), QSpinBox()
        for box, key in ((self.width, "width"), (self.height, "height")):
            box.setRange(0, 10000)
            box.setSingleStep(160)
            box.setSpecialValueText("auto")
            box.setValue(int(cfg.get(key, 0) or 0))
            zrow.addWidget(box)
        self.path = QLineEdit(str(cfg.get("path", "")))
        browse = QPushButton("…")
        browse.setFixedWidth(36)
        browse.setStyleSheet("padding:6px 0;")
        browse.clicked.connect(self._browse)
        self.path_row = QWidget()
        row = QHBoxLayout(self.path_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        self.host = QLineEdit(str(cfg.get("host", "192.168.0.10")))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(cfg["port"]) if str(cfg.get("port", "")).isdigit() else 502)
        # serial line (UART / RS-232 / RS-485, Modbus RTU)
        self.serial_port = QComboBox()
        self.serial_port.setEditable(True)
        self.serial_port.addItems(list_serial_ports())
        self.serial_port.setEditText(str(cfg.get("port", "")) if not str(cfg.get("port", "")).isdigit() else "")
        self.serial_port.lineEdit().setPlaceholderText("COM3, /dev/ttyUSB0")
        rescan = QPushButton(t("Dò cổng"))
        rescan.clicked.connect(self._scan_ports)
        self.serial_row = QWidget()
        prow = QHBoxLayout(self.serial_row)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.addWidget(self.serial_port, 1)
        prow.addWidget(rescan)
        self.baud = QComboBox()
        self.baud.setEditable(True)
        self.baud.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baud.setEditText(str(cfg.get("baudrate", 9600)))
        self.frame_row = QWidget()
        frow = QHBoxLayout(self.frame_row)
        frow.setContentsMargins(0, 0, 0, 0)
        self.bytesize, self.parity, self.stopbits = QComboBox(), QComboBox(), QComboBox()
        self.bytesize.addItems(["8", "7", "6", "5"])
        self.parity.addItems(["N", "E", "O", "M", "S"])
        self.stopbits.addItems(["1", "1.5", "2"])
        self.bytesize.setCurrentText(str(cfg.get("bytesize", 8)))
        self.parity.setCurrentText(str(cfg.get("parity", "N")).upper()[:1])
        self.stopbits.setCurrentText(f"{float(cfg.get('stopbits', 1)):g}")
        for w in (self.bytesize, self.parity, self.stopbits):
            frow.addWidget(w)
        self.rs485 = QCheckBox(t("RS-485 điều khiển RTS"))
        self.rs485.setChecked(bool(cfg.get("rs485", False)))
        self.unit = QSpinBox()
        self.unit.setRange(0, 247)
        self.unit.setValue(int(cfg.get("unit", 1)))
        # EtherCAT
        self.ecat_if = QComboBox()
        self.ecat_if.setEditable(True)
        self.ecat_if.setEditText(str(cfg.get("interface", "")))
        self.ecat_slave, self.ecat_offset, self.ecat_cycle = QSpinBox(), QSpinBox(), QSpinBox()
        self.ecat_slave.setRange(0, 255)
        self.ecat_offset.setRange(0, 4095)
        self.ecat_cycle.setRange(1, 1000)
        self.ecat_slave.setValue(int(cfg.get("slave", 0)))
        self.ecat_offset.setValue(int(cfg.get("offset", 0)))
        self.ecat_cycle.setValue(int(cfg.get("cycle_ms", 10)))
        self.form.addRow(t("ID thiết bị"), self.id_edit)
        self.form.addRow(t("Loại"), self.kind)
        self.form.addRow("Adapter", self.provider)
        self.form.addRow(t("Tên hiển thị"), self.name)
        self.form.addRow(t("Góc nhìn mô phỏng"), self.view)
        self.form.addRow(t("Nguồn (index hoặc URL)"), self.source_row)
        self.form.addRow(t("Độ phân giải (rộng, cao)"), self.size_row)
        self.form.addRow(t("Thư mục ảnh"), self.path_row)
        self.form.addRow(t("Địa chỉ IP"), self.host)
        self.form.addRow(t("Cổng"), self.port)
        self.form.addRow(t("Cổng serial"), self.serial_row)
        self.form.addRow(t("Tốc độ baud"), self.baud)
        self.form.addRow(t("Bit dữ liệu, parity, bit dừng"), self.frame_row)
        self.form.addRow("", self.rs485)
        self.form.addRow(t("Địa chỉ trạm Modbus"), self.unit)
        self.form.addRow(t("Card mạng EtherCAT"), self.ecat_if)
        self.form.addRow(t("Vị trí slave (0 = đầu tiên)"), self.ecat_slave)
        self.form.addRow(t("Byte bắt đầu trong vùng đầu ra"), self.ecat_offset)
        self.form.addRow(t("Chu kỳ trao đổi (ms)"), self.ecat_cycle)
        col.addLayout(self.form)
        self.hint = label("", "dim", wrap=True)
        col.addWidget(self.hint)
        self.test_btn = QPushButton(t("Thử kết nối và chụp một ảnh"))
        self.test_btn.clicked.connect(self._test)
        col.addWidget(self.test_btn)
        self.preview = ImageView(t("Ảnh thử sẽ hiện ở đây"), fixed_h=200)
        col.addWidget(self.preview)
        self.test_msg = label("", wrap=True)
        col.addWidget(self.test_msg)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("Lưu"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("Hủy"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)
        self.kind.currentTextChanged.connect(self._fill_providers)
        self.provider.currentTextChanged.connect(self._update_fields)
        self._fill_providers(cfg.get("provider", ""))

    def _fill_providers(self, select: str = "") -> None:
        table = {"camera": CAMERA_PROVIDERS, "plc": PLC_PROVIDERS, "comm": COMM_PROVIDERS}[self.kind.currentText()]
        self.provider.blockSignals(True)
        self.provider.clear()
        self.provider.addItems(list(table))
        if select in table:
            self.provider.setCurrentText(select)
        self.provider.blockSignals(False)
        self._update_fields()

    def _update_fields(self) -> None:
        key = (self.kind.currentText(), self.provider.currentText())
        for w in (self.test_btn, self.test_msg):
            w.setVisible(key[0] in ("camera", "comm"))
        self.preview.setVisible(key[0] == "camera")
        self.test_btn.setText(t("Thử kết nối và chụp một ảnh") if key[0] == "camera" else t("Thử kết nối và gửi một bản tin"))
        if key == ("comm", "ethercat") and self.ecat_if.count() == 0:
            current = self.ecat_if.currentText()
            self.ecat_if.addItems(ethercat_adapters())
            self.ecat_if.setEditText(current)
        visible = {self.view: key == ("camera", "sim"), self.source_row: key == ("camera", "opencv"),
                   self.size_row: key == ("camera", "opencv"), self.path_row: key == ("camera", "folder"),
                   self.host: key in NET_USERS, self.port: key in NET_USERS,
                   self.serial_row: key in SERIAL_USERS, self.baud: key in SERIAL_USERS,
                   self.frame_row: key in SERIAL_USERS, self.rs485: key == ("comm", "serial"),
                   self.unit: key == ("plc", "modbus_rtu"), self.ecat_if: key == ("comm", "ethercat"),
                   self.ecat_slave: key == ("comm", "ethercat"), self.ecat_offset: key == ("comm", "ethercat"),
                   self.ecat_cycle: key == ("comm", "ethercat")}
        for widget, show in visible.items():
            self.form.setRowVisible(widget, show)
        self.hint.setText(t(PROVIDER_HINT[key]) if key in PROVIDER_HINT else (t("Adapter từ plugin: sửa các tham số khác trực tiếp trong file recipe.")))

    def _say(self, text: str, good: bool) -> None:
        self.test_msg.setText(text)
        self.test_msg.setStyleSheet(f"color:{theme.OK if good else theme.NG};")

    def _with_live_released(self, action) -> None:
        """Run `action` while the engine's own handle on this camera is closed, then reopen it."""
        if self.engine_running:
            self._say(t("Hãy bấm STOP trước khi thử thiết bị."), False)
            return
        was_open = self.live is not None and self.live.status == "Connected"
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if was_open:
                self.live.close()
            action()
        finally:
            if was_open:
                try:
                    self.live.open()
                except Exception:
                    pass
            QApplication.restoreOverrideCursor()

    def _scan(self) -> None:
        def run():
            found = []
            for index in range(6):
                cam = CAMERA_PROVIDERS["opencv"]("scan", {"source": index})
                try:
                    cam.open()
                    frame = cam.grab()
                    found.append(f"{index} ({frame.image.shape[1]}x{frame.image.shape[0]})")
                except Exception:
                    pass
                finally:
                    cam.close()
            if found:
                self.source.setText(found[0].split()[0])
                self._say(t("Webcam mở được: ") + ", ".join(found), True)
            else:
                self._say(t("Không tìm thấy webcam nào ở số 0 đến 5."), False)
        self._with_live_released(run)

    def _scan_ports(self) -> None:
        current = self.serial_port.currentText()
        ports = list_serial_ports()
        self.serial_port.clear()
        self.serial_port.addItems(ports)
        self.serial_port.setEditText(current or (ports[0] if ports else ""))
        self._say(t("Cổng serial tìm thấy: {0}").format(", ".join(ports)) if ports
                  else t("Không tìm thấy cổng serial nào (hoặc chưa cài pyserial)."), bool(ports))

    def _test_comm(self) -> None:
        def run():
            _id, cfg = self.result_config()
            channel = COMM_PROVIDERS[cfg["provider"]]("test", cfg)
            try:
                channel.open()
                channel.send(b"VISIONSTUDIO TEST\r\n")
                self._say(t("Đã mở kênh và gửi 19 byte: VISIONSTUDIO TEST<CR><LF>"), True)
            except Exception as exc:
                self._say(f"{type(exc).__name__}: {exc}", False)
            finally:
                try:
                    channel.close()
                except Exception:
                    pass
        self._with_live_released(run)

    def _test(self) -> None:
        if self.kind.currentText() == "comm":
            self._test_comm()
            return

        def run():
            _id, cfg = self.result_config()
            cam = CAMERA_PROVIDERS[cfg["provider"]]("test", cfg)
            try:
                cam.open()
                frame = cam.grab()
                self.preview.set_image(frame.image)
                self._say(t("Kết nối được. Kích thước ảnh: {0} x {1}").format(frame.image.shape[1], frame.image.shape[0]), True)
            except Exception as exc:
                self._say(f"{type(exc).__name__}: {exc}", False)
            finally:
                cam.close()
        self._with_live_released(run)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, t("Chọn thư mục ảnh"), self.path.text())
        if folder:
            self.path.setText(folder)

    def _accept(self) -> None:
        dev_id = self.id_edit.text().strip()
        if not dev_id or not dev_id.replace("_", "").isalnum():
            QMessageBox.warning(self, t("Thiết bị"), t("ID chỉ gồm chữ không dấu, số và dấu '_'."))
            return
        if not self.editing and dev_id in self.existing:
            QMessageBox.warning(self, t("Thiết bị"), t("ID '{0}' đã tồn tại.").format(dev_id))
            return
        self.accept()

    def result_config(self) -> tuple[str, dict]:
        kind, provider = self.kind.currentText(), self.provider.currentText()
        cfg = {k: v for k, v in self.extra.items()
               if k not in ("view", "source", "path", "host", "port", "width", "height", "baudrate", "bytesize",
                            "parity", "stopbits", "rs485", "unit", "interface", "slave", "offset", "cycle_ms")}
        cfg.update(kind=kind, provider=provider, name=self.name.text().strip() or self.id_edit.text().strip())
        if (kind, provider) == ("camera", "sim"):
            cfg["view"] = self.view.currentText()
        elif (kind, provider) == ("camera", "opencv"):
            src = self.source.text().strip()
            cfg["source"] = int(src) if src.isdigit() else src
            if self.width.value() and self.height.value():
                cfg.update(width=self.width.value(), height=self.height.value())
        elif (kind, provider) == ("camera", "folder"):
            cfg["path"] = self.path.text().strip()
        elif (kind, provider) in NET_USERS:
            cfg.update(host=self.host.text().strip(), port=self.port.value())
        elif (kind, provider) in SERIAL_USERS:
            baud = self.baud.currentText().strip()
            cfg.update(port=self.serial_port.currentText().strip(), baudrate=int(baud) if baud.isdigit() else 9600,
                       bytesize=int(self.bytesize.currentText()), parity=self.parity.currentText(),
                       stopbits=float(self.stopbits.currentText()))
            if (kind, provider) == ("comm", "serial"):
                cfg["rs485"] = self.rs485.isChecked()
            else:
                cfg["unit"] = self.unit.value()
        elif (kind, provider) == ("comm", "ethercat"):
            cfg.update(interface=self.ecat_if.currentText().strip(), slave=self.ecat_slave.value(),
                       offset=self.ecat_offset.value(), cycle_ms=self.ecat_cycle.value())
        if kind == "plc" and provider.startswith("modbus"):
            cfg.setdefault("tags", {"busy": 0, "done": 1, "result_ok": 2, "result_ng": 3})
        return self.id_edit.text().strip(), cfg


class DevicesView(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setObjectName("view")
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 24, 24, 24)
        self.add_btn = QPushButton(t("Thêm thiết bị"))
        self.add_btn.clicked.connect(self._add)
        self.scan_btn = QPushButton(t("Kết nối lại thiết bị"))
        self.scan_btn.setObjectName("primary")
        self.scan_btn.clicked.connect(lambda _checked=False: self._reconnect())
        col.addWidget(view_header(t("Quản lý phần cứng"), t("Camera và PLC khai báo trong recipe, kết nối qua adapter"),
                                  self.add_btn, self.scan_btn))
        self.grid = QGridLayout()
        self.grid.setSpacing(18)
        col.addLayout(self.grid)
        col.addSpacing(14)
        col.addWidget(label(t("Adapter camera: {0}   ·   Adapter PLC: {1}   ·   Kênh truyền: {2}   ·   Thay đổi thiết bị được lưu khi bấm 'Lưu Recipe' ở tab Studio.").format(', '.join(CAMERA_PROVIDERS), ', '.join(PLC_PROVIDERS), ', '.join(COMM_PROVIDERS)), "dim", wrap=True))
        col.addStretch(1)
        self.cards: dict[str, dict[str, QLabel]] = {}
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        ctx.role_changed.connect(lambda _r: self.rebuild() if self.isVisible() else self._apply_role())
        ctx.recipe_changed.connect(lambda: self.isVisible() and self.rebuild())
        self._apply_role()

    def _apply_role(self) -> bool:
        can = self.ctx.can("devices.manage")
        self.add_btn.setEnabled(can)
        self.scan_btn.setEnabled(can)
        return can

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.rebuild()
        self.timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.timer.stop()

    # ---- actions -------------------------------------------------------------------------
    def _reconnect(self, audit: bool = True) -> None:
        engine = self.ctx.engine
        was_running = engine.running
        engine.stop()
        engine.devices.configure(engine.recipe.devices)
        engine.update_graph(engine.recipe.graph)      # nodes re-open their devices
        if audit:
            self.ctx.audit("RECONNECT_DEVICES")
        else:
            self.ctx.set_dirty()                  # a device was added, edited or removed
        if was_running:
            engine.start()
        self.rebuild()

    def _add(self) -> None:
        devices = self.ctx.engine.recipe.devices
        dlg = DeviceDialog(list(devices), parent=self, engine_running=self.ctx.engine.running)
        if dlg.exec():
            dev_id, cfg = dlg.result_config()
            devices[dev_id] = cfg
            self.ctx.audit("ADD_DEVICE", f"{dev_id}: {cfg['kind']}/{cfg['provider']}")
            self._reconnect(audit=False)

    def _edit(self, dev_id: str) -> None:
        devices = self.ctx.engine.recipe.devices
        dlg = DeviceDialog(list(devices), dev_id, devices[dev_id], parent=self,
                           live=self.ctx.engine.devices.cameras.get(dev_id) or self.ctx.engine.devices.comms.get(dev_id),
                           engine_running=self.ctx.engine.running)
        if dlg.exec():
            _id, cfg = dlg.result_config()
            devices[dev_id] = cfg
            self.ctx.audit("EDIT_DEVICE", f"{dev_id}: {cfg['kind']}/{cfg['provider']} {cfg.get('source', cfg.get('path', cfg.get('host', '')))}")
            self._reconnect(audit=False)

    def _remove(self, dev_id: str) -> None:
        used = [n.id for n in self.ctx.engine.recipe.graph.nodes.values() if n.params.get("device") == dev_id]
        text = t("Xóa thiết bị '{0}' khỏi recipe?").format(dev_id)
        if used:
            text += t("\nNode đang dùng thiết bị này: {0}. Các node đó sẽ báo ERROR.").format(', '.join(used))
        if QMessageBox.question(self, t("Xóa thiết bị"), text) != QMessageBox.StandardButton.Yes:
            return
        del self.ctx.engine.recipe.devices[dev_id]
        self.ctx.audit("REMOVE_DEVICE", dev_id)
        self._reconnect(audit=False)

    # ---- display -------------------------------------------------------------------------
    def rebuild(self) -> None:
        can = self._apply_role()
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        self.cards = {}
        for i, dev in enumerate(self.ctx.engine.devices.info()):
            card = Card()
            top = QHBoxLayout()
            status = QLabel()
            top.addWidget(status)
            top.addStretch(1)
            top.addWidget(label(dev["interface"], "dim"))
            card.box.addLayout(top)
            name = QLabel(f"{dev['name']}")
            name.setStyleSheet("font-size:14px; font-weight:bold;")
            card.box.addWidget(name)
            addr = label(f"ID: {dev['id']} | {dev['type']} | {dev['address']} | SDK: {dev['sdk']}", "dim", wrap=True)
            addr.setStyleSheet(f"font-family:{theme.MONO}; color:{theme.TEXT_DIM};")
            card.box.addWidget(addr)
            metric = QLabel()
            metric.setWordWrap(True)
            metric.setStyleSheet(f"font-family:{theme.MONO}; color:{theme.TEXT_DIM}; border-top:1px solid {theme.BORDER}; padding-top:8px;")
            card.box.addWidget(metric)
            btns = QHBoxLayout()
            edit = QPushButton(t("Sửa"))
            edit.clicked.connect(lambda _c, d=dev["id"]: self._edit(d))
            remove = QPushButton(t("Xóa"))
            remove.clicked.connect(lambda _c, d=dev["id"]: self._remove(d))
            for b in (edit, remove):
                b.setEnabled(can)
                btns.addWidget(b)
            btns.addStretch(1)
            card.box.addLayout(btns)
            self.grid.addWidget(card, i // 3, i % 3)
            self.cards[dev["id"]] = {"status": status, "metric": metric}
        self.refresh()

    def refresh(self) -> None:
        for dev in self.ctx.engine.devices.info():
            widgets = self.cards.get(dev["id"])
            if not widgets:
                continue
            good = dev["status"] == "Connected"
            color, bg = (theme.OK, theme.OK_BG) if good else (theme.NG, theme.NG_BG)
            widgets["status"].setText(dev["status"])
            widgets["status"].setToolTip(dev["error"])
            widgets["status"].setStyleSheet(f"color:{color}; background:{bg}; border:1px solid {color};"
                                            "border-radius:4px; padding:3px 9px; font-weight:bold;")
            widgets["metric"].setText(dev["metric"] if good else (dev["error"] or dev["status"]))