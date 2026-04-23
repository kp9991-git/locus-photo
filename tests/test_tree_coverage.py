import pytest
from unittest.mock import MagicMock, patch
import os
import queue

from PySide6.QtCore import Qt

from viewer.mixins.tree import TreeMixin


class _MockDirEntry:
    def __init__(self, name, parent, is_dir_val):
        self.name = name
        self.path = os.path.join(parent, name)
        self._is_dir = is_dir_val

    def is_dir(self):
        return self._is_dir


class _MockScandir:
    def __init__(self, entries):
        self._entries = entries

    def __enter__(self):
        return iter(self._entries)

    def __exit__(self, exc_type, exc, tb):
        return False

class _DummyQueue:
    def __init__(self):
        self.items = []
        
    def put(self, item, timeout=None):
        self.items.append(item)
        
    def get(self, timeout=None):
        if not self.items:
            raise queue.Empty
        return self.items.pop(0)
        
    def qsize(self):
        return len(self.items)

class _DummySignal:
    def __init__(self):
        self.calls = []
    def emit(self, payload=None):
        self.calls.append(payload)

class _DummySignals:
    def __init__(self):
        self.update_tree_icons = _DummySignal()

class _DummyHarness(TreeMixin):
    def __init__(self):
        self.grid_items_per_page = 2
        self.running = True
        self.gps_flags_queue = _DummyQueue()
        self.image_load_queue = _DummyQueue()
        self.display_image_queue = _DummyQueue()
        self.map_location_queue = _DummyQueue()
        self.logger = MagicMock()
        self._fpath_to_tree_item = {}
        self._populated_dirs = set()
        self.shown_gps_flags = {}
        self.pin_icon = "pin"
        self.cross_icon = "cross"
        self.continue_iter = True
        self.signals = _DummySignals()
        self.exiftool_registry = MagicMock()
        self.tree = MagicMock()
        self.config = {}
        
        self.has_gps_flag_for_file_in_cache = MagicMock(return_value=("fpath", None))
        self.extract_gps_coordinates_and_put_in_cache = MagicMock(return_value=(None, False))
        self.is_file_acceptable = MagicMock(return_value=True)

    def _clear_photo_grid(self): pass
    def _update_pagination_controls(self): pass
    def _queue_current_page_for_display(self): pass
    def _clear_grid_focus_state(self): pass
    def get_data_dir(self): return "data_dir"
    def base_dir_add(self): pass
    def base_dir_remove(self): pass
    def save_config(self): pass

def test_get_image_preload_count():
    harness = _DummyHarness()
    assert harness._get_image_preload_count() == 4
    harness.grid_items_per_page = 0
    assert harness._get_image_preload_count() == 1

def test_get_gps_deferred_backlog_limit():
    harness = _DummyHarness()
    assert harness._get_gps_deferred_backlog_limit() == 32
    harness.grid_items_per_page = 5
    assert harness._get_gps_deferred_backlog_limit() == 40

def test_next_gps_scan_generation():
    harness = _DummyHarness()
    assert getattr(harness, "_gps_scan_generation", 0) == 0
    assert harness._next_gps_scan_generation() == 1
    assert harness._gps_scan_generation == 1

def test_deferred_enqueue_gps_flags():
    harness = _DummyHarness()
    gen = harness._next_gps_scan_generation()
    
    with patch("os.path.isdir", side_effect=lambda x: os.path.basename(x) == "dir"):
        with patch("time.sleep"):
            # normal
            harness._deferred_enqueue_gps_flags(["file1"], gen)
            assert harness.gps_flags_queue.qsize() == 1
            
            # dir
            harness._deferred_enqueue_gps_flags(["dir"], gen)
            assert harness.gps_flags_queue.qsize() == 1
            
            # wrong gen
            harness._deferred_enqueue_gps_flags(["file2"], gen + 1)
            assert harness.gps_flags_queue.qsize() == 1
            
            # not running
            harness.running = False
            harness._deferred_enqueue_gps_flags(["file2"], gen)
            assert harness.gps_flags_queue.qsize() == 1

def test_deferred_enqueue_gps_flags_backlog():
    harness = _DummyHarness()
    harness._get_gps_deferred_backlog_limit = MagicMock(return_value=0) # always full
    gen = harness._next_gps_scan_generation()
    
    with patch("os.path.isdir", return_value=False):
        with patch("time.sleep") as mock_sleep:
            def change_gen(*args, **kwargs):
                harness._gps_scan_generation += 1
            mock_sleep.side_effect = change_gen
            harness.gps_flags_queue.put("dummy")
            
            harness._deferred_enqueue_gps_flags(["file"], gen)
            assert harness.gps_flags_queue.qsize() == 1 # didn't add "file" due to gen change in loop

            harness._next_gps_scan_generation()
            gen = harness._gps_scan_generation
            harness.running = True
            def stop_running(*args, **kwargs):
                harness.running = False
            mock_sleep.side_effect = stop_running
            harness._deferred_enqueue_gps_flags(["file"], gen)
            assert harness.gps_flags_queue.qsize() == 1 # didn't add "file" due to running=False in loop

def test_start_deferred_gps_scan():
    harness = _DummyHarness()
    with patch("os.path.isdir", side_effect=lambda x: os.path.basename(x) == "dir"):
        harness._start_deferred_gps_scan(["dir"])
        assert getattr(harness, "_gps_scan_thread", None) is None
        
        with patch("threading.Thread") as mock_thread:
            harness._start_deferred_gps_scan(["file"])
            mock_thread.assert_called_once()
            mock_thread.return_value.start.assert_called_once()
            assert harness._gps_scan_thread == mock_thread.return_value

def test_find_tree_item():
    harness = _DummyHarness()
    harness._fpath_to_tree_item["/test/file"] = "item"
    assert harness._find_tree_item("/test/file") == "item"
    assert harness._find_tree_item("\\test\\file") == "item"
    assert harness._find_tree_item("missing") is None

def test_tree_exists():
    harness = _DummyHarness()
    harness._fpath_to_tree_item["/test/file"] = "item"
    assert harness._tree_exists("/test/file") is True
    assert harness._tree_exists("missing") is False

def test_tree_iterate_items():
    harness = _DummyHarness()
    
    # Not continue_iter
    harness.continue_iter = False
    harness.tree_iterate_items(None)
    harness.continue_iter = True
    
    # parent is None
    top_item = MagicMock()
    top_item.childCount.return_value = 0
    harness.tree.topLevelItemCount.return_value = 1
    harness.tree.topLevelItem.return_value = top_item
    harness.tree_iterate_items(None)
    
    # parent is not None
    parent = MagicMock()
    parent.childCount.return_value = 1
    child = MagicMock()
    parent.child.return_value = child
    child.data.return_value = "file.jpg"
    
    with patch("os.path.isdir", return_value=False):
        harness.has_gps_flag_for_file_in_cache.return_value = ("file.jpg", True)
        
        # Avoid recursion
        child.childCount.return_value = 0
        
        harness.tree_iterate_items(parent)
        child.setIcon.assert_called_with(0, "pin")
        assert harness.shown_gps_flags["file.jpg"] is True
        
        # Test false flag
        harness.has_gps_flag_for_file_in_cache.return_value = ("file.jpg", False)
        harness.tree_iterate_items(parent)
        child.setIcon.assert_called_with(0, "cross")

        # Test continue_iter goes False in the loop
        parent.childCount.return_value = 2
        def child_side_effect(i):
            if i == 0:
                harness.continue_iter = False
            return child
        parent.child.side_effect = child_side_effect
        harness.continue_iter = True
        harness.tree_iterate_items(parent)
        # Should not process child 1 because continue_iter became False
        assert harness.continue_iter is False
        parent.child.side_effect = None
        parent.childCount.return_value = 1
        harness.continue_iter = True

        # Test exception handling
        child.setIcon.side_effect = Exception("err")
        harness.has_gps_flag_for_file_in_cache.return_value = ("file.jpg", True)
        harness.tree_iterate_items(parent)
        assert harness.logger.error.called

def test_update_tree_icons_slot():
    harness = _DummyHarness()
    
    item = MagicMock()
    harness._fpath_to_tree_item["file1"] = item
    
    # flag True
    harness._update_tree_icons_slot([("file1", True)])
    item.setIcon.assert_called_with(0, "pin")
    
    # flag False
    harness._update_tree_icons_slot([("file1", False)])
    item.setIcon.assert_called_with(0, "cross")
    
    # Missing item
    harness._update_tree_icons_slot([("missing", True)])
    
    # Exception
    item.setIcon.side_effect = Exception("err")
    harness._update_tree_icons_slot([("file1", True)])
    assert harness.logger.error.called

def test_load_file_gps_flags_background():
    harness = _DummyHarness()
    
    # Stop loop after a few gets
    def get_mock(*args, **kwargs):
        if harness.gps_flags_queue.qsize() == 0:
            harness.running = False
            raise queue.Empty
        return harness.gps_flags_queue.items.pop(0)
    harness.gps_flags_queue.get = get_mock
    
    harness.gps_flags_queue.put("unacceptable")
    harness.gps_flags_queue.put("file1")
    harness.gps_flags_queue.put("file2")
    
    def is_acceptable(fpath):
        return fpath != "unacceptable"
    harness.is_file_acceptable.side_effect = is_acceptable
    
    def has_flag(fpath):
        if fpath == "file1":
            return (fpath, None)
        return (fpath, True)
    harness.has_gps_flag_for_file_in_cache.side_effect = has_flag
    
    harness.extract_gps_coordinates_and_put_in_cache.return_value = (False, True)
    
    with patch("viewer.mixins.tree.ExifToolWrapper"):
        harness.load_file_gps_flags_background()
        
    flat_calls = [item for sublist in harness.signals.update_tree_icons.calls for item in sublist]
    assert ("file1", False) in flat_calls
    assert ("file2", True) in flat_calls

def test_load_file_gps_flags_background_exceptions():
    harness = _DummyHarness()
    
    def get_mock(*args, **kwargs):
        harness.running = False
        return "file1"
    harness.gps_flags_queue.get = get_mock
    
    harness.has_gps_flag_for_file_in_cache.return_value = ("file1", None)
    harness.extract_gps_coordinates_and_put_in_cache.side_effect = Exception("err")
    
    with patch("viewer.mixins.tree.ExifToolWrapper"):
        harness.load_file_gps_flags_background()
        
    assert harness.logger.error.called

def test_update_tree():
    harness = _DummyHarness()
    
    with patch("viewer.mixins.tree.QTreeWidgetItem") as mock_item:
        with patch.object(harness, "insert_files") as mock_insert:
            with patch("viewer.mixins.tree.clear_queue") as mock_clear:
                harness.update_tree()
                
                harness.tree.clear.assert_called_once()
                mock_item.assert_called()
                mock_insert.assert_called()
                assert mock_clear.call_count == 4
                mock_item.return_value.setExpanded.assert_called_with(True)
                assert harness.continue_iter is True

def test_insert_files():
    harness = _DummyHarness()

    entries = [
        _MockDirEntry("file1", "path", False),
        _MockDirEntry("dir1", "path", True),
    ]
    with patch("os.path.exists", return_value=True):
        with patch("os.scandir", return_value=_MockScandir(entries)):
            with patch("viewer.mixins.tree.QTreeWidgetItem") as mock_item:
                harness.insert_files("path", "parent")

                # 2 items created
                assert mock_item.call_count == 2
                assert len(harness._fpath_to_tree_item) == 2

def test_insert_files_not_exists():
    harness = _DummyHarness()
    with patch("os.path.exists", return_value=False):
        harness.insert_files("path", "parent")
        assert len(harness._fpath_to_tree_item) == 0


def test_safe_listdir_permission_error_returns_empty_and_logs_warning():
    harness = _DummyHarness()

    with patch("os.listdir", side_effect=PermissionError("denied")):
        result = harness._safe_listdir("restricted", context_label="expanding tree item")

    assert result == []
    harness.logger.warning.assert_called_once_with(
        "Could not list directory %s while %s",
        "restricted",
        "expanding tree item",
        exc_info=True,
    )

def test_item_clicked():
    harness = _DummyHarness()
    
    item1 = MagicMock()
    item1.data.return_value = "file1"
    item2 = MagicMock()
    item2.data.return_value = "dir1"
    
    harness.tree.selectedItems.return_value = [item1, item2]
    
    harness.ADD_DIR_LABEL = "add"
    
    with patch("os.path.isdir", side_effect=lambda x: os.path.basename(x) == "dir1"):
        with patch("os.listdir", return_value=["file2"]):
            with patch.object(harness, "_start_deferred_gps_scan") as mock_deferred:
                harness.item_clicked()
                
                assert harness.selected_items == ["file1", "dir1"]
                assert harness.selected_photo_fpaths == ["file1", os.path.join("dir1", "file2")]
                assert harness.image_load_queue.qsize() == 2
                assert harness.gps_flags_queue.qsize() == 2
                mock_deferred.assert_called_with([])
                assert harness.current_page_index == 0

def test_item_expanded():
    harness = _DummyHarness()

    item = MagicMock()
    item.data.return_value = "dir1"
    harness._populated_dirs = {"dir1"}

    with patch("os.path.isdir", side_effect=lambda x: os.path.basename(x) == "dir1"):
        with patch("os.listdir", return_value=["file1"]):
            with patch.object(harness, "_start_deferred_gps_scan") as mock_deferred:
                harness.item_expanded(item)

                assert harness.image_load_queue.qsize() == 1
                mock_deferred.assert_called_with([os.path.join("dir1", "file1")])


def test_item_expanded_populates_on_first_expand():
    harness = _DummyHarness()
    harness._populated_dirs = set()

    item = MagicMock()
    item.data.return_value = "dir1"

    entries = [_MockDirEntry("file1", "dir1", False)]
    with patch("os.path.isdir", side_effect=lambda x: os.path.basename(x) == "dir1"):
        with patch("os.path.exists", return_value=True):
            with patch("os.scandir", return_value=_MockScandir(entries)):
                with patch("viewer.mixins.tree.QTreeWidgetItem"):
                    with patch.object(harness, "_start_deferred_gps_scan") as mock_deferred:
                        harness.item_expanded(item)

                        assert harness.image_load_queue.qsize() == 1
                        mock_deferred.assert_called_with([os.path.join("dir1", "file1")])
                        assert "dir1" in harness._populated_dirs

def test_item_expanded_no_dir():
    harness = _DummyHarness()
    item = MagicMock()
    item.data.return_value = "file1"
    
    with patch("os.path.isdir", return_value=False):
        with patch.object(harness, "_start_deferred_gps_scan") as mock_deferred:
            harness.item_expanded(item)
            assert not mock_deferred.called


def test_insert_files_listdir_permission_error_is_handled():
    harness = _DummyHarness()

    with patch("os.path.exists", return_value=True):
        with patch("os.scandir", side_effect=PermissionError("denied")):
            harness.insert_files("restricted", "parent")

    assert harness.logger.warning.called
    assert len(harness._fpath_to_tree_item) == 0


def test_item_clicked_listdir_permission_error_is_handled():
    harness = _DummyHarness()

    item1 = MagicMock()
    item1.data.return_value = "dir1"
    harness.tree.selectedItems.return_value = [item1]

    with patch("os.path.isdir", side_effect=lambda x: os.path.basename(x) == "dir1"):
        with patch("os.listdir", side_effect=PermissionError("denied")):
            with patch.object(harness, "_start_deferred_gps_scan") as mock_deferred:
                harness.item_clicked()

    assert harness.logger.warning.called
    assert harness.selected_photo_fpaths == []
    mock_deferred.assert_called_with([])


def test_item_expanded_listdir_permission_error_is_handled():
    harness = _DummyHarness()
    harness._populated_dirs = {"dir1"}
    item = MagicMock()
    item.data.return_value = "dir1"

    with patch("os.path.isdir", side_effect=lambda x: os.path.basename(x) == "dir1"):
        with patch("os.listdir", side_effect=PermissionError("denied")):
            with patch.object(harness, "_start_deferred_gps_scan") as mock_deferred:
                harness.item_expanded(item)

    assert harness.logger.warning.called
    assert harness.image_load_queue.qsize() == 0
    mock_deferred.assert_called_with([])

def test_select_combobox():
    harness = _DummyHarness()
    harness.ADD_DIR_LABEL = "+ Add directory"
    harness.REMOVE_DIR_LABEL = "- Remove directory"
    
    harness.base_dir_add = MagicMock()
    harness.select_combobox(harness.ADD_DIR_LABEL)
    harness.base_dir_add.assert_called_once()
    
    harness.base_dir_remove = MagicMock()
    harness.select_combobox(harness.REMOVE_DIR_LABEL)
    harness.base_dir_remove.assert_called_once()
    
    harness.update_tree = MagicMock()
    harness.select_combobox("Other")
    assert harness.config['base_dir_selected_label'] == "Other"
    harness.update_tree.assert_called_once()

def test_item_clicked_deferred_dir():
    harness = _DummyHarness()
    
    item1 = MagicMock()
    item1.data.return_value = "dir1"
    
    harness.tree.selectedItems.return_value = [item1]
    
    with patch("os.path.isdir", side_effect=lambda x: os.path.basename(x) == "dir1"):
        with patch("os.listdir", return_value=["file1"]):
            with patch.object(harness, "_start_deferred_gps_scan") as mock_deferred:
                # Force os.path.isdir to return True for the deferred scan check
                # Note: This is an edge case, we'll mock os.path.isdir just for the all_gps_candidates loop
                original_isdir = os.path.isdir
                
                def mocked_isdir(p):
                    if p.endswith("file1"):
                        return True
                    return os.path.basename(p) == "dir1"
                    
                with patch("os.path.isdir", side_effect=mocked_isdir):
                    # We have to bypass the first loop isdir to populate fpaths_to_load
                    # Let's just mock os.path.isdir directly in the flow
                    pass
                
                # It's easier to just mock os.path.isdir to return True conditionally
                # Since all_gps_candidates = ["dir1/file1" or "dir1\\file1"], we want isdir to be True there,
                # but False in the first loop.
                call_counts = [0]
                def custom_isdir(p):
                    if p.endswith("file1"):
                        call_counts[0] += 1
                        if call_counts[0] == 1:
                            return False # First loop: not a dir -> append to fpaths_to_load
                        return True # Second loop: is a dir -> hit `continue` at line 245
                    return os.path.basename(p) == "dir1"
                
                with patch("os.path.isdir", side_effect=custom_isdir):
                    harness.item_clicked()
                    # It should continue, so it shouldn't be added to deferred_gps_paths or priority_set (gps_flags_queue)
                    assert harness.gps_flags_queue.qsize() == 0
                    mock_deferred.assert_called_with([])
