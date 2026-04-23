import pytest
from unittest.mock import MagicMock, patch
import queue

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QGridLayout, QWidget

from viewer.mixins.photo_grid import PhotoGridMixin
from viewer.metadata.image_container import ImageContainer
from viewer.core.enums import MetaTagName
from viewer.ui.widgets import ZoomablePhotoLabel

class _DummyQueue:
    def __init__(self, items=None):
        self.items = items or []
    def put(self, item):
        self.items.append(item)
    def get(self, timeout=None):
        if not self.items:
            return None
        return self.items.pop(0)
    def empty(self):
        return len(self.items) == 0

class _DummySignal:
    def __init__(self):
        self.calls = []
    def emit(self, payload=None):
        self.calls.append(payload)

class _DummySignals:
    def __init__(self):
        self.clear_map_signal = _DummySignal()
        self.update_map_signal = _DummySignal()
        self.display_images_signal = _DummySignal()
        self.zoom_image_ready = _DummySignal()

class _DummyHarness(PhotoGridMixin):
    def __init__(self):
        self.selected_photo_fpaths = []
        self.grid_items_per_page = 4
        self.current_page_index = 0
        self.image_load_queue = _DummyQueue()
        self.display_image_queue = _DummyQueue()
        self.map_location_queue = _DummyQueue()
        self.text_color = "black"
        self.bg_color = "white"
        self.theme_name = "light"
        
        self.photo_grid_layout = MagicMock()
        self.image_labels = []
        self.displayed_photos = []
        self.canvas_currently_displayed_image_fpath = None
        self.canvas_selected_fpath = None
        self.canvas_selected_fpath_loaded = False
        
        self.pagination_frame = MagicMock()
        self.page_status_label = MagicMock()
        self.first_page_button = MagicMock()
        self.prev_page_button = MagicMock()
        self.next_page_button = MagicMock()
        self.last_page_button = MagicMock()
        
        self.map_widget = MagicMock()
        self.signals = _DummySignals()
        self.running = True
        self.logger = MagicMock()
        self.IMAGE_SUPPORTED_EXTENSIONS = [".jpg", ".png"]
        self.SUPPORTED_EXTENSIONS = [".jpg", ".cr2"]
        self.MAX_FILE_SIZE = 2e8
        self.use_logging = False
        self.exiftool = MagicMock()
        
        self.photo_frame = MagicMock()
        self.photo_frame.width.return_value = 800
        self.photo_frame.height.return_value = 600

        self.images = {}

    def get_image(self, fpath):
        return self.images.get(fpath)

def test_queue_image_preload_window():
    harness = _DummyHarness()
    harness.selected_photo_fpaths = []
    harness._queue_image_preload_window()
    assert len(harness.image_load_queue.items) == 0

    harness.selected_photo_fpaths = ["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg"]
    harness.grid_items_per_page = 2
    harness.current_page_index = 1 # start at index 2, length is 4 (2*2)
    harness._queue_image_preload_window()
    assert harness.image_load_queue.items == ["3.jpg", "4.jpg", "5.jpg"]

def test_get_photo_label_stylesheet():
    harness = _DummyHarness()
    stylesheet = harness._get_photo_label_stylesheet()
    assert "black" in stylesheet
    assert "transparent" in stylesheet

def test_decorate_photo_pixmap_null():
    harness = _DummyHarness()
    assert harness._decorate_photo_pixmap(None) is None
    
    empty_pixmap = QPixmap()
    assert harness._decorate_photo_pixmap(empty_pixmap) == empty_pixmap

@patch("viewer.mixins.photo_grid.QPainter")
def test_decorate_photo_pixmap(mock_painter):
    harness = _DummyHarness()
    pixmap = QPixmap(100, 100)
    decorated = harness._decorate_photo_pixmap(pixmap)
    assert decorated is not None
    assert decorated.width() > 100
    mock_painter.assert_called()

def test_apply_photo_label_decoration():
    harness = _DummyHarness()
    label = MagicMock()
    label.property.return_value = QPixmap(100, 100)
    harness._apply_photo_label_decoration(label)
    label.setStyleSheet.assert_called_once()
    label.set_base_pixmap.assert_called_once()

def test_apply_photo_label_decoration_no_base_pixmap():
    harness = _DummyHarness()
    label = MagicMock()
    label.property.return_value = None
    del label.set_base_pixmap
    harness._apply_photo_label_decoration(label)
    assert not hasattr(label, 'setPixmap') or not label.setPixmap.called

def test_apply_photo_label_decoration_fallback():
    harness = _DummyHarness()
    label = MagicMock()
    label.property.return_value = QPixmap(100, 100)

    harness._apply_photo_label_decoration(label)
    label.set_base_pixmap.assert_called_once()

def test_clear_photo_grid():
    harness = _DummyHarness()
    harness.photo_grid_layout = None
    harness._clear_photo_grid() # no op
    
    harness.photo_grid_layout = MagicMock()
    label1, label2 = MagicMock(), MagicMock()
    harness.image_labels = [label1, label2]
    harness._clear_photo_grid()
    
    assert harness.photo_grid_layout.removeWidget.call_count == 2
    assert label1.deleteLater.called
    assert len(harness.image_labels) == 0

def test_get_total_pages():
    harness = _DummyHarness()
    assert harness._get_total_pages() == 0
    
    harness.selected_photo_fpaths = ["1.jpg"] * 5
    harness.grid_items_per_page = 2
    assert harness._get_total_pages() == 3

def test_get_current_page_fpaths():
    harness = _DummyHarness()
    assert harness._get_current_page_fpaths() == []
    
    harness.selected_photo_fpaths = ["1.jpg", "2.jpg", "3.jpg"]
    harness.grid_items_per_page = 2
    harness.current_page_index = 10
    
    fpaths = harness._get_current_page_fpaths()
    assert harness.current_page_index == 1
    assert fpaths == ["3.jpg"]

def test_update_pagination_controls():
    harness = _DummyHarness()
    harness.pagination_frame = None
    harness._update_pagination_controls() # No error
    
    harness.pagination_frame = MagicMock()
    harness.selected_photo_fpaths = ["1.jpg"]
    harness._update_pagination_controls()
    harness.pagination_frame.setVisible.assert_called_with(False)
    
    harness.selected_photo_fpaths = ["1.jpg", "2.jpg", "3.jpg"]
    harness.grid_items_per_page = 2
    harness.current_page_index = 0
    harness._update_pagination_controls()
    harness.pagination_frame.setVisible.assert_called_with(True)
    harness.page_status_label.setText.assert_called_with("1/2 (3 images)")
    
    harness.current_page_index = 1
    harness._update_pagination_controls()
    harness.page_status_label.setText.assert_called_with("2/2 (3 images)")

    # Test total_pages == 0 logic
    harness.selected_photo_fpaths = []
    harness._get_total_pages = MagicMock(return_value=0)
    # simulate total_selected > 1 so it doesn't return early in the first check
    with patch.object(harness, "selected_photo_fpaths", ["1.jpg", "2.jpg"]):
        harness._update_pagination_controls()
        harness.page_status_label.setText.assert_called_with("")
        harness.first_page_button.setEnabled.assert_called_with(False)

def test_queue_current_page_for_display():
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["1.jpg"]
    harness._queue_current_page_for_display()
    assert harness.display_image_queue.items == [["1.jpg"]]
    
    harness.selected_photo_fpaths = []
    harness._clear_photo_grid = MagicMock()
    harness._queue_current_page_for_display()
    assert harness.display_image_queue.items == []
    harness._clear_photo_grid.assert_called_once()

def test_show_previous_page():
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["1.jpg", "2.jpg", "3.jpg"]
    harness.grid_items_per_page = 2
    harness.current_page_index = 1
    
    harness._queue_current_page_for_display = MagicMock()
    harness.show_previous_page()
    assert harness.current_page_index == 0
    harness._queue_current_page_for_display.assert_called_once()

    harness.show_previous_page()
    assert harness.current_page_index == 0 # shouldn't go below 0

def test_show_first_page():
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["1.jpg", "2.jpg", "3.jpg"]
    harness.grid_items_per_page = 2
    harness.current_page_index = 1
    
    harness._queue_current_page_for_display = MagicMock()
    harness.show_first_page()
    assert harness.current_page_index == 0
    harness._queue_current_page_for_display.assert_called_once()

def test_show_next_page():
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["1.jpg", "2.jpg", "3.jpg"]
    harness.grid_items_per_page = 2
    harness.current_page_index = 0
    
    harness._queue_current_page_for_display = MagicMock()
    harness.show_next_page()
    assert harness.current_page_index == 1
    harness._queue_current_page_for_display.assert_called_once()
    
    harness.show_next_page()
    assert harness.current_page_index == 1 # shouldn't exceed max pages

def test_show_last_page():
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["1.jpg", "2.jpg", "3.jpg"]
    harness.grid_items_per_page = 2
    harness.current_page_index = 0
    
    harness._queue_current_page_for_display = MagicMock()
    harness.show_last_page()
    assert harness.current_page_index == 1
    harness._queue_current_page_for_display.assert_called_once()


def test_show_single_photo_in_grid_focuses_photo_from_multi_selection():
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["1.jpg", "2.jpg", "3.jpg"]
    harness.current_page_index = 2
    harness._queue_current_page_for_display = MagicMock()

    harness.show_single_photo_in_grid("2.jpg")

    assert harness.selected_photo_fpaths == ["2.jpg"]
    assert harness.current_page_index == 0
    assert harness._focused_grid_origin_fpaths == ["1.jpg", "2.jpg", "3.jpg"]
    assert harness._focused_grid_origin_page_index == 2
    harness._queue_current_page_for_display.assert_called_once()


def test_restore_grid_after_focus_restores_previous_selection_and_page():
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg"]
    harness.grid_items_per_page = 2
    harness.current_page_index = 2
    harness._queue_current_page_for_display = MagicMock()

    harness.show_single_photo_in_grid("4.jpg")
    harness._queue_current_page_for_display.reset_mock()

    harness.restore_grid_after_focus()

    assert harness.selected_photo_fpaths == ["1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg"]
    assert harness.current_page_index == 2
    assert harness._focused_grid_origin_fpaths is None
    assert harness._focused_grid_origin_page_index == 0
    harness._queue_current_page_for_display.assert_called_once()


def test_show_photo_in_parent_grid_selects_folder_and_targets_photo_page():
    import os
    harness = _DummyHarness()
    harness.grid_items_per_page = 2
    harness._queue_current_page_for_display = MagicMock()
    harness._focused_grid_origin_fpaths = ["old1.jpg", "old2.jpg"]
    harness._focused_grid_origin_page_index = 1

    parent_dir = "folder"
    listing = ["0.jpg", "1.jpg", "2.jpg", "3.jpg", "4.jpg", "5.jpg", "6.jpg"]
    target = os.path.join(parent_dir, "5.jpg")

    harness.tree = MagicMock()
    folder_item = MagicMock()
    harness._find_tree_item = MagicMock(return_value=folder_item)

    with patch("viewer.mixins.photo_grid.os.path.isdir", side_effect=lambda p: p == parent_dir), patch("viewer.mixins.photo_grid.os.listdir", return_value=listing):
        harness.show_photo_in_parent_grid(target)

    assert harness.selected_items == [parent_dir]
    assert harness.selected_photo_fpaths == [os.path.join(parent_dir, name) for name in listing]
    assert harness.current_page_index == 2
    assert harness._focused_grid_origin_fpaths is None
    assert harness._focused_grid_origin_page_index == 0
    harness._queue_current_page_for_display.assert_called_once()
    harness.tree.clearSelection.assert_called_once()
    folder_item.setSelected.assert_called_once_with(True)
    harness.tree.setCurrentItem.assert_called_once_with(folder_item)


def test_update_focus_restore_control_toggles_back_to_grid_button():
    harness = _DummyHarness()
    harness.back_to_grid_button = MagicMock()

    harness.selected_photo_fpaths = ["1.jpg", "2.jpg"]
    harness._focused_grid_origin_fpaths = None
    harness._update_focus_restore_control()
    harness.back_to_grid_button.setVisible.assert_called_with(False)
    harness.back_to_grid_button.setEnabled.assert_called_with(False)

    harness.back_to_grid_button.reset_mock()
    harness.selected_photo_fpaths = ["2.jpg"]
    harness._focused_grid_origin_fpaths = ["1.jpg", "2.jpg", "3.jpg"]
    harness._update_focus_restore_control()
    harness.back_to_grid_button.setVisible.assert_called_with(True)
    harness.back_to_grid_button.setEnabled.assert_called_with(True)


def test_show_single_photo_in_grid_is_noop_when_not_applicable():
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["1.jpg"]
    harness._queue_current_page_for_display = MagicMock()

    harness.show_single_photo_in_grid("1.jpg")
    harness.show_single_photo_in_grid("missing.jpg")

    assert harness.selected_photo_fpaths == ["1.jpg"]
    harness._queue_current_page_for_display.assert_not_called()

def test_map_slots():
    harness = _DummyHarness()
    harness._update_map_slot([(1.0, 2.0), (3.0, 4.0)])
    assert harness.map_widget.set_position.call_count == 2
    
    harness._clear_map_slot()
    harness.map_widget.delete_all_marker.assert_called_once()

def test_map_location_background():
    harness = _DummyHarness()
    harness.map_location_queue = _DummyQueue([[], [(1.0, 2.0)]])
    
    def stop_running(timeout=None):
        harness.running = False
        return harness.WORKER_STOP_SIGNAL
    
    harness.map_location_queue.get = stop_running
    harness.map_location_background()
    # It stops immediately, so testing the loop logic requires a bit more setup
    # Let's mock get
    
    harness.running = True
    queue_returns = [[], [(1.0, 2.0)], Exception("stop")]
    def get_mock(timeout=None):
        val = queue_returns.pop(0)
        if isinstance(val, Exception):
            harness.running = False
            return harness.WORKER_STOP_SIGNAL
        return val
    
    harness.map_location_queue.get = get_mock
    harness.map_location_background()
    
    assert len(harness.signals.clear_map_signal.calls) > 0
    assert len(harness.signals.update_map_signal.calls) > 0

def test_display_image_background():
    harness = _DummyHarness()
    
    queue_returns = [["1.jpg"], Exception("stop")]
    def get_mock(timeout=None):
        val = queue_returns.pop(0)
        if isinstance(val, Exception):
            harness.running = False
            return harness.WORKER_STOP_SIGNAL
        return val
    
    harness.display_image_queue.get = get_mock
    harness.display_image_background()
    assert harness.signals.display_images_signal.calls[0] == ["1.jpg"]


def test_map_location_background_exits_on_queue_empty_after_shutdown_flag():
    harness = _DummyHarness()
    harness.running = False

    def get_mock(timeout=None):
        raise queue.Empty

    harness.map_location_queue.get = get_mock
    harness.map_location_background()

    assert harness.signals.clear_map_signal.calls == []
    assert harness.signals.update_map_signal.calls == []


def test_display_image_background_exits_on_stop_signal_without_emitting():
    harness = _DummyHarness()
    stop_signal = object()
    harness.WORKER_STOP_SIGNAL = stop_signal

    queue_values = [stop_signal]

    def get_mock(timeout=None):
        return queue_values.pop(0)

    harness.display_image_queue.get = get_mock
    harness.display_image_background()

    assert harness.signals.display_images_signal.calls == []


def test_request_zoom_image_load_starts_worker_for_raw_file():
    harness = _DummyHarness()
    label = MagicMock()
    label.property.return_value = False

    with patch("viewer.mixins.photo_grid.threading.Thread") as mock_thread:
        harness._request_zoom_image_load("photo.cr2", label)

    mock_thread.assert_called_once()
    mock_thread.return_value.start.assert_called_once()


def test_request_zoom_image_load_skips_non_raw_file():
    harness = _DummyHarness()
    label = MagicMock()
    label.property.return_value = False

    with patch("viewer.mixins.photo_grid.threading.Thread") as mock_thread:
        harness._request_zoom_image_load("photo.jpg", label)

    mock_thread.assert_not_called()


def test_on_zoom_image_ready_dispatches_to_matching_label():
    harness = _DummyHarness()
    label = MagicMock()
    label.property.return_value = "photo.cr2"
    harness.image_labels = [label]
    harness._zoom_loading_fpaths = {"photo.cr2"}
    harness._apply_zoom_image_to_label = MagicMock()
    container = MagicMock()

    harness._on_zoom_image_ready({"fpath": "photo.cr2", "image_container": container})

    assert "photo.cr2" not in harness._zoom_loading_fpaths
    harness._apply_zoom_image_to_label.assert_called_once_with(label, container)


def test_on_zoom_image_ready_failure_allows_retry():
    harness = _DummyHarness()
    label = MagicMock()
    label.property.side_effect = lambda key: "photo.cr2" if key == "_photo_source_fpath" else None
    harness.image_labels = [label]
    harness._zoom_loading_fpaths = {"photo.cr2"}

    harness._on_zoom_image_ready({"fpath": "photo.cr2", "image_container": None})

    assert "photo.cr2" not in harness._zoom_loading_fpaths
    label.clear_zoom_request_state.assert_called_once()

def test_display_images_slot():
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["1.jpg", "2.jpg"]
    harness.grid_items_per_page = 2
    harness.current_page_index = 0
    
    harness.display_images = MagicMock(return_value=True)
    
    # Matching fpaths
    harness._display_images_slot(["1.jpg", "2.jpg"], _attempt=1)
    harness.display_images.assert_called_with(["1.jpg", "2.jpg"])
    
    # Not matching fpaths
    harness.display_images.reset_mock()
    harness._display_images_slot(["3.jpg"], _attempt=1)
    assert not harness.display_images.called
    
    # display fails
    with patch("viewer.mixins.photo_grid.QTimer") as mock_timer:
        harness.display_images.return_value = False
        harness._display_images_slot(["1.jpg", "2.jpg"], _attempt=0)
        mock_timer.singleShot.assert_called_once()

@patch("viewer.mixins.photo_grid.ZoomablePhotoLabel")
@patch("viewer.mixins.photo_grid.pil_image_to_qpixmap")
def test_display_images(mock_pil_to_pixmap, mock_label_class):
    harness = _DummyHarness()
    harness.photo_frames_width = 800
    harness.photo_frame_height = 600
    
    assert harness.display_images([]) is True
    
    # Image container available
    img_mock = MagicMock()
    img_mock.size = (100, 100)
    img_mock.rotate.return_value = img_mock
    container = ImageContainer(img_mock, {MetaTagName.GPSLatitude: 1.0, MetaTagName.GPSLongitude: 2.0})
    harness.images["1.jpg"] = container
    
    mock_pixmap = MagicMock()
    mock_pixmap.isNull.return_value = False
    mock_pil_to_pixmap.return_value = mock_pixmap
    
    label_instance = mock_label_class.return_value
    label_instance.pixmap.return_value = mock_pixmap
    
    assert harness.display_images(["1.jpg"]) is True
    assert harness.canvas_selected_fpath == "1.jpg"
    assert harness.canvas_currently_displayed_image_fpath == "1.jpg"
    assert harness.canvas_selected_fpath_loaded is True
    assert len(harness.displayed_photos) == 1
    assert len(harness.signals.update_map_signal.calls) > 0
    harness.photo_grid_layout.addWidget.assert_called()
    
    # Image container not available
    harness.images = {}
    harness.photo_grid_layout.reset_mock()
    assert harness.display_images(["2.jpg"]) is False
    label_instance.setText.assert_called_with("Loading")
    harness.photo_grid_layout.addWidget.assert_called()

def test_display_images_photo_frame_size_fallback():
    harness = _DummyHarness()
    harness.photo_frame.width.return_value = 0
    harness.photo_frame.height.return_value = 0
    harness.photo_frames_width = 800
    harness.photo_frame_height = 600
    
    with patch("viewer.mixins.photo_grid.ZoomablePhotoLabel"):
        # Passing 3 images. sqrt(3) is 1.73 -> nb_columns is 2.
        # i=0: column=0. column += 1 -> 1
        # i=1: column=1. column += 1 -> 2
        # i=2: column=2. column >= 2 is TRUE. column=0, row+=1.
        harness.display_images(["1.jpg", "2.jpg", "3.jpg"])


def test_display_images_sets_blowup_action_for_multi_selection(qapp):
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["1.jpg", "2.jpg"]
    harness.photo_frames_width = 800
    harness.photo_frame_height = 600

    img_mock = MagicMock()
    img_mock.size = (100, 100)
    img_mock.rotate.return_value = img_mock
    harness.images["1.jpg"] = ImageContainer(img_mock, {})

    with patch("viewer.mixins.photo_grid.pil_image_to_qpixmap", return_value=QPixmap(20, 20)):
        result = harness.display_images(["1.jpg"])

    assert result is True
    label = harness.image_labels[0]
    assert isinstance(label, ZoomablePhotoLabel)
    assert label._zoom_blowup_button.isHidden() is False


def test_display_images_sets_blowup_action_for_single_selection_parent_grid(qapp):
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["folder\\2.jpg"]
    harness.photo_frames_width = 800
    harness.photo_frame_height = 600
    harness.show_photo_in_parent_grid = MagicMock()

    img_mock = MagicMock()
    img_mock.size = (100, 100)
    img_mock.rotate.return_value = img_mock
    harness.images["folder\\2.jpg"] = ImageContainer(img_mock, {})

    with patch("viewer.mixins.photo_grid.pil_image_to_qpixmap", return_value=QPixmap(20, 20)):
        result = harness.display_images(["folder\\2.jpg"])

    assert result is True
    label = harness.image_labels[0]
    assert label._zoom_blowup_button.isHidden() is False
    assert label._zoom_blowup_button.toolTip() == "Open folder grid"
    label._zoom_blowup_button.click()
    harness.show_photo_in_parent_grid.assert_called_once_with("folder\\2.jpg")


def test_display_images_sets_blowup_action_to_restore_grid_after_focus(qapp):
    harness = _DummyHarness()
    harness.selected_photo_fpaths = ["2.jpg"]
    harness._focused_grid_origin_fpaths = ["1.jpg", "2.jpg", "3.jpg"]
    harness.restore_grid_after_focus = MagicMock()
    harness.photo_frames_width = 800
    harness.photo_frame_height = 600

    img_mock = MagicMock()
    img_mock.size = (100, 100)
    img_mock.rotate.return_value = img_mock
    harness.images["2.jpg"] = ImageContainer(img_mock, {})

    with patch("viewer.mixins.photo_grid.pil_image_to_qpixmap", return_value=QPixmap(20, 20)):
        result = harness.display_images(["2.jpg"])

    assert result is True
    label = harness.image_labels[0]
    assert label._zoom_blowup_button.isHidden() is False
    assert label._zoom_blowup_button.toolTip() == "Back to grid"
    label._zoom_blowup_button.click()
    harness.restore_grid_after_focus.assert_called_once()
