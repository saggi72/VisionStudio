"""Every tab of the desktop UI, driven without a screen (see the `window` fixture in conftest.py)."""
from __future__ import annotations

import csv

import pytest
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QDropEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QCheckBox, QFileDialog, QInputDialog, QTabWidget

from visionstudio.core import i18n
from visionstudio.core.graph import Recipe
from visionstudio.ui import theme
from visionstudio.ui.devices_view import DeviceDialog
from visionstudio.ui.node_editor import MIME_NODE, EdgeItem
from visionstudio.ui.users_view import LoginDialog, UserDialog

from conftest import FOLDER_RECIPE


def graph_state(scene):
    return sorted(scene.graph.nodes), sorted((e.src, e.dst) for e in scene.graph.edges)


def accounts_page(window):
    tabs = window.views["settings"].findChild(QTabWidget)
    return tabs.widget(1)


# ---- main window -----------------------------------------------------------------------------
def test_tabs_switch_and_footer(window, pump):
    assert list(window.tab_buttons) == ["studio", "operator", "retrain", "devices", "history", "reports", "settings"]
    for index, key in enumerate(window.tab_buttons):
        window.tab_buttons[key].click()
        pump(0.05)
        assert window.stack.currentIndex() == index and window.stack.currentWidget() is window.views[key]
    assert "STOPPED" in window.foot_left.text() and "3/3" in window.foot_left.text()
    assert "ASSY-CONN-01" in window.recipe_label.text()


def test_start_stop_button_runs_jobs(window, pump):
    window.ctx.store.set("interval_ms", 20)
    window.run_btn.click()
    pump(0.6)
    assert window.ctx.engine.running and "STOP" in window.run_btn.text() and "RUNNING" in window.foot_left.text()
    assert "Cycle Time" in window.foot_right.text()
    assert window.tab_buttons["operator"].text().endswith(("[OK]", "[NG]"))
    window.run_btn.click()
    pump(0.1)
    assert not window.ctx.engine.running and "START" in window.run_btn.text()
    actions = [r[2] for r in window.ctx.store.audit_rows(10)]
    assert "ENGINE_START" in actions and "ENGINE_STOP" in actions


def test_theme_switch_rebuilds_and_keeps_session(window, qapp, pump):
    window.tab_buttons["devices"].click()
    window.theme_btn.click()
    pump(0.3)
    new = qapp.property("main_window")
    assert new is not window and theme.mode == "light" and theme.TEXT == theme.PALETTES["light"]["TEXT"]
    assert new.ctx.user["username"] == "dev" and new.stack.currentIndex() == 3
    assert len(new.ctx.engine.listeners) == 1 and new.ctx.store.get("theme") == "light"
    assert theme.PALETTES["light"]["PANEL"] in qapp.styleSheet()
    new.theme_btn.click()
    pump(0.3)
    assert theme.mode == "dark" and qapp.property("main_window") is not new


def test_language_switch_translates_ui(window, qapp, pump):
    assert window.tab_buttons["devices"].text() == "Thiết bị"
    window.lang_btn.click()
    pump(0.3)
    new = qapp.property("main_window")
    assert i18n.language() == "en" and new.tab_buttons["devices"].text() == "Devices"
    assert new.views["studio"].save_btn.text() == "Save Recipe" and new.lang_btn.text() == "VI"
    assert new.ctx.store.get("language") == "en"
    new.views["studio"].scene.node_items["det1"].setSelected(True)
    pump(0.05)
    labels = [new.views["studio"].form.itemAt(i).widget().text() for i in range(new.views["studio"].form.count())
              if hasattr(new.views["studio"].form.itemAt(i).widget(), "text")]
    assert "Confidence threshold" in labels and "Ngưỡng tin cậy" not in labels


def test_light_and_dark_text_contrast():
    """The rule 'dark background -> light text, light background -> dark text' as numbers (WCAG ratio)."""
    def luminance(hex_color):
        rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    def contrast(a, b):
        hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    for mode, pal in theme.PALETTES.items():
        for bg in ("BG", "BG_CANVAS", "PANEL", "PANEL_HI", "HEADER", "INPUT_BG", "NODE_FILL", "NODE_HEAD"):
            for fg in ("TEXT", "TEXT_DIM"):
                assert contrast(pal[fg], pal[bg]) >= 4.5, (mode, fg, bg)
        for fg, bg in (("OK", "OK_BG"), ("NG", "NG_BG"), ("WARN", "WARN_BG"), ("OK", "PANEL"), ("NG", "PANEL"),
                       ("WARN", "PANEL"), ("INFO", "PANEL"), ("TEXT_STRONG", "SELECT")):
            assert contrast(pal[fg], pal[bg]) >= 4.5, (mode, fg, bg)
        assert contrast(theme.ON_COLOR, pal["ACCENT"]) >= 4.5, mode
    for button in (theme.BTN_START, theme.BTN_STOP, theme.BTN_AMBER):
        assert contrast(theme.ON_COLOR, button) >= 4.5
    assert contrast(theme.IMAGE_TEXT, theme.IMAGE_BG) >= 7


# ---- accounts and permissions ------------------------------------------------------------------
def test_guest_is_read_only_and_login_unlocks(window, pump):
    ctx, studio = window.ctx, window.views["studio"]
    ctx.logout()
    pump(0.05)
    assert ctx.role == "Operator" and not ctx.logged_in
    assert studio.lock_bar.isVisible() and not studio.save_btn.isEnabled() and not studio.tree.isEnabled()
    assert studio.scene.read_only and window.run_btn.isEnabled()                 # Operator may still run
    assert not window.views["devices"].add_btn.isEnabled()
    dialog = LoginDialog(ctx, window)
    dialog.user.setEditText("engineer")
    dialog.password.setText("wrong")
    dialog._try()
    assert not ctx.logged_in and dialog.error.text()
    dialog.password.setText("1111")
    dialog._try()
    pump(0.05)
    assert ctx.user["username"] == "engineer" and not studio.lock_bar.isVisible() and studio.save_btn.isEnabled()
    assert not accounts_page(window).manage_buttons[0].isEnabled()               # Engineer cannot manage accounts
    assert [r[2] for r in ctx.store.audit_rows(3)] == ["LOGIN", "LOGIN_FAILED", "LOGOUT"]


def test_developer_previews_other_roles(window, pump):
    ctx, studio = window.ctx, window.views["studio"]
    assert [a.text() for a in window.role_menu.actions()][-1].startswith("Thử quyền")
    ctx.preview_as("Operator")
    pump(0.05)
    assert ctx.role == "Operator" and studio.scene.read_only and "Operator" in window.role_btn.text()
    ctx.preview_as("Developer")
    pump(0.05)
    assert ctx.role == "Developer" and not studio.scene.read_only
    ctx.login("engineer", "1111")
    ctx.preview_as("Admin")                                                      # only a Developer may preview
    assert ctx.role == "Engineer"


def test_create_edit_lock_delete_account(window, pump, monkeypatch):
    ctx, page = window.ctx, accounts_page(window)
    dialog = UserDialog(ctx, parent=window)
    dialog.username.setText("QC_Lan")
    dialog.full_name.setText("Trần Thị Lan")
    dialog.role.setCurrentText("Engineer")
    dialog.pw1.setText("lan12345")
    dialog.pw2.setText("different")
    dialog._save()
    assert dialog.error.text() and ctx.auth.user("qc_lan") is None               # passwords differ
    dialog.pw2.setText("lan12345")
    dialog._save()
    assert ctx.auth.verify("qc_lan", "lan12345")["role"] == "Engineer"
    ctx.rules_changed()
    pump(0.05)
    row = [page.user_table.item(r, 0).text() for r in range(page.user_table.rowCount())].index("qc_lan")
    page.user_table.selectRow(row)

    edit = UserDialog(ctx, ctx.auth.user("qc_lan"), parent=window)
    edit.role.setCurrentText("Operator")
    edit._save()
    assert ctx.auth.user("qc_lan")["role"] == "Operator"

    page._toggle_active()
    pump(0.05)
    assert ctx.auth.user("qc_lan")["active"] == 0 and ctx.auth.verify("qc_lan", "lan12345") is None
    page.user_table.selectRow(row)
    answers = iter([("newpass1", True), ("newpass1", True)])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: next(answers)))
    page._reset_password()
    page.user_table.selectRow(row)
    page._toggle_active()
    pump(0.05)
    assert ctx.auth.verify("qc_lan", "newpass1") is not None
    page.user_table.selectRow(row)
    page._delete()
    pump(0.05)
    assert ctx.auth.user("qc_lan") is None
    actions = [r[2] for r in ctx.store.audit_rows(20)]
    for expected in ("CREATE_USER", "UPDATE_USER", "LOCK_USER", "RESET_PASSWORD", "UNLOCK_USER", "DELETE_USER"):
        assert expected in actions


def test_cannot_lock_or_delete_own_account(window, pump):
    page = accounts_page(window)
    row = [page.user_table.item(r, 0).text() for r in range(page.user_table.rowCount())].index("dev")
    page.user_table.selectRow(row)
    page._toggle_active()
    page._delete()
    pump(0.05)
    assert window.ctx.auth.user("dev")["active"] == 1


def test_rule_matrix_checkbox_changes_permissions(window, pump):
    ctx, page = window.ctx, accounts_page(window)
    roles = list(ctx.auth.roles())
    operator_col, developer_col = 1 + roles.index("Operator"), 1 + roles.index("Developer")
    assert not page.matrix.cellWidget(0, developer_col).findChild(QCheckBox).isEnabled()   # Developer is fixed
    page.matrix.cellWidget(0, operator_col).findChild(QCheckBox).setChecked(False)          # "engine.run"
    pump(0.1)
    assert "engine.run" not in ctx.auth.role_perms("Operator")
    ctx.logout()
    pump(0.05)
    assert not window.run_btn.isEnabled()
    window.run_btn.click()                                                       # ignored without the permission
    assert not ctx.engine.running
    ctx.login("dev", "dev1234")
    pump(0.05)
    assert window.run_btn.isEnabled()


def test_add_and_delete_custom_role(window, pump, monkeypatch):
    ctx, page = window.ctx, accounts_page(window)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("QC_Leader", True)))
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Engineer", True)))
    page._add_role()
    pump(0.1)
    assert ctx.auth.role_perms("QC_Leader") == ctx.auth.role_perms("Engineer")
    assert page.matrix.columnCount() == 6
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("QC_Leader", True)))
    page._delete_role()
    pump(0.1)
    assert "QC_Leader" not in ctx.auth.roles() and page.matrix.columnCount() == 5


def test_change_own_password(window, pump, monkeypatch):
    answers = iter([("dev1234", True), ("brandnew", True), ("brandnew", True)])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: next(answers)))
    accounts_page(window)._change_own_password()
    pump(0.05)
    assert window.ctx.auth.verify("dev", "brandnew") and window.ctx.auth.verify("dev", "dev1234") is None


# ---- studio ----------------------------------------------------------------------------------
@pytest.fixture
def studio(window, pump):
    view = window.views["studio"]
    view.fit_view()
    pump(0.05)
    return view


def mouse_drag(view, a: QPoint, b: QPoint, pump, button=Qt.MouseButton.LeftButton):
    vp = view.viewport()
    QTest.mousePress(vp, button, Qt.KeyboardModifier.NoModifier, a)
    pump(0.02)
    for i in range(1, 6):
        QTest.mouseMove(vp, QPoint(a.x() + (b.x() - a.x()) * i // 5, a.y() + (b.y() - a.y()) * i // 5))
        pump(0.01)
    QTest.mouseRelease(vp, button, Qt.KeyboardModifier.NoModifier, b)
    pump(0.03)


def port_pos(studio, node_id, name, output):
    item = studio.scene.node_items[node_id]
    return studio.view.mapFromScene((item.out_ports if output else item.in_ports)[name].scenePos())


def body_pos(studio, node_id):
    return studio.view.mapFromScene(studio.scene.node_items[node_id].scenePos() + QPointF(100, 14))


def drop_node(studio, type_id, point: QPoint, pump):
    mime = QMimeData()
    mime.setData(MIME_NODE, type_id.encode())
    studio.view.dropEvent(QDropEvent(QPointF(point), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                                     Qt.KeyboardModifier.NoModifier))
    pump(0.03)


def test_palette_lists_every_node_and_filters(studio):
    from visionstudio.core.node_base import REGISTRY
    count = lambda: sum(studio.tree.topLevelItem(i).childCount() for i in range(studio.tree.topLevelItemCount()))
    assert count() == len(REGISTRY)
    studio.search.setText("yolo")
    assert count() == 2
    studio.search.setText("")


def test_add_node_by_drop_and_double_click(studio, pump):
    drop_node(studio, "classic.threshold", QPoint(300, 80), pump)
    assert "threshold1" in studio.scene.graph.nodes and studio.selected == "threshold1"
    assert studio.ctx.dirty and "lỗi cấu hình" in studio.status.text()           # its input is not wired yet
    item = next(studio.tree.topLevelItem(i).child(j) for i in range(studio.tree.topLevelItemCount())
                for j in range(studio.tree.topLevelItem(i).childCount())
                if studio.tree.topLevelItem(i).child(j).data(0, Qt.ItemDataRole.UserRole) == "classic.canny")
    studio._add_from_palette(item)
    assert "canny1" in studio.scene.graph.nodes
    assert studio.scene.node_items["threshold1"].pos().x() % 10 == 0             # snapped to the grid


def test_connect_ports_with_the_mouse_both_directions(studio, pump):
    drop_node(studio, "classic.gaussian_blur", QPoint(250, 60), pump)
    drop_node(studio, "classic.threshold", QPoint(520, 60), pump)
    studio.fit_view()
    pump(0.05)
    mouse_drag(studio.view, port_pos(studio, "cam1", "frame", True), port_pos(studio, "gaussian_blur1", "image", False), pump)
    assert ("cam1", "gaussian_blur1") in graph_state(studio.scene)[1]
    mouse_drag(studio.view, port_pos(studio, "threshold1", "image", False), port_pos(studio, "gaussian_blur1", "image", True), pump)
    assert ("gaussian_blur1", "threshold1") in graph_state(studio.scene)[1]      # dragged input -> output
    before = graph_state(studio.scene)
    mouse_drag(studio.view, port_pos(studio, "cam1", "frame", True), port_pos(studio, "cnt1", "detections", False), pump)
    assert graph_state(studio.scene) == before and "Sai kiểu" in studio.status.text()
    mouse_drag(studio.view, port_pos(studio, "threshold1", "mask", True), port_pos(studio, "gaussian_blur1", "image", False), pump)
    assert graph_state(studio.scene) == before and "vòng lặp" in studio.status.text()


def test_move_select_delete_and_undo_redo(studio, pump):
    start = studio.scene.node_items["cam1"].pos()
    mouse_drag(studio.view, body_pos(studio, "cam1"), body_pos(studio, "cam1") + QPoint(40, 30), pump)
    moved = studio.scene.node_items["cam1"].pos()
    assert moved != start and studio.undo_btn.isEnabled()
    studio.undo_btn.click()
    assert studio.scene.node_items["cam1"].pos() == start
    studio.redo_btn.click()
    assert studio.scene.node_items["cam1"].pos() == moved

    original = graph_state(studio.scene)
    edge = next(e for e in studio.scene.edge_items if e.edge.dst == "plc1")
    QTest.mouseClick(studio.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     studio.view.mapFromScene(edge.path().pointAtPercent(0.5)))
    pump(0.03)
    assert isinstance(studio.scene.selectedItems()[0], EdgeItem) and studio.del_btn.isEnabled()
    QTest.keyClick(studio.view, Qt.Key.Key_Delete)
    assert ("cnt1", "plc1") not in graph_state(studio.scene)[1]
    QTest.keyClick(studio.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert graph_state(studio.scene) == original

    QTest.mouseClick(studio.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, body_pos(studio, "det1"))
    pump(0.03)
    assert studio.selected == "det1"
    studio.del_btn.click()
    nodes, edges = graph_state(studio.scene)
    assert "det1" not in nodes and all("det1" not in e for e in edges)
    QTest.keyClick(studio.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert graph_state(studio.scene) == original
    QTest.keyClick(studio.view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert "det1" not in graph_state(studio.scene)[0]


def test_copy_paste_duplicate_select_all_disconnect(studio, pump):
    scene = studio.scene
    scene.node_items["det1"].setSelected(True)
    scene.node_items["cnt1"].setSelected(True)
    QTest.keyClick(studio.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(studio.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    nodes, edges = graph_state(scene)
    assert {"blob_detect1", "count_by_class1"} <= set(nodes) and ("blob_detect1", "count_by_class1") in edges
    assert scene.graph.nodes["count_by_class1"].params == scene.graph.nodes["cnt1"].params
    scene.clearSelection()
    scene.node_items["cam1"].setSelected(True)
    QTest.keyClick(studio.view, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert "camera1" in scene.graph.nodes
    QTest.keyClick(studio.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert len(scene.selected_nodes()) == len(scene.graph.nodes) == 9
    scene.disconnect_node("sync1")
    assert all("sync1" not in e for e in graph_state(scene)[1])


def test_auto_layout_zoom_pan_fit(studio, pump):
    studio.layout_btn.click()
    xs = {n: i.pos().x() for n, i in studio.scene.node_items.items()}
    assert xs["cam1"] == xs["cam2"] < xs["sync1"] < xs["det1"] < xs["cnt1"] < xs["plc1"]
    assert studio.scene.node_items["cam1"].pos().y() != studio.scene.node_items["cam2"].pos().y()
    from PyQt6.QtGui import QWheelEvent
    zoom = studio.view.transform().m11()
    studio.view.wheelEvent(QWheelEvent(QPointF(300, 200), QPointF(300, 200), QPoint(0, 0), QPoint(0, 120),
                                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                       Qt.ScrollPhase.NoScrollPhase, False))
    assert studio.view.transform().m11() > zoom
    h = studio.view.horizontalScrollBar().value()
    mouse_drag(studio.view, QPoint(400, 300), QPoint(300, 260), pump, Qt.MouseButton.MiddleButton)
    assert studio.view.horizontalScrollBar().value() == h + 100
    QTest.keyClick(studio.view, Qt.Key.Key_F)
    assert studio.view.transform().m11() <= 1.0


def test_inspector_edits_params_and_engine_uses_them(studio, pump):
    studio.scene.node_items["cnt1"].setSelected(True)
    pump(0.03)
    assert studio.selected == "cnt1" and "cnt1" in studio.id_label.text() and studio.node_doc.text()
    inst = studio.scene.graph.nodes["cnt1"]
    studio._set_param(inst, "expect", "connector=99")
    job = studio.ctx.engine.run_once()
    assert job.result.status == "NG" and "MISSING_CONNECTOR" in job.result.reasons
    studio._rename(inst, "Đếm linh kiện")
    assert inst.title == "Đếm linh kiện" and studio.ctx.dirty
    studio.scene.undo()
    studio.scene.undo()
    assert studio.scene.graph.nodes["cnt1"].params["expect"] == "connector=4,screw=2"
    assert studio.ctx.engine.recipe.graph is studio.scene.graph                   # undo swapped the graph object
    assert "EDIT_PARAM" in [r[2] for r in studio.ctx.store.audit_rows(10)]


def test_live_probe_and_heatmap(studio, pump):
    studio.ctx.store.set("interval_ms", 20)
    studio.scene.node_items["det1"].setSelected(True)
    studio.ctx.engine.start()
    pump(0.5)
    studio.ctx.engine.stop()
    assert studio.probe.pixmap() is not None and not studio.probe.pixmap().isNull()
    assert "ms" in studio.time_label.text()
    item = studio.scene.node_items["det1"]
    assert item.exec_ms is not None and 0 < item.score <= 100
    assert abs(sum(i.score for i in studio.scene.node_items.values()) - 100) < 0.01
    studio.heat_btn.click()
    assert not item.heatmap and "OFF" in studio.heat_btn.text()


def test_new_save_open_recipe_and_dirty_flag(studio, pump, monkeypatch, tmp_path):
    import visionstudio.ui.studio_view as sv

    class Info:
        def __init__(self, *a, **k): pass
        def exec(self): return True
        def values(self): return "BRACKET-A12", "Kiểm tra bracket"

    monkeypatch.setattr(sv, "RecipeInfoDialog", Info)
    ctx = studio.ctx
    studio._new_recipe()
    pump(0.05)
    assert graph_state(studio.scene) == ([], []) and ctx.dirty and ctx.engine.recipe.id == "BRACKET-A12"
    assert list(ctx.engine.recipe.devices) == ["cam1", "cam2", "plc1"]            # devices are kept
    assert "OK/NG" in studio.status.text()
    cam = studio.scene.add_node("source.camera", QPointF(0, 0))
    bright = studio.scene.add_node("measure.brightness", QPointF(300, 0))
    tol = studio.scene.add_node("logic.tolerance", QPointF(600, 0))
    studio.scene._connect(studio.scene.node_items[cam].out_ports["frame"], studio.scene.node_items[bright].in_ports["image"])
    studio.scene._connect(studio.scene.node_items[bright].out_ports["value"], studio.scene.node_items[tol].in_ports["value"])
    studio._set_param(studio.scene.graph.nodes[tol], "max", 255.0)
    assert "Hợp lệ" in studio.status.text() and "chưa lưu" in studio.recipe_info.text()
    assert studio._save_recipe() and not ctx.dirty and "chưa lưu" not in studio.recipe_info.text()
    saved = Recipe.load(ctx.recipe_path)
    assert saved.version == 1 and len(saved.graph.nodes) == 3 and len(saved.graph.edges) == 2
    assert ctx.engine.run_once().result.status == "OK"

    copy = tmp_path / "copy_b7.json"
    studio.save_recipe_as(str(copy))
    assert Recipe.load(copy).id == "COPY-B7" and ctx.recipe_path == str(copy)
    first = ctx.recipe_path
    assert studio.open_recipe(str(FOLDER_RECIPE)) and ctx.engine.recipe.id == "REAL-FOLDER-YOLO"
    assert not studio.scene.can_undo() and ctx.store.get("last_recipe") == str(FOLDER_RECIPE)
    assert not studio.open_recipe(str(tmp_path / "missing.json"))                # error box, state unchanged
    assert ctx.engine.recipe.id == "REAL-FOLDER-YOLO"
    assert studio.open_recipe(first) and len(studio.scene.graph.nodes) == 3


def test_empty_recipe_and_missing_result_run_as_error(studio):
    studio.scene.select_all()
    studio.scene.delete_selected()
    job = studio.ctx.engine.run_once()
    assert job.result.status == "ERROR" and job.result.reasons == ["NO_RESULT_NODE"]


# ---- devices ---------------------------------------------------------------------------------
def test_device_cards_and_reconnect(window, pump):
    devices = window.views["devices"]
    window.tab_buttons["devices"].click()
    pump(0.1)
    assert set(devices.cards) == {"cam1", "cam2", "plc1"}
    assert all(card["status"].text() == "Connected" for card in devices.cards.values())
    devices.scan_btn.click()
    pump(0.1)
    assert window.ctx.engine.run_once().result.status in ("OK", "NG")
    assert "RECONNECT_DEVICES" in [r[2] for r in window.ctx.store.audit_rows(5)]


def test_device_dialog_builds_config_for_each_adapter(window, tmp_path):
    dialog = DeviceDialog(["cam1"], parent=window)
    dialog.id_edit.setText("cam9")
    dialog.provider.setCurrentText("opencv")
    dialog.source.setText("2")
    dialog.width.setValue(1280)
    dialog.height.setValue(720)
    assert dialog.result_config() == ("cam9", {"kind": "camera", "provider": "opencv", "name": "cam9",
                                               "source": 2, "width": 1280, "height": 720})
    dialog.source.setText("rtsp://10.0.0.5/stream")
    dialog.width.setValue(0)
    assert dialog.result_config()[1]["source"] == "rtsp://10.0.0.5/stream" and "width" not in dialog.result_config()[1]
    dialog.provider.setCurrentText("folder")
    dialog.path.setText(str(tmp_path))
    assert dialog.result_config()[1] == {"kind": "camera", "provider": "folder", "name": "cam9", "path": str(tmp_path)}
    dialog.kind.setCurrentText("plc")
    dialog.provider.setCurrentText("modbus")
    dialog.host.setText("192.168.1.20")
    cfg = dialog.result_config()[1]
    assert cfg["host"] == "192.168.1.20" and cfg["port"] == 502 and cfg["tags"]["result_ng"] == 3
    dialog.id_edit.setText("cam1")
    dialog._accept()
    assert dialog.result() == 0                                                  # duplicate ID refused
    dialog.id_edit.setText("bad id!")
    dialog._accept()
    assert dialog.result() == 0


def test_device_dialog_builds_config_for_serial_tcp_and_ethercat(window):
    dialog = DeviceDialog([], parent=window)
    dialog.id_edit.setText("com1")
    dialog.kind.setCurrentText("comm")
    assert [dialog.provider.itemText(i) for i in range(dialog.provider.count())] == ["sim", "serial", "tcp", "udp", "ethercat"]
    dialog.provider.setCurrentText("serial")
    assert not dialog.preview.isVisibleTo(dialog) and "bản tin" in dialog.test_btn.text()
    dialog.serial_port.setEditText("COM7")
    dialog.baud.setEditText("115200")
    dialog.parity.setCurrentText("E")
    dialog.stopbits.setCurrentText("2")
    dialog.rs485.setChecked(True)
    assert dialog.result_config() == ("com1", {"kind": "comm", "provider": "serial", "name": "com1", "port": "COM7",
                                               "baudrate": 115200, "bytesize": 8, "parity": "E", "stopbits": 2.0,
                                               "rs485": True})
    dialog.provider.setCurrentText("tcp")
    dialog.host.setText("192.168.1.50")
    dialog.port.setValue(9100)
    assert dialog.result_config()[1] == {"kind": "comm", "provider": "tcp", "name": "com1", "host": "192.168.1.50", "port": 9100}
    dialog.provider.setCurrentText("ethercat")
    dialog.ecat_if.setEditText("eth1")
    dialog.ecat_slave.setValue(2)
    dialog.ecat_offset.setValue(4)
    assert dialog.result_config()[1] == {"kind": "comm", "provider": "ethercat", "name": "com1", "interface": "eth1",
                                         "slave": 2, "offset": 4, "cycle_ms": 10}
    dialog.kind.setCurrentText("plc")
    dialog.provider.setCurrentText("modbus_rtu")
    dialog.serial_port.setEditText("COM3")
    dialog.unit.setValue(17)
    cfg = dialog.result_config()[1]
    assert (cfg["port"], cfg["unit"], cfg["baudrate"], cfg["tags"]["busy"]) == ("COM3", 17, 115200, 0) and "rs485" not in cfg


def test_device_dialog_channel_test_button_and_reopen_for_edit(window):
    pytest.importorskip("serial")
    dialog = DeviceDialog([], parent=window)
    dialog.id_edit.setText("com1")
    dialog.kind.setCurrentText("comm")
    dialog.provider.setCurrentText("serial")
    dialog.serial_port.setEditText("loop://")
    dialog._test()
    assert "19" in dialog.test_msg.text() and "Exception" not in dialog.test_msg.text()
    dialog.serial_port.setEditText("NO_SUCH_PORT_99")
    dialog._test()
    assert "SerialException" in dialog.test_msg.text()
    dialog._scan_ports()                                                         # must not raise, whatever it finds
    _id, cfg = dialog.result_config()
    again = DeviceDialog(["com1"], "com1", cfg, parent=window)                   # editing shows what was saved
    assert again.serial_port.currentText() == "NO_SUCH_PORT_99" and again.kind.currentText() == "comm"
    assert again.result_config()[1] == cfg


def test_data_output_node_in_studio_lists_channels(window, pump, monkeypatch):
    from PyQt6.QtWidgets import QComboBox
    devices, studio, engine = window.views["devices"], window.views["studio"], window.ctx.engine
    monkeypatch.setattr(DeviceDialog, "exec", lambda self: True)
    monkeypatch.setattr(DeviceDialog, "result_config",
                        lambda self: ("com1", {"kind": "comm", "provider": "sim", "name": "Máy in nhãn"}))
    devices._add()
    window.tab_buttons["devices"].click()
    pump(0.1)
    assert "com1" in devices.cards and engine.devices.comms["com1"].status == "Connected"
    node_id = studio.scene.add_node("io.data_output", QPointF(900, 300))
    studio.scene._connect(studio.scene.node_items["cnt1"].out_ports["result"], studio.scene.node_items[node_id].in_ports["result"])
    pump(0.05)
    combos = [studio.form.itemAt(i).widget() for i in range(studio.form.count())
              if isinstance(studio.form.itemAt(i).widget(), QComboBox)]
    channel_box = combos[0]
    assert "com1" in [channel_box.itemText(i) for i in range(channel_box.count())]
    channel_box.setCurrentText("com1")
    for _ in range(3):
        engine.run_once()
    log = engine.devices.comms["com1"].log
    assert len(log) == 3 and log[0].split(b",")[0] in (b"OK", b"NG") and log[0].endswith(b"\r\n")
    pump(1.1)                                                                    # the card's counter refreshes each second
    assert "3" in devices.cards["com1"]["metric"].text()


def test_device_dialog_camera_test_button(window, tmp_path):
    engine = window.ctx.engine
    dialog = DeviceDialog(["cam1"], "cam1", engine.recipe.devices["cam1"], window, live=engine.devices.cameras["cam1"])
    dialog._test()
    assert "640" in dialog.test_msg.text() and dialog.preview.pixmap() is not None
    assert engine.devices.cameras["cam1"].status == "Connected"                  # the engine's handle was reopened
    dialog.provider.setCurrentText("folder")
    dialog.path.setText(str(tmp_path / "empty"))
    dialog._test()
    assert "RuntimeError" in dialog.test_msg.text()
    busy = DeviceDialog(["cam1"], "cam1", engine.recipe.devices["cam1"], window, engine_running=True)
    busy._test()
    assert "STOP" in busy.test_msg.text()


def test_add_edit_remove_device_through_the_view(window, pump, monkeypatch):
    devices, engine = window.views["devices"], window.ctx.engine
    window.tab_buttons["devices"].click()
    monkeypatch.setattr(DeviceDialog, "exec", lambda self: True)
    monkeypatch.setattr(DeviceDialog, "result_config",
                        lambda self: ("cam3", {"kind": "camera", "provider": "folder", "name": "Ảnh mẫu", "path": "samples"}))
    devices._add()
    pump(0.1)
    assert engine.devices.cameras["cam3"].status == "Connected" and "cam3" in devices.cards and window.ctx.dirty
    monkeypatch.setattr(DeviceDialog, "result_config",
                        lambda self: ("cam3", {"kind": "camera", "provider": "sim", "name": "Sim 3", "view": "side"}))
    devices._edit("cam3")
    assert engine.recipe.devices["cam3"]["provider"] == "sim"
    devices._remove("cam3")
    assert "cam3" not in engine.recipe.devices and "cam3" not in engine.devices.cameras
    devices._remove("cam2")                                                      # still used by a node
    job = engine.run_once()
    assert job.result.status == "ERROR" and job.result.reasons[0] == "NODE_FAILED:cam2"
    actions = [r[2] for r in window.ctx.store.audit_rows(10)]
    assert {"ADD_DEVICE", "EDIT_DEVICE", "REMOVE_DEVICE"} <= set(actions)


# ---- operator --------------------------------------------------------------------------------
def test_operator_view_shows_verdict_and_kpis(window, pump):
    operator, engine = window.views["operator"], window.ctx.engine
    window.tab_buttons["operator"].click()
    assert operator.verdict.text() == "--"
    for _ in range(5):
        engine.run_once()
    pump(0.1)
    last = engine.last_job
    assert operator.verdict.text() == last.result.status and last.job_id in operator.serial.text()
    assert operator.total.text() == "5" and "ms" in operator.cycle.text()
    assert int(operator.ok.text()) + int(operator.ng.text()) + int(operator.err.text()) == 5
    assert operator.image.pixmap() is not None and "%" in operator.yield_label.text()
    color = theme.result_color(last.result.status)
    assert color in operator.verdict.styleSheet()


# ---- history ---------------------------------------------------------------------------------
def test_history_filter_search_and_csv(window, pump, monkeypatch, tmp_path):
    history, engine = window.views["history"], window.ctx.engine
    engine.recipe.graph.nodes["cnt1"].params["expect"] = "connector=99"
    engine.update_graph(engine.recipe.graph)
    engine.run_once()                                                            # one certain NG
    engine.update_graph(Recipe.load(window.ctx.recipe_path).graph)
    for _ in range(6):
        engine.run_once()
    window.tab_buttons["history"].click()
    pump(0.1)
    assert history.table.rowCount() == 7 and history.table.item(0, 0).text() == "JOB-00007"
    history.filter.setCurrentText("NG")
    assert history.table.rowCount() >= 1
    assert all(history.table.item(r, 4).text() == "NG" for r in range(history.table.rowCount()))
    history.filter.setCurrentIndex(0)
    history.search.setText("MISSING_CONNECTOR")
    assert history.table.rowCount() >= 1
    history.search.setText("no-such-serial")
    assert history.table.rowCount() == 0
    history.search.setText("")
    out = tmp_path / "log.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    history._export()
    rows = list(csv.reader(open(out, encoding="utf-8-sig")))
    assert len(rows) == 8 and rows[0][0] == "Job ID" and rows[1][0] == "7"


# ---- reports ---------------------------------------------------------------------------------
def test_reports_kpis_pareto_pdf_and_excel(window, pump, monkeypatch, tmp_path):
    reports, engine = window.views["reports"], window.ctx.engine
    engine.recipe.graph.nodes["cnt1"].params["expect"] = "connector=99"
    engine.update_graph(engine.recipe.graph)
    for _ in range(3):
        engine.run_once()
    window.tab_buttons["reports"].click()
    pump(0.1)
    assert reports.c_total.value.text() == "3" and reports.c_ng.value.text() == "3" and reports.c_yield.value.text() == "0.00%"
    assert reports.pareto_box.count() >= 1
    pdf = tmp_path / "r.pdf"
    reports.write_pdf(str(pdf))
    assert pdf.read_bytes().startswith(b"%PDF") and pdf.stat().st_size > 1000
    openpyxl = pytest.importorskip("openpyxl")
    xlsx = tmp_path / "r.xlsx"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(xlsx), "")))
    reports._export_xlsx()
    book = openpyxl.load_workbook(xlsx)
    summary = {row[0]: row[1] for row in book.worksheets[0].iter_rows(values_only=True) if row[0]}
    assert summary["NG"] == 3 and summary["MISSING_CONNECTOR"] == 3 and book.worksheets[1].max_row == 4


def test_export_needs_permission(window, pump):
    window.ctx.logout()
    pump(0.05)
    from PyQt6.QtWidgets import QPushButton
    for key in ("history", "reports"):
        buttons = [b for b in window.views[key].findChildren(QPushButton) if "Xuất" in b.text()]
        assert buttons and not any(b.isEnabled() for b in buttons)
    assert not window.views["retrain"].export_btn.isEnabled()


# ---- retrain ---------------------------------------------------------------------------------
def test_retrain_buffer_view_and_dataset_export(window, pump):
    retrain, ctx = window.views["retrain"], window.ctx
    ctx.store.set("unc_lo", 0.0)
    ctx.store.set("unc_hi", 1.0)
    for _ in range(3):
        ctx.engine.run_once()
    window.tab_buttons["retrain"].click()
    pump(0.1)
    assert retrain.count.text() == "3 mẫu" and retrain.sample_name.text().startswith("JOB-")
    retrain._export()
    dataset = ctx.store.dir / "dataset"
    assert (dataset / "data.yaml").exists() and len(list((dataset / "images" / "train").glob("*.jpg"))) == 3
    assert "3" in retrain.log.toPlainText() and "EXPORT_DATASET" in [r[2] for r in ctx.store.audit_rows(3)]


def test_finetune_without_dataset_or_yolo_explains(window, monkeypatch):
    import shutil
    retrain = window.views["retrain"]
    retrain._train()
    assert "dataset" in retrain.log.toPlainText().lower() and retrain.proc is None
    retrain._export()
    monkeypatch.setattr(shutil, "which", lambda name: None)
    retrain._train()
    assert "pip install ultralytics" in retrain.log.toPlainText() and retrain.proc is None


# ---- settings --------------------------------------------------------------------------------
def test_settings_are_saved_audited_and_gated(window, pump):
    from PyQt6.QtWidgets import QLineEdit, QSpinBox
    settings, ctx = window.views["settings"], window.ctx
    spins = [w for w in settings.admin_widgets if isinstance(w, QSpinBox)]
    spins[0].setValue(333)                                                       # trigger interval
    assert ctx.store.get("interval_ms", int) == 333
    station = next(w for w in settings.admin_widgets if isinstance(w, QLineEdit))
    station.setText("LINE-07")
    station.editingFinished.emit()
    assert ctx.store.get("station_id") == "LINE-07"
    assert ("CHANGE_SETTING", "station_id = LINE-07") in [(r[2], r[3]) for r in ctx.store.audit_rows(5)]
    ctx.login("engineer", "1111")
    pump(0.05)
    assert not any(w.isEnabled() for w in settings.admin_widgets) and settings.role_note.text()
    assert settings.theme_box.isEnabled() and settings.lang_box.isEnabled()      # appearance is for everyone


def test_audit_table_and_cleanup(window, pump):
    settings = window.views["settings"]
    window.tab_buttons["settings"].click()
    settings.findChild(QTabWidget).setCurrentIndex(2)
    pump(0.05)
    assert settings.audit_table.rowCount() >= 2
    assert settings.audit_table.item(settings.audit_table.rowCount() - 1, 2).text() == "APP_START"
    settings._cleanup()
    assert window.ctx.store.audit_rows(1)[0][2] == "CLEANUP_ARCHIVE"


def test_settings_combo_changes_language(window, qapp, pump):
    settings = window.views["settings"]
    settings.lang_box.setCurrentIndex(settings.lang_box.findData("en"))
    settings.lang_box.activated.emit(settings.lang_box.currentIndex())
    pump(0.3)
    assert i18n.language() == "en" and qapp.property("main_window") is not window


# ---- closing ---------------------------------------------------------------------------------
def test_close_asks_about_unsaved_recipe(window, qapp, pump, monkeypatch):
    studio = window.views["studio"]
    studio.scene.add_node("classic.canny", QPointF(0, 0))
    assert window.ctx.dirty
    monkeypatch.setattr(studio, "confirm_discard", lambda: False)                # user presses "Hủy"
    window.close()
    pump(0.05)
    assert window.isVisible()
    monkeypatch.setattr(studio, "confirm_discard", lambda: True)
    window.close()
    pump(0.05)
    assert not window.isVisible() and window.ctx.store.audit_rows(1)[0][2] == "APP_EXIT"