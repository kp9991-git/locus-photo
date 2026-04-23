import pytest
from unittest.mock import MagicMock, patch
import os

from PySide6.QtCore import Qt

from viewer.core.enums import MetaTagName
from viewer.metadata.gps_operations import GpsOperationsMixin

class _DummyControl:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, value):
        self.enabled = bool(value)

class _DummyRoot:
    def __init__(self):
        self.cursor_shape = None

    def setCursor(self, cursor_shape):
        self.cursor_shape = cursor_shape

    def unsetCursor(self):
        self.cursor_shape = None

class _DummySignal:
    def __init__(self):
        self.calls = []
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, payload=None):
        self.calls.append(payload)
        for callback in list(self._callbacks):
            callback(payload)

class _DummySignals:
    def __init__(self):
        self.clear_map_signal = _DummySignal()
        self.update_map_signal = _DummySignal()
        self.gps_write_completed = _DummySignal()
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
        self.gps_read_in_progress = False
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
        
        self.exiftool = MagicMock()
        self.map_widget = MagicMock()
        self.canvas_selected_fpath = None
        self.copied_gps_position = None

        self.signals.gps_read_completed.connect(self._on_gps_read_completed)

    def _find_tree_item(self, fpath):
        return self.tree_items.get(fpath)

    def refresh_file(self, fpath):
        self.refresh_calls.append(fpath)

    def is_file_acceptable(self, fpath):
        return not fpath.endswith(".bad")

def test_has_gps_flag_for_file_in_cache():
    harness = _GpsHarness()
    harness.has_gps_flags["C:\\test.jpg"] = True
    assert harness.has_gps_flag_for_file_in_cache("C:\\test.jpg") == ("C:\\test.jpg", True)
    
    harness.has_gps_flags["C:/test2.jpg"] = False
    assert harness.has_gps_flag_for_file_in_cache("C:\\test2.jpg") == ("C:/test2.jpg", False)
    
    assert harness.has_gps_flag_for_file_in_cache("unknown.jpg") == ("unknown.jpg", None)

@patch("viewer.metadata.gps_operations.os.path.isdir")
def test_extract_gps_coordinates_and_put_in_cache_dir(mock_isdir):
    mock_isdir.return_value = True
    harness = _GpsHarness()
    harness.exiftool.get_meta_data.return_value = {"C:/test.jpg": [1.0], "C:/test2.jpg": []}
    
    res, updated = harness.extract_gps_coordinates_and_put_in_cache("C:/dir")
    
    assert res is False
    assert updated is True
    assert harness.has_gps_flags["C:/test.jpg"] is True
    assert harness.has_gps_flags["C:/test2.jpg"] is False

@patch("viewer.metadata.gps_operations.os.path.isdir")
def test_extract_gps_coordinates_and_put_in_cache_file(mock_isdir):
    mock_isdir.return_value = False
    harness = _GpsHarness()
    
    # unsupported file
    res, updated = harness.extract_gps_coordinates_and_put_in_cache("bad.bad")
    assert res is False
    assert updated is True
    
    # no gps data
    harness.exiftool.get_meta_data.return_value = {}
    res, updated = harness.extract_gps_coordinates_and_put_in_cache("good.jpg")
    assert res is False
    assert updated is True
    
    # has gps data
    harness.exiftool.get_meta_data.return_value = {"good.jpg": {"GPSLatitude": 1.0}}
    res, updated = harness.extract_gps_coordinates_and_put_in_cache("good.jpg")
    assert res is True
    assert updated is True
    assert harness.has_gps_flags["good.jpg"] is True

def test_update_has_gps_flag():
    harness = _GpsHarness()
    harness.tree_items["test.jpg"] = _DummyTreeItem()
    
    harness.extract_gps_coordinates_and_put_in_cache = MagicMock(return_value=(True, True))
    harness.update_has_gps_flag("test.jpg")
    assert harness.tree_items["test.jpg"].icon_calls[-1] == (0, harness.pin_icon)
    
    harness.extract_gps_coordinates_and_put_in_cache = MagicMock(return_value=(False, True))
    harness.update_has_gps_flag("test.jpg")
    assert harness.tree_items["test.jpg"].icon_calls[-1] == (0, harness.cross_icon)

def test_normalize_gps_tags_exceptions():
    harness = _GpsHarness()
    res = harness._normalize_gps_tags({MetaTagName.GPSLatitude: "invalid"})
    assert MetaTagName.GPSLatitude not in res
    assert harness.logger.info.called

def test_read_gps_tags():
    harness = _GpsHarness()
    harness.exiftool.get_meta_data.return_value = {"test.jpg": {MetaTagName.GPSLatitude: 10.0}}
    tags = harness._read_gps_tags("test.jpg")
    assert tags[MetaTagName.GPSLatitude] == 10.0
    
    harness.exiftool.get_meta_data.return_value = {"test.jpg": None}
    tags = harness._read_gps_tags("test.jpg")
    assert tags == {}

    harness.exiftool.get_meta_data.side_effect = Exception("error")
    tags = harness._read_gps_tags("test.jpg")
    assert tags == {}

def test_apply_gps_tags():
    harness = _GpsHarness()
    tags = {MetaTagName.GPSLatitude: 10.0}
    applied = harness._apply_gps_tags("test.jpg", tags)
    assert applied[MetaTagName.GPSLatitude] == 10.0
    harness.exiftool.apply_meta_data.assert_called_once_with(
        "test.jpg",
        tags={MetaTagName.GPSLatitude: 10.0},
        clear_tags=list(harness.GPS_TAGS),
    )

    harness.exiftool.reset_mock()
    applied = harness._apply_gps_tags("test.jpg", {})
    assert applied == {}
    harness.exiftool.apply_meta_data.assert_called_once_with(
        "test.jpg",
        tags={},
        clear_tags=list(harness.GPS_TAGS),
    )

def test_parse_clipboard_gps_exceptions():
    harness = _GpsHarness()
    assert harness._parse_clipboard_gps("invalid, 10.0") is None
    assert harness._parse_clipboard_gps("10.0, invalid") is None
    tags = harness._parse_clipboard_gps("invalid, 10.0, 20.0")
    assert MetaTagName.GPSAltitude not in tags

def test_apply_gps_history_entry():
    harness = _GpsHarness()
    harness.selected_items = ["test.jpg"]
    history_entry = {
        "changes": [
            {"fpath": "test.jpg", "after": {MetaTagName.GPSLatitude: 10.0, MetaTagName.GPSLongitude: 20.0}},
            {"fpath": "test2.jpg", "after": {MetaTagName.GPSLatitude: 30.0}}
        ]
    }
    
    harness.update_has_gps_flag = MagicMock()
    harness._apply_gps_history_entry(history_entry, apply_after_state=True)
    
    harness.update_has_gps_flag.assert_any_call("test.jpg")
    harness.update_has_gps_flag.assert_any_call("test2.jpg")
    assert "test.jpg" in harness.refresh_calls
    assert harness.signals.update_map_signal.calls[-1] == [(10.0, 20.0)]
    
    # Test exception handling
    harness._apply_gps_tags = MagicMock(side_effect=Exception("error"))
    harness._apply_gps_history_entry(history_entry, apply_after_state=True)
    assert harness.logger.error.called

def test_set_gps_operation_busy():
    harness = _GpsHarness()
    harness._set_gps_operation_busy(True)
    assert harness.gps_write_in_progress is True
    assert harness.copy_to_clipboard_button.enabled is False
    assert harness.paste_from_clipboard_button.enabled is False
    assert harness.undo_gps_button.enabled is False
    assert harness.root.cursor_shape == Qt.CursorShape.WaitCursor
    
    harness._set_gps_operation_busy(False)
    assert harness.gps_write_in_progress is False
    assert harness.copy_to_clipboard_button.enabled is True
    assert harness.paste_from_clipboard_button.enabled is True
    assert harness.root.cursor_shape is None

def test_start_bulk_gps_write():
    harness = _GpsHarness()
    harness.gps_write_in_progress = True
    harness._start_bulk_gps_write("label", {})
    
    harness.gps_write_in_progress = False
    harness._start_bulk_gps_write("label", {})
    
    harness.selected_items = []
    harness._start_bulk_gps_write("label", {MetaTagName.GPSLatitude: 10.0})
    
    harness.selected_items = ["test.jpg"]
    with patch("viewer.metadata.gps_operations.threading.Thread") as mock_thread:
        harness._start_bulk_gps_write("label", {MetaTagName.GPSLatitude: 10.0})
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

def test_start_history_gps_write():
    harness = _GpsHarness()
    harness.gps_write_in_progress = True
    assert harness._start_history_gps_write({}, True) is False
    
    harness.gps_write_in_progress = False
    assert harness._start_history_gps_write({}, True) is False
    assert harness._start_history_gps_write({"changes": []}, True) is False
    
    with patch("viewer.metadata.gps_operations.threading.Thread") as mock_thread:
        assert harness._start_history_gps_write({"changes": [{"fpath": "test.jpg"}]}, True) is True
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

@patch("viewer.metadata.gps_operations.ExifToolWrapper")
def test_run_bulk_gps_write(mock_exif_wrapper):
    harness = _GpsHarness()
    mock_exif_instance = mock_exif_wrapper.return_value
    harness._read_gps_tags = MagicMock(return_value={})
    harness._apply_gps_tags = MagicMock(return_value={MetaTagName.GPSLatitude: 10.0, MetaTagName.GPSLongitude: 20.0})
    
    harness._run_bulk_gps_write("label", {MetaTagName.GPSLatitude: 10.0, MetaTagName.GPSLongitude: 20.0}, ["test.jpg"])
    
    assert len(harness.signals.gps_write_completed.calls) == 1
    result = harness.signals.gps_write_completed.calls[0]
    assert result["operation_kind"] == "paste"
    assert result["label"] == "label"
    assert result["changed_selected_item"] is True
    assert "test.jpg" in result["applied_tags_by_file"]
    assert result["selected_locations"] == [(10.0, 20.0)]
    mock_exif_instance.terminate.assert_called_once()


@patch("viewer.metadata.gps_operations.ExifToolWrapper")
def test_run_bulk_gps_write_records_timeout_as_failure_without_applied_tags(mock_exif_wrapper):
    harness = _GpsHarness()
    mock_exif_instance = mock_exif_wrapper.return_value
    harness._read_gps_tags = MagicMock(return_value={})
    harness._apply_gps_tags = MagicMock(side_effect=TimeoutError("timed out"))

    harness._run_bulk_gps_write("label", {MetaTagName.GPSLatitude: 10.0}, ["test.jpg"])

    result = harness.signals.gps_write_completed.calls[-1]
    assert result["operation_kind"] == "paste"
    assert result["changed_selected_item"] is False
    assert result["applied_tags_by_file"] == {}
    assert len(result["errors"]) == 1
    assert result["errors"][0][0] == "test.jpg"
    mock_exif_instance.terminate.assert_called_once()

@patch("viewer.metadata.gps_operations.ExifToolWrapper")
def test_run_history_gps_write(mock_exif_wrapper):
    harness = _GpsHarness()
    mock_exif_instance = mock_exif_wrapper.return_value
    harness._apply_gps_tags = MagicMock(return_value={MetaTagName.GPSLatitude: 10.0, MetaTagName.GPSLongitude: 20.0})
    
    history_entry = {"changes": [{"fpath": "test.jpg", "after": {MetaTagName.GPSLatitude: 10.0, MetaTagName.GPSLongitude: 20.0}}]}
    harness._run_history_gps_write(history_entry, True, ["test.jpg"])
    
    assert len(harness.signals.gps_write_completed.calls) == 1
    result = harness.signals.gps_write_completed.calls[0]
    assert result["operation_kind"] == "history"
    assert result["history_direction"] == "redo"
    assert result["changed_selected_item"] is True
    assert "test.jpg" in result["applied_tags_by_file"]
    assert result["selected_locations"] == [(10.0, 20.0)]
    mock_exif_instance.terminate.assert_called_once()

def test_copy_gps_from_file():
    harness = _GpsHarness()
    harness.canvas_selected_fpath = "test.jpg"
    with patch("viewer.metadata.gps_operations.ExifToolWrapper") as mock_exif_wrapper:
        mock_exif_instance = mock_exif_wrapper.return_value
        mock_exif_instance.get_meta_data.return_value = {"test.jpg": {MetaTagName.GPSLatitude: 10.0}}

        with patch("viewer.metadata.gps_operations.threading.Thread") as mock_thread:
            def _thread_factory(*, target, args, daemon):
                thread_mock = MagicMock()
                thread_mock.start.side_effect = lambda: target(*args)
                return thread_mock

            mock_thread.side_effect = _thread_factory
            harness.copy_gps_from_file()

    assert harness.copied_gps_position == {MetaTagName.GPSLatitude: 10.0}
    
    harness.canvas_selected_fpath = None
    harness.copied_gps_position = None
    harness.copy_gps_from_file()
    assert harness.copied_gps_position is None

def test_paste_gps_to_file():
    harness = _GpsHarness()
    harness.copied_gps_position = None
    harness.paste_gps_to_file()
    
    harness.copied_gps_position = {MetaTagName.GPSLatitude: "invalid"}
    harness.paste_gps_to_file()
    
    harness.copied_gps_position = {MetaTagName.GPSLatitude: 10.0}
    harness._start_bulk_gps_write = MagicMock()
    harness.paste_gps_to_file()
    harness._start_bulk_gps_write.assert_called_once()

@patch("viewer.metadata.gps_operations.pyperclip.copy")
def test_copy_gps_to_clipboard(mock_copy):
    harness = _GpsHarness()
    harness.canvas_selected_fpath = "test.jpg"
    harness.map_widget.get_position.return_value = (10.0, 20.0)
    
    with patch("viewer.metadata.gps_operations.ExifToolWrapper") as mock_exif_wrapper:
        mock_exif_instance = mock_exif_wrapper.return_value

        with patch("viewer.metadata.gps_operations.threading.Thread") as mock_thread:
            def _thread_factory(*, target, args, daemon):
                thread_mock = MagicMock()
                thread_mock.start.side_effect = lambda: target(*args)
                return thread_mock

            mock_thread.side_effect = _thread_factory

            # 3 values, same as map
            mock_exif_instance.get_meta_data.return_value = {"test.jpg": {MetaTagName.GPSAltitude: 5.0, MetaTagName.GPSLatitude: 10.0, MetaTagName.GPSLongitude: 20.0}}
            harness.copy_gps_to_clipboard()
            mock_copy.assert_called_with("5.0, 10.0, 20.0")

            # 3 values, different from map
            mock_exif_instance.get_meta_data.return_value = {"test.jpg": {MetaTagName.GPSAltitude: 5.0, MetaTagName.GPSLatitude: 15.0, MetaTagName.GPSLongitude: 20.0}}
            harness.copy_gps_to_clipboard()
            mock_copy.assert_called_with("10.0, 20.0")

            # 2 values, same as map
            mock_exif_instance.get_meta_data.return_value = {"test.jpg": {MetaTagName.GPSLatitude: 10.0, MetaTagName.GPSLongitude: 20.0}}
            harness.copy_gps_to_clipboard()
            mock_copy.assert_called_with("10.0, 20.0")

            # 2 values, different from map
            mock_exif_instance.get_meta_data.return_value = {"test.jpg": {MetaTagName.GPSLatitude: 15.0, MetaTagName.GPSLongitude: 20.0}}
            harness.copy_gps_to_clipboard()
            mock_copy.assert_called_with("10.0, 20.0")

            # 0 values
            mock_exif_instance.get_meta_data.return_value = {"test.jpg": {}}
            harness.copy_gps_to_clipboard()
            mock_copy.assert_called_with("10.0, 20.0")

@patch("viewer.metadata.gps_operations.pyperclip.paste")
def test_paste_gps_from_clipboard(mock_paste):
    harness = _GpsHarness()
    mock_paste.return_value = ""
    harness.paste_gps_from_clipboard()
    
    mock_paste.return_value = "invalid"
    harness.paste_gps_from_clipboard()
    
    mock_paste.return_value = "10.0, 20.0"
    harness._start_bulk_gps_write = MagicMock()
    harness.paste_gps_from_clipboard()
    harness._start_bulk_gps_write.assert_called_once()

def test_undo_last_gps_edit():
    harness = _GpsHarness()
    harness.gps_write_in_progress = True
    harness.undo_last_gps_edit()
    
    harness.gps_write_in_progress = False
    harness.undo_last_gps_edit()
    
    harness.gps_undo_stack.append({"label": "test"})
    harness._start_history_gps_write = MagicMock(return_value=False)
    harness.undo_last_gps_edit()
    assert len(harness.gps_undo_stack) == 1

def test_redo_last_gps_edit():
    harness = _GpsHarness()
    harness.gps_write_in_progress = True
    harness.redo_last_gps_edit()
    
    harness.gps_write_in_progress = False
    harness.redo_last_gps_edit()
    
    harness.gps_redo_stack.append({"label": "test"})
    harness._start_history_gps_write = MagicMock(return_value=False)
    harness.redo_last_gps_edit()
    assert len(harness.gps_redo_stack) == 1

def test_on_gps_write_completed_history_with_errors():
    harness = _GpsHarness()
    harness.gps_undo_stack = []
    
    result = {
        "operation_kind": "history",
        "history_direction": "undo",
        "history_entry": {"label": "test"},
        "applied_tags_by_file": {},
        "errors": ["error"]
    }
    harness._on_gps_write_completed(result)
    assert len(harness.gps_undo_stack) == 1
    assert len(harness.gps_redo_stack) == 0

    harness.gps_undo_stack = []
    harness.gps_redo_stack = []
    result["history_direction"] = "redo"
    harness._on_gps_write_completed(result)
    assert len(harness.gps_undo_stack) == 0
    assert len(harness.gps_redo_stack) == 1

def test_apply_gps_history_entry_handles_apply_error_without_logger():
    harness = _GpsHarness()
    harness.logger = None
    harness.selected_items = ["test.jpg"]
    harness._apply_gps_tags = MagicMock(side_effect=Exception("error"))

    history_entry = {
        "changes": [{"fpath": "test.jpg", "after": {MetaTagName.GPSLatitude: 10.0}}]
    }
    harness._apply_gps_history_entry(history_entry, apply_after_state=True)

    assert harness.refresh_calls == []


def test_run_history_gps_write_collects_errors_and_swallows_terminate_exception():
    harness = _GpsHarness()
    harness.logger = MagicMock()
    harness._apply_gps_tags = MagicMock(side_effect=Exception("apply error"))

    history_entry = {
        "changes": [{"fpath": "test.jpg", "after": {MetaTagName.GPSLatitude: 10.0}}]
    }

    with patch("viewer.metadata.gps_operations.ExifToolWrapper") as mock_exif_wrapper:
        mock_exif_instance = mock_exif_wrapper.return_value
        mock_exif_instance.terminate.side_effect = Exception("terminate error")

        harness._run_history_gps_write(history_entry, True, ["test.jpg"])

    assert mock_exif_instance.terminate.called
    result = harness.signals.gps_write_completed.calls[-1]
    assert result["operation_kind"] == "history"
    assert result["history_direction"] == "redo"
    assert len(result["errors"]) == 1


def test_on_gps_write_completed_history_undo_error_requeues_undo_stack():
    harness = _GpsHarness()

    harness._on_gps_write_completed({
        "operation_kind": "history",
        "history_direction": "undo",
        "history_entry": {"label": "test_undo_error"},
        "applied_tags_by_file": {},
        "errors": ["error"],
    })

    assert harness.gps_undo_stack[-1]["label"] == "test_undo_error"
    assert harness.gps_redo_stack == []


def test_on_gps_write_completed_history_redo_success_pushes_to_undo_stack():
    harness = _GpsHarness()

    harness._on_gps_write_completed({
        "operation_kind": "history",
        "history_direction": "redo",
        "history_entry": {"label": "test_redo_success"},
        "applied_tags_by_file": {"test.jpg": {MetaTagName.GPSLatitude: 10.0}},
        "errors": [],
    })

    assert harness.gps_undo_stack[-1]["label"] == "test_redo_success"


def test_on_gps_write_completed_history_redo_error_requeues_redo_stack():
    harness = _GpsHarness()

    harness._on_gps_write_completed({
        "operation_kind": "history",
        "history_direction": "redo",
        "history_entry": {"label": "test_redo_error"},
        "applied_tags_by_file": {},
        "errors": ["error"],
    })

    assert harness.gps_redo_stack[-1]["label"] == "test_redo_error"


def test_copy_and_paste_gps_noop_without_logger_and_selection():
    harness = _GpsHarness()
    harness.logger = None
    harness.canvas_selected_fpath = None
    harness.copied_gps_position = None

    harness.copy_gps_from_file()
    harness.paste_gps_to_file()

    assert harness.copied_gps_position is None


def test_copy_gps_to_clipboard_uses_map_when_file_position_differs_without_logger():
    harness = _GpsHarness()
    harness.logger = None
    harness.canvas_selected_fpath = "test.jpg"
    harness.map_widget.get_position.return_value = (10.0, 20.0)
    with patch("viewer.metadata.gps_operations.ExifToolWrapper") as mock_exif_wrapper:
        mock_exif_instance = mock_exif_wrapper.return_value
        mock_exif_instance.get_meta_data.return_value = {
            "test.jpg": {
                MetaTagName.GPSAltitude: 5.0,
                MetaTagName.GPSLatitude: 15.0,
                MetaTagName.GPSLongitude: 20.0,
            }
        }

        with patch("viewer.metadata.gps_operations.threading.Thread") as mock_thread:
            def _thread_factory(*, target, args, daemon):
                thread_mock = MagicMock()
                thread_mock.start.side_effect = lambda: target(*args)
                return thread_mock

            mock_thread.side_effect = _thread_factory

            with patch("viewer.metadata.gps_operations.pyperclip.copy") as mock_copy:
                harness.copy_gps_to_clipboard()

            mock_copy.assert_called_once_with("10.0, 20.0")


def test_record_gps_history_entry_keeps_limit():
    harness = _GpsHarness()
    harness.gps_undo_stack = [{"label": "old1"}, {"label": "old2"}, {"label": "old3"}]

    harness._record_gps_history_entry("new", [{
        "fpath": "x",
        "before": {MetaTagName.GPSLatitude: 1.0},
        "after": {MetaTagName.GPSLatitude: 2.0},
    }])

    assert len(harness.gps_undo_stack) == 3
    assert harness.gps_undo_stack[-1]["label"] == "new"


def test_run_bulk_gps_write_collects_errors_and_swallows_terminate_exception():
    harness = _GpsHarness()
    harness.logger = MagicMock()

    with patch("viewer.metadata.gps_operations.ExifToolWrapper") as mock_exif_wrapper:
        mock_exif_instance = mock_exif_wrapper.return_value
        mock_exif_instance.terminate.side_effect = Exception("terminate error")
        harness._read_gps_tags = MagicMock(side_effect=Exception("loop error"))

        harness._run_bulk_gps_write("label", {MetaTagName.GPSLatitude: 1.0}, ["test.jpg"])

    assert mock_exif_instance.terminate.called
    assert harness.logger.error.called
    result = harness.signals.gps_write_completed.calls[-1]
    assert result["operation_kind"] == "paste"
    assert len(result["errors"]) == 1
    assert result["errors"][0][0] == "test.jpg"


def test_run_history_gps_write_skips_change_without_fpath():
    harness = _GpsHarness()

    with patch("viewer.metadata.gps_operations.ExifToolWrapper"):
        harness._run_history_gps_write({"changes": [{"after": {}}]}, True, [])

    result = harness.signals.gps_write_completed.calls[-1]
    assert result["operation_kind"] == "history"
    assert result["applied_tags_by_file"] == {}
    assert result["errors"] == []


def test_on_gps_write_completed_non_dict_result_is_noop_after_busy_reset():
    harness = _GpsHarness()
    harness.gps_write_in_progress = True

    harness._on_gps_write_completed(None)

    assert harness.gps_write_in_progress is False


def test_on_gps_write_completed_history_stack_limits_are_enforced():
    harness = _GpsHarness()

    harness.gps_redo_stack = [{}, {}, {}]
    harness._on_gps_write_completed({
        "operation_kind": "history",
        "history_direction": "undo",
        "history_entry": {"label": "x"},
        "applied_tags_by_file": {"x": {MetaTagName.GPSLatitude: 1.0}},
        "errors": [],
    })
    assert len(harness.gps_redo_stack) == 3

    harness.gps_undo_stack = [{}, {}, {}]
    harness._on_gps_write_completed({
        "operation_kind": "history",
        "history_direction": "redo",
        "history_entry": {"label": "y"},
        "applied_tags_by_file": {"y": {MetaTagName.GPSLatitude: 1.0}},
        "errors": [],
    })
    assert len(harness.gps_undo_stack) == 3

