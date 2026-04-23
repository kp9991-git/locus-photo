from unittest.mock import MagicMock, patch

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication

from viewer.core.enums import MetaTagName
from viewer.metadata.gps_operations import GpsOperationsMixin
from viewer.ui.widgets import MapWidget, ZoomablePhotoLabel, pil_image_to_qpixmap


class _DummyControl:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, value):
        self.enabled = bool(value)


class _DummyRoot:
    def __init__(self):
        self.cursor_set = False

    def setCursor(self, _cursor):
        self.cursor_set = True

    def unsetCursor(self):
        self.cursor_set = False


class _DummySignal:
    def __init__(self):
        self.calls = []

    def emit(self, payload=None):
        self.calls.append(payload)


class _DummySignals:
    def __init__(self):
        self.clear_map_signal = _DummySignal()
        self.update_map_signal = _DummySignal()
        self.gps_read_completed = _DummySignal()


class _DummyTreeItem:
    def __init__(self):
        self.icon_calls = []

    def setIcon(self, column, icon):
        self.icon_calls.append((column, icon))


class _GpsHarness(GpsOperationsMixin):
    GPS_TAGS = (MetaTagName.GPSAltitude, MetaTagName.GPSLatitude, MetaTagName.GPSLongitude)
    GPS_HISTORY_LIMIT = 3

    def __init__(self):
        self.logger = MagicMock()
        self.copy_to_clipboard_button = _DummyControl()
        self.paste_from_clipboard_button = _DummyControl()
        self.undo_gps_button = _DummyControl()
        self.redo_gps_button = _DummyControl()
        self.undo_gps_action = _DummyControl()
        self.redo_gps_action = _DummyControl()
        self.root = _DummyRoot()

        self.gps_write_in_progress = False
        self.gps_undo_stack = []
        self.gps_redo_stack = []

        self.has_gps_flags = {}
        self.shown_gps_flags = {}
        self.selected_items = []
        self.pin_icon = object()
        self.cross_icon = object()
        self.signals = _DummySignals()

        self.tree_items = {}
        self.refresh_calls = []

    def _find_tree_item(self, fpath):
        return self.tree_items.get(fpath)

    def refresh_file(self, fpath):
        self.refresh_calls.append(fpath)

    def is_file_acceptable(self, fpath):
        return not fpath.endswith(".bad")


class _DummyDelta:
    def __init__(self, value):
        self._value = value

    def y(self):
        return self._value


class _DummyWheelEvent:
    def __init__(self, delta):
        self._delta = delta
        self.accepted = False
        self.ignored = False

    def angleDelta(self):
        return _DummyDelta(self._delta)

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


class _DummyMouseEvent:
    def __init__(self, button, pos=(0, 0), buttons=None):
        self._button = button
        self._pos = QPoint(*pos)
        self._buttons = button if buttons is None else buttons
        self.accepted = False

    def button(self):
        return self._button

    def buttons(self):
        return self._buttons

    def position(self):
        return type("_PointF", (), {"toPoint": lambda _self: self._pos})()

    def accept(self):
        self.accepted = True


def test_parse_clipboard_gps_two_values():
    harness = _GpsHarness()

    tags = harness._parse_clipboard_gps("12.5, -45.25")

    assert tags[MetaTagName.GPSLatitude] == 12.5
    assert tags[MetaTagName.GPSLongitude] == -45.25
    assert MetaTagName.GPSAltitude not in tags


def test_parse_clipboard_gps_three_values_with_altitude():
    harness = _GpsHarness()

    tags = harness._parse_clipboard_gps("120.0 10.0 20.0")

    assert tags[MetaTagName.GPSAltitude] == 120.0
    assert tags[MetaTagName.GPSLatitude] == 10.0
    assert tags[MetaTagName.GPSLongitude] == 20.0


def test_parse_clipboard_gps_invalid_returns_none():
    harness = _GpsHarness()

    assert harness._parse_clipboard_gps("not-a-coordinate") is None


def test_normalize_gps_tags_filters_invalid_values():
    harness = _GpsHarness()

    normalized = harness._normalize_gps_tags({
        MetaTagName.GPSLatitude: "1.25",
        MetaTagName.GPSLongitude: "bad",
        MetaTagName.GPSAltitude: 100,
    })

    assert normalized[MetaTagName.GPSLatitude] == 1.25
    assert normalized[MetaTagName.GPSAltitude] == 100.0
    assert MetaTagName.GPSLongitude not in normalized


def test_update_gps_history_controls_sets_enabled_flags():
    harness = _GpsHarness()
    harness.gps_undo_stack = [{"label": "x", "changes": []}]
    harness.gps_redo_stack = []

    harness._update_gps_history_controls()

    assert harness.undo_gps_button.enabled is True
    assert harness.redo_gps_button.enabled is False
    assert harness.undo_gps_action.enabled is True
    assert harness.redo_gps_action.enabled is False


def test_record_gps_history_entry_ignores_noop_changes():
    harness = _GpsHarness()

    harness._record_gps_history_entry("noop", [{
        "fpath": "a.jpg",
        "before": {MetaTagName.GPSLatitude: 1.0},
        "after": {MetaTagName.GPSLatitude: 1.0},
    }])

    assert harness.gps_undo_stack == []


def test_record_gps_history_entry_stores_effective_change_and_clears_redo():
    harness = _GpsHarness()
    harness.gps_redo_stack = [{"label": "old", "changes": []}]

    harness._record_gps_history_entry("edit", [{
        "fpath": "a.jpg",
        "before": {MetaTagName.GPSLatitude: 1.0},
        "after": {MetaTagName.GPSLatitude: 2.0},
    }])

    assert len(harness.gps_undo_stack) == 1
    assert harness.gps_undo_stack[0]["label"] == "edit"
    assert harness.gps_redo_stack == []


def test_iter_selected_files_for_gps_edit_skips_dirs_and_unsupported():
    harness = _GpsHarness()
    harness.selected_items = ["dir", "ok.jpg", "bad.bad"]

    # Only the file accepted by is_file_acceptable should remain.
    with patch("viewer.metadata.gps_operations.os.path.isdir", side_effect=lambda p: p == "dir"):
        files = list(harness._iter_selected_files_for_gps_edit())

    assert files == ["ok.jpg"]


def test_on_gps_write_completed_paste_updates_flags_icons_and_map():
    harness = _GpsHarness()
    tree_item = _DummyTreeItem()
    harness.tree_items["a.jpg"] = tree_item
    harness._record_gps_history_entry = MagicMock()

    result = {
        "operation_kind": "paste",
        "label": "Paste GPS",
        "history_changes": [],
        "applied_tags_by_file": {
            "a.jpg": {
                MetaTagName.GPSLatitude: 1.0,
                MetaTagName.GPSLongitude: 2.0,
            }
        },
        "selected_locations": [(1.0, 2.0)],
        "changed_selected_item": True,
        "errors": [],
    }

    harness._on_gps_write_completed(result)

    assert harness.has_gps_flags["a.jpg"] is True
    assert harness.shown_gps_flags["a.jpg"] is True
    assert harness.refresh_calls == ["a.jpg"]
    assert tree_item.icon_calls[-1] == (0, harness.pin_icon)
    assert harness.signals.clear_map_signal.calls[-1] is None
    assert harness.signals.update_map_signal.calls[-1] == [(1.0, 2.0)]
    harness._record_gps_history_entry.assert_called_once()


def test_on_gps_write_completed_history_undo_moves_entry_to_redo_stack():
    harness = _GpsHarness()
    history_entry = {"label": "Edit GPS", "changes": [{"fpath": "a.jpg"}]}

    result = {
        "operation_kind": "history",
        "history_direction": "undo",
        "history_entry": history_entry,
        "applied_tags_by_file": {"a.jpg": {}},
        "selected_locations": [],
        "changed_selected_item": False,
        "errors": [],
    }

    harness._on_gps_write_completed(result)

    assert harness.gps_redo_stack == [history_entry]


def test_pil_image_to_qpixmap_converts_rgb_image(qapp):
    pil_img = Image.new("RGB", (10, 6), color=(255, 0, 0))

    pixmap = pil_image_to_qpixmap(pil_img)

    assert pixmap.width() == 10
    assert pixmap.height() == 6


def test_mapwidget_copy_result_updates_position_and_clipboard(qapp):
    dummy = type("DummyMap", (), {"_position": (0.0, 0.0)})()

    MapWidget._on_copy_position_result(dummy, [1.5, -2.25])

    assert dummy._position == (1.5, -2.25)
    assert QGuiApplication.clipboard().text() == "1.5, -2.25"


def test_mapwidget_copy_result_invalid_payload_keeps_position(qapp):
    dummy = type("DummyMap", (), {"_position": (9.0, 8.0)})()

    MapWidget._on_copy_position_result(dummy, ["x", 2.0])

    assert dummy._position == (9.0, 8.0)


def test_mapwidget_get_position_returns_cached_value():
    dummy = type("DummyMap", (), {"_position": (3.0, 4.0)})()

    assert MapWidget.get_position(dummy) == (3.0, 4.0)


def test_zoomable_photo_label_wheel_zoom_in_and_out(qapp):
    label = ZoomablePhotoLabel()
    base_pixmap = pil_image_to_qpixmap(Image.new("RGB", (120, 80), color=(20, 30, 40)))
    label.set_base_pixmap(base_pixmap)
    initial_width = label.pixmap().width()

    zoom_in_event = _DummyWheelEvent(120)
    label.wheelEvent(zoom_in_event)

    assert zoom_in_event.accepted is True
    assert label.pixmap().width() > initial_width

    for _ in range(25):
        label.wheelEvent(_DummyWheelEvent(-120))

    assert label.pixmap().width() == initial_width


def test_zoomable_photo_label_double_click_resets_zoom(qapp):
    label = ZoomablePhotoLabel()
    base_pixmap = pil_image_to_qpixmap(Image.new("RGB", (90, 60), color=(120, 30, 10)))
    label.set_base_pixmap(base_pixmap)
    initial_width = label.pixmap().width()

    label.wheelEvent(_DummyWheelEvent(120))
    assert label.pixmap().width() > initial_width

    dbl_click = _DummyMouseEvent(Qt.MouseButton.LeftButton)
    label.mouseDoubleClickEvent(dbl_click)

    assert dbl_click.accepted is True
    assert label.pixmap().width() == initial_width


def test_zoomable_photo_label_preserves_zoom_when_reset_flag_false(qapp):
    label = ZoomablePhotoLabel()
    base_pixmap = pil_image_to_qpixmap(Image.new("RGB", (100, 50), color=(1, 2, 3)))
    label.set_base_pixmap(base_pixmap)
    label.wheelEvent(_DummyWheelEvent(120))
    zoomed_width = label.pixmap().width()

    label.set_base_pixmap(base_pixmap, reset_zoom=False)

    assert label.pixmap().width() == zoomed_width


def test_zoomable_photo_label_drag_pan_moves_offset_when_zoomed(qapp):
    label = ZoomablePhotoLabel()
    label.resize(120, 120)
    base_pixmap = pil_image_to_qpixmap(Image.new("RGB", (120, 80), color=(10, 10, 10)))
    label.set_base_pixmap(base_pixmap)
    label.wheelEvent(_DummyWheelEvent(120))

    start_offset = QPoint(label._pan_offset)
    press = _DummyMouseEvent(Qt.MouseButton.LeftButton, pos=(10, 10))
    label.mousePressEvent(press)
    move = _DummyMouseEvent(Qt.MouseButton.NoButton, pos=(30, 20), buttons=Qt.MouseButton.LeftButton)
    label.mouseMoveEvent(move)
    release = _DummyMouseEvent(Qt.MouseButton.LeftButton, pos=(30, 20))
    label.mouseReleaseEvent(release)

    assert press.accepted is True
    assert move.accepted is True
    assert release.accepted is True
    assert label._pan_offset != start_offset


def test_zoomable_photo_label_drag_pan_is_clamped(qapp):
    label = ZoomablePhotoLabel()
    label.resize(120, 120)
    base_pixmap = pil_image_to_qpixmap(Image.new("RGB", (140, 140), color=(50, 60, 70)))
    label.set_base_pixmap(base_pixmap)
    label.wheelEvent(_DummyWheelEvent(120))

    max_x = max(0, (label.pixmap().width() - label.width()) // 2)
    max_y = max(0, (label.pixmap().height() - label.height()) // 2)

    label.mousePressEvent(_DummyMouseEvent(Qt.MouseButton.LeftButton, pos=(10, 10)))
    label.mouseMoveEvent(_DummyMouseEvent(Qt.MouseButton.NoButton, pos=(400, 450), buttons=Qt.MouseButton.LeftButton))
    label.mouseReleaseEvent(_DummyMouseEvent(Qt.MouseButton.LeftButton, pos=(400, 450)))

    assert label._pan_offset.x() <= max_x
    assert label._pan_offset.x() >= -max_x
    assert label._pan_offset.y() <= max_y
    assert label._pan_offset.y() >= -max_y


def test_zoomable_photo_label_requests_zoom_data_once(qapp):
    label = ZoomablePhotoLabel()
    base_pixmap = pil_image_to_qpixmap(Image.new("RGB", (120, 80), color=(90, 80, 70)))
    callback = MagicMock()
    label.set_zoom_request_callback(callback)
    label.set_base_pixmap(base_pixmap)

    label.wheelEvent(_DummyWheelEvent(120))
    label.wheelEvent(_DummyWheelEvent(120))

    callback.assert_called_once_with(label)
