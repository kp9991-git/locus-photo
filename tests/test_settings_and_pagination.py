import queue
from unittest.mock import patch

from viewer.mixins.tree import TreeMixin
from viewer.mixins.photo_grid import PhotoGridMixin
from viewer.mixins.settings import SettingsMixin


class _SettingsHarness(SettingsMixin):
    DEFAULT_GRID_ITEMS_PER_PAGE = 4
    GRID_ITEMS_PER_PAGE_OPTIONS = [1, 4, 6, 9]

    def __init__(self):
        self.grid_items_per_page = 4
        self.current_page_index = 3
        self.config = {}
        self.logger = None
        self.grid_page_size_actions = {}
        self.queued_for_display = False
        self.saved_config = False

    def _queue_current_page_for_display(self):
        self.queued_for_display = True

    def save_config(self):
        self.saved_config = True


class _PaginationHarness(PhotoGridMixin):
    def __init__(self, fpaths, items_per_page):
        self.selected_photo_fpaths = list(fpaths)
        self.grid_items_per_page = items_per_page
        self.current_page_index = 0
        self.queue_calls = 0

    def _queue_current_page_for_display(self):
        self.queue_calls += 1


class _DummyButton:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = bool(value)


class _DummyLabel:
    def __init__(self):
        self.text = ""

    def setText(self, value):
        self.text = str(value)


class _DummyFrame:
    def __init__(self):
        self.visible = True

    def setVisible(self, value):
        self.visible = bool(value)


class _PaginationControlsHarness(PhotoGridMixin):
    def __init__(self, fpaths, items_per_page):
        self.selected_photo_fpaths = list(fpaths)
        self.grid_items_per_page = items_per_page
        self.current_page_index = 0
        self.pagination_frame = _DummyFrame()
        self.page_status_label = _DummyLabel()
        self.first_page_button = _DummyButton()
        self.prev_page_button = _DummyButton()
        self.next_page_button = _DummyButton()
        self.last_page_button = _DummyButton()
        self.display_image_queue = queue.LifoQueue()
        self.image_load_queue = queue.LifoQueue()


class _DeferredGpsHarness(TreeMixin):
    def __init__(self, generation=1, running=True, items_per_page=4):
        self._gps_scan_generation = generation
        self.running = running
        self.grid_items_per_page = items_per_page
        self.gps_flags_queue = queue.Queue()


class _DummyTreeItem:
    def __init__(self, fpath):
        self._fpath = fpath

    def data(self, _column, _role):
        return self._fpath


class _DummyTree:
    def __init__(self, selected_paths):
        self._selected = [_DummyTreeItem(p) for p in selected_paths]

    def selectedItems(self):
        return list(self._selected)


class _TreeSelectionHarness(TreeMixin):
    def __init__(self, selected_paths, grid_items_per_page=4):
        self.tree = _DummyTree(selected_paths)
        self.selected_items = []
        self.selected_photo_fpaths = []
        self.current_page_index = 99
        self.grid_items_per_page = grid_items_per_page
        self.image_load_queue = queue.LifoQueue()
        self.gps_flags_queue = queue.Queue()
        self.logger = None
        self.queued = False
        self._gps_scan_generation = 0
        self.deferred_gps_paths = None

    def _queue_current_page_for_display(self):
        self.queued = True

    def _start_deferred_gps_scan(self, fpaths):
        self.deferred_gps_paths = list(fpaths)

    def _clear_grid_focus_state(self):
        pass


def test_item_clicked_folder_selection_populates_display_and_preload_queues(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    file_a = folder / "a.jpg"
    file_b = folder / "b.jpg"
    file_a.write_bytes(b"a")
    file_b.write_bytes(b"b")

    harness = _TreeSelectionHarness([str(folder)], grid_items_per_page=4)

    harness.item_clicked()

    expected = {str(file_a), str(file_b)}
    assert set(harness.selected_photo_fpaths) == expected
    assert harness.current_page_index == 0
    assert harness.queued is True

    queued_images = set()
    while not harness.image_load_queue.empty():
        queued_images.add(harness.image_load_queue.get_nowait())
    assert queued_images == expected

    queued_gps = set()
    while not harness.gps_flags_queue.empty():
        queued_gps.add(harness.gps_flags_queue.get_nowait())
    assert queued_gps == expected


def test_item_clicked_folder_selection_limits_initial_image_preload_to_two_pages(tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    files = []
    for i in range(7):
        p = folder / f"{i}.jpg"
        p.write_bytes(b"x")
        files.append(str(p))

    harness = _TreeSelectionHarness([str(folder)], grid_items_per_page=2)

    harness.item_clicked()

    assert len(harness.selected_photo_fpaths) == 7

    queued_images = []
    while not harness.image_load_queue.empty():
        queued_images.append(harness.image_load_queue.get_nowait())
    assert len(queued_images) == 4
    assert set(queued_images).issubset(set(files))

    queued_gps = []
    while not harness.gps_flags_queue.empty():
        queued_gps.append(harness.gps_flags_queue.get_nowait())
    assert len(queued_gps) == 4
    assert set(queued_gps).issubset(set(files))

    assert harness.deferred_gps_paths is not None
    assert len(harness.deferred_gps_paths) == 3
    assert set(harness.deferred_gps_paths).issubset(set(files))


def test_sanitize_grid_items_per_page_uses_default_for_invalid_value():
    assert _SettingsHarness.sanitize_grid_items_per_page("invalid") == 4


def test_sanitize_grid_items_per_page_enforces_minimum_of_one():
    assert SettingsMixin.sanitize_grid_items_per_page(0) == 1
    assert SettingsMixin.sanitize_grid_items_per_page(-5) == 1


def test_set_grid_items_per_page_updates_state_and_persists():
    harness = _SettingsHarness()

    harness._set_grid_items_per_page("6")

    assert harness.grid_items_per_page == 6
    assert harness.current_page_index == 0
    assert harness.queued_for_display is True
    assert harness.saved_config is True
    assert harness.config["grid_items_per_page"] == 6


def test_set_grid_items_per_page_can_skip_persist():
    harness = _SettingsHarness()

    harness._set_grid_items_per_page(9, persist_config=False)

    assert harness.grid_items_per_page == 9
    assert harness.current_page_index == 0
    assert harness.queued_for_display is True
    assert harness.saved_config is False
    assert "grid_items_per_page" not in harness.config


def test_total_pages_is_zero_when_no_selection():
    harness = _PaginationHarness([], items_per_page=4)
    assert harness._get_total_pages() == 0


def test_current_page_fpaths_clamps_index():
    harness = _PaginationHarness(["a", "b", "c", "d", "e"], items_per_page=2)
    harness.current_page_index = 99

    page_fpaths = harness._get_current_page_fpaths()

    assert harness.current_page_index == 2
    assert page_fpaths == ["e"]


def test_show_next_and_previous_page_updates_index_and_queues():
    harness = _PaginationHarness(["a", "b", "c", "d", "e"], items_per_page=2)

    harness.show_next_page()
    harness.show_next_page()
    harness.show_next_page()  # no-op at last page
    harness.show_previous_page()

    assert harness.current_page_index == 1
    assert harness.queue_calls == 3


def test_show_first_and_last_page_updates_index_and_queues():
    harness = _PaginationHarness(["a", "b", "c", "d", "e"], items_per_page=2)
    harness.current_page_index = 1

    harness.show_last_page()
    harness.show_first_page()

    assert harness.current_page_index == 0
    assert harness.queue_calls == 2


def test_update_pagination_controls_for_single_item_hides_controls():
    harness = _PaginationControlsHarness(["a"], items_per_page=4)

    harness._update_pagination_controls()

    assert harness.pagination_frame.visible is False
    assert harness.page_status_label.text == ""
    assert harness.first_page_button.enabled is False
    assert harness.prev_page_button.enabled is False
    assert harness.next_page_button.enabled is False
    assert harness.last_page_button.enabled is False


def test_update_pagination_controls_sets_text_and_button_states():
    harness = _PaginationControlsHarness(["a", "b", "c", "d", "e"], items_per_page=2)
    harness.current_page_index = 1  # page 2 of 3

    harness._update_pagination_controls()

    assert harness.pagination_frame.visible is True
    assert harness.page_status_label.text == "2/3 (5 images)"
    assert harness.first_page_button.enabled is True
    assert harness.prev_page_button.enabled is True
    assert harness.next_page_button.enabled is True
    assert harness.last_page_button.enabled is True


def test_queue_image_preload_window_enqueues_two_pages_from_current_page():
    harness = _PaginationControlsHarness(["a", "b", "c", "d", "e", "f", "g"], items_per_page=2)
    harness.current_page_index = 1

    harness._queue_image_preload_window()

    queued = []
    while not harness.image_load_queue.empty():
        queued.append(harness.image_load_queue.get_nowait())
    assert queued == ["f", "e", "d", "c"]


def test_deferred_enqueue_gps_flags_deduplicates_entries():
    harness = _DeferredGpsHarness(generation=3, running=True, items_per_page=1)

    with patch("viewer.mixins.tree.time.sleep", return_value=None):
        harness._deferred_enqueue_gps_flags(["a.jpg", "a.jpg", "b.jpg"], generation=3)

    queued = []
    while not harness.gps_flags_queue.empty():
        queued.append(harness.gps_flags_queue.get_nowait())
    assert queued == ["a.jpg", "b.jpg"]


def test_deferred_enqueue_gps_flags_stops_on_generation_mismatch():
    harness = _DeferredGpsHarness(generation=4, running=True)

    with patch("viewer.mixins.tree.time.sleep", return_value=None):
        harness._deferred_enqueue_gps_flags(["a.jpg", "b.jpg"], generation=5)

    assert harness.gps_flags_queue.empty()


def test_item_expanded_enqueues_images_and_starts_deferred_gps_scan(tmp_path):
    folder = tmp_path / "expand"
    folder.mkdir()
    file_a = folder / "a.jpg"
    file_b = folder / "b.jpg"
    file_a.write_bytes(b"a")
    file_b.write_bytes(b"b")

    harness = _TreeSelectionHarness([], grid_items_per_page=2)
    harness._populated_dirs = {str(folder)}
    harness.item_expanded(_DummyTreeItem(str(folder)))

    queued_images = set()
    while not harness.image_load_queue.empty():
        queued_images.add(harness.image_load_queue.get_nowait())

    expected = {str(file_a), str(file_b)}
    assert queued_images == expected
    assert set(harness.deferred_gps_paths) == expected
