"""DeviceManager: creates and owns the devices declared in a recipe."""
from __future__ import annotations

from ..core.i18n import t

from . import camera as cam_mod
from . import comm as comm_mod
from . import plc as plc_mod


class DeviceManager:
    def __init__(self):
        self.cameras: dict[str, cam_mod.Camera] = {}
        self.plcs: dict[str, plc_mod.Plc] = {}
        self.comms: dict[str, comm_mod.Channel] = {}

    def configure(self, devices_cfg: dict[str, dict]) -> None:
        self.close()
        kinds = {"camera": (cam_mod.CAMERA_PROVIDERS, self.cameras, cam_mod.Camera, "open"),
                 "plc": (plc_mod.PLC_PROVIDERS, self.plcs, plc_mod.Plc, "connect"),
                 "comm": (comm_mod.COMM_PROVIDERS, self.comms, comm_mod.Channel, "open")}
        for dev_id, cfg in devices_cfg.items():
            kind, provider = cfg.get("kind", "camera"), cfg.get("provider", "sim")
            table, target, base, opener = kinds.get(kind, kinds["camera"])
            if provider not in table:
                dev = base(dev_id, cfg)
                dev.status, dev.error = "No plugin", t("Chưa có adapter '{0}'").format(provider)
                target[dev_id] = dev
                continue
            dev = table[provider](dev_id, cfg)
            try:
                getattr(dev, opener)()
            except Exception as exc:       # missing SDK, wrong IP, port in use, ... -> keep the app alive
                dev.status, dev.error = "Error", f"{type(exc).__name__}: {exc}"
            target[dev_id] = dev

    def camera(self, dev_id: str) -> cam_mod.Camera:
        if dev_id not in self.cameras:
            raise KeyError(t("Camera '{0}' không có trong recipe").format(dev_id))
        return self.cameras[dev_id]

    def plc(self, dev_id: str) -> plc_mod.Plc:
        if dev_id not in self.plcs:
            raise KeyError(t("PLC '{0}' không có trong recipe").format(dev_id))
        return self.plcs[dev_id]

    def comm(self, dev_id: str) -> comm_mod.Channel:
        if dev_id not in self.comms:
            raise KeyError(t("Kênh truyền '{0}' không có trong recipe").format(dev_id))
        return self.comms[dev_id]

    def trigger(self) -> None:
        """Software trigger for one job. The simulated part advances once for all sim cameras."""
        if any(isinstance(c, cam_mod.SimCamera) for c in self.cameras.values()):
            cam_mod.SIM_WORLD.advance()

    def info(self) -> list[dict]:
        rows = []
        for c in self.cameras.values():
            rows.append({"id": c.id, "name": c.name, "type": "Camera", "interface": c.INTERFACE,
                         "address": c.address, "status": c.status, "error": c.error, "sdk": c.SDK,
                         "metric": f"FPS: {c.fps:.1f}"})
        for p in self.plcs.values():
            rows.append({"id": p.id, "name": p.name, "type": "PLC", "interface": p.INTERFACE,
                         "address": p.address, "status": p.status, "error": p.error, "sdk": p.SDK,
                         "metric": t("Ghi tag: {0:.2f} ms").format(p.last_write_ms)})
        for c in self.comms.values():
            rows.append({"id": c.id, "name": c.name, "type": "Comm", "interface": c.INTERFACE,
                         "address": c.address, "status": c.status, "error": c.error, "sdk": c.SDK,
                         "metric": t("Đã gửi: {0} bản tin, {1} byte").format(c.sent_count, c.sent_bytes)})
        return rows

    def close(self) -> None:
        for c in self.cameras.values():
            try:
                c.close()
            except Exception:
                pass
        for p in self.plcs.values():
            try:
                p.disconnect()
            except Exception:
                pass
        for c in self.comms.values():
            try:
                c.close()
            except Exception:
                pass
        self.cameras, self.plcs, self.comms = {}, {}, {}