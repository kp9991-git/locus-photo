import pytest
from unittest.mock import MagicMock, patch
import os
from pathlib import Path
import sys

from viewer.mixins.config import ConfigMixin
import viewer.mixins.config as config_mixin

class _DummyHarness(ConfigMixin):
    MAX_FILE_SIZE = 1000
    SUPPORTED_EXTENSIONS = [".jpg"]
    ADD_DIR_LABEL = "+ Add directory"
    REMOVE_DIR_LABEL = "- Remove directory"

    def __init__(self):
        self.logger = MagicMock()
        self.config = {
            'base_dir_labels': ['Dir1', 'Dir2'],
            'base_dirs': ['/path/to/dir1', '/path/to/dir2'],
            'base_dir_selected_label': 'Dir1'
        }
        self.root = MagicMock()
        self.combobox = MagicMock()
        
    def update_tree(self):
        pass

def test_process_dir_pictures_windows(monkeypatch):
    harness = _DummyHarness()
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\test")
    
    with patch("viewer.mixins.config.platform.system", return_value="Windows"):
        with patch("viewer.mixins.config.os.path.exists", return_value=True) as mock_exists:
            res = harness.process_dir("$$$PICTURES$$$")
            assert "Pictures" in res
            
        with patch("viewer.mixins.config.os.path.exists") as mock_exists:
            # First call for Pictures, second for OneDrive/Pictures, third for final res check
            mock_exists.side_effect = [False, True, True]
            res = harness.process_dir("$$$PICTURES$$$")
            assert "OneDrive" in res
            assert "Pictures" in res

def test_process_dir_pictures_mac_linux():
    harness = _DummyHarness()
    with patch("viewer.mixins.config.platform.system", return_value="Linux"):
        with patch("viewer.mixins.config.os.path.exists", return_value=True):
            res = harness.process_dir("$$$PICTURES$$$")
            assert "Pictures" in res

    with patch("viewer.mixins.config.platform.system", return_value="Darwin"):
        with patch("viewer.mixins.config.os.path.exists", return_value=True):
            res = harness.process_dir("$$$PICTURES$$$")
            assert "Pictures" in res

def test_process_dir_pictures_unknown():
    harness = _DummyHarness()
    with patch("viewer.mixins.config.platform.system", return_value="Unknown"):
        with patch("viewer.mixins.config.os.path.exists", return_value=False):
            res = harness.process_dir("$$$PICTURES$$$")
            assert res is None
            assert harness.logger.error.called

def test_process_dir_username(monkeypatch):
    harness = _DummyHarness()
    monkeypatch.setenv("USERNAME", "testuser")
    
    with patch("viewer.mixins.config.os.path.exists", return_value=True):
        res = harness.process_dir("/home/$$$USERNAME$$$/docs")
        assert res == "/home/testuser/docs"
        
    with patch("viewer.mixins.config.os.path.exists", return_value=False):
        res = harness.process_dir("/home/$$$USERNAME$$$/docs")
        assert res is None

def test_process_dir_normal():
    harness = _DummyHarness()
    with patch("viewer.mixins.config.os.path.exists", return_value=True):
        res = harness.process_dir("/normal/path")
        assert res == "/normal/path"

def test_get_config_fpath():
    with patch("viewer.mixins.config.os.path.exists", return_value=True):
        # exists in home
        assert ConfigMixin.get_config_fpath() is not None

    with patch("viewer.mixins.config.os.path.exists", side_effect=[False, False]):
        with patch("viewer.mixins.config.shutil.copy") as mock_copy:
            # doesn't exist, frozen
            with patch("viewer.mixins.config.sys", frozen=True, _MEIPASS="/frozen/path"):
                res = ConfigMixin.get_config_fpath(copy_local=True)
                mock_copy.assert_called_once()
                assert ".yaml" in res
                
    with patch("viewer.mixins.config.os.path.exists", side_effect=[False, True]):
        with patch("viewer.mixins.config.shutil.copy") as mock_copy:
            # doesn't exist, not frozen, copy local succeeds
            with patch("viewer.mixins.config.sys", frozen=False):
                res = ConfigMixin.get_config_fpath(copy_local=True)
                mock_copy.assert_called_once()
                assert ".yaml" in res

def test_is_file_acceptable():
    class DummyClass:
        MAX_FILE_SIZE = 1000
        SUPPORTED_EXTENSIONS = [".jpg"]
    
    with patch("viewer.mixins.config.os.path.getsize", return_value=500):
        assert ConfigMixin.is_file_acceptable.__func__(DummyClass, "test.jpg") is True
        assert ConfigMixin.is_file_acceptable.__func__(DummyClass, "test.png") is False
        
    with patch("viewer.mixins.config.os.path.getsize", return_value=1500):
        assert ConfigMixin.is_file_acceptable.__func__(DummyClass, "test.jpg") is False
        
    with patch("viewer.mixins.config.os.path.getsize", side_effect=OSError("err")):
        assert ConfigMixin.is_file_acceptable.__func__(DummyClass, "test.jpg") is False

def test_save_config():
    harness = _DummyHarness()
    harness.get_config_fpath = MagicMock(return_value="test.yaml")
    
    with patch("builtins.open", MagicMock()) as mock_open:
        with patch("viewer.mixins.config.yaml.dump") as mock_dump:
            with patch("viewer.mixins.config.os.replace") as mock_replace:
                harness.save_config()
                mock_dump.assert_called_once()
                mock_replace.assert_called_once_with("test.yaml.tmp", "test.yaml")

def test_get_data_dir():
    harness = _DummyHarness()
    harness.process_dir = MagicMock(side_effect=lambda x: x)
    
    # get_index = False
    assert harness.get_data_dir() == '/path/to/dir1'
    
    # get_index = True
    assert harness.get_data_dir(get_index=True) == 0
    
    # Not found
    harness.config['base_dir_selected_label'] = 'Unknown'
    with pytest.raises(ValueError):
        harness.get_data_dir()

def test_get_combobox_items():
    harness = _DummyHarness()
    items = harness.get_combobox_items()
    assert items == ['Dir1', 'Dir2', '+ Add directory', '- Remove directory']

def test_base_dir_add():
    harness = _DummyHarness()
    harness.update_tree = MagicMock()
    harness.save_config = MagicMock()
    
    with patch("viewer.mixins.config.QFileDialog.getExistingDirectory", return_value="/new/dir/path"):
        with patch("viewer.mixins.config.os.path.basename", return_value="Dir1"): # simulate collision
            harness.base_dir_add()
            
            assert len(harness.config['base_dirs']) == 3
            assert harness.config['base_dir_labels'][-1] == "Dir1 (1)"
            assert harness.config['base_dir_selected_label'] == "Dir1 (1)"
            
            harness.combobox.blockSignals.assert_called()
            harness.combobox.clear.assert_called()
            harness.combobox.addItems.assert_called_with(['Dir1', 'Dir2', 'Dir1 (1)', '+ Add directory', '- Remove directory'])
            harness.combobox.setCurrentText.assert_called_with("Dir1 (1)")
            harness.update_tree.assert_called()
            harness.save_config.assert_called()
            
    with patch("viewer.mixins.config.QFileDialog.getExistingDirectory", return_value=""): # Empty path
        harness.base_dir_add() # Shouldn't crash

def test_base_dir_remove():
    harness = _DummyHarness()
    harness.update_tree = MagicMock()
    harness.save_config = MagicMock()
    
    harness.get_data_dir = MagicMock(return_value=1) # remove Dir2
    harness.base_dir_remove()
    
    assert len(harness.config['base_dirs']) == 1
    assert harness.config['base_dir_labels'] == ['Dir1']
    assert harness.config['base_dir_selected_label'] == 'Dir1'
    
    harness.combobox.blockSignals.assert_called()
    harness.combobox.clear.assert_called()
    harness.combobox.addItems.assert_called()
    harness.combobox.setCurrentText.assert_called_with("Dir1")
    harness.update_tree.assert_called()
    harness.save_config.assert_called()
    
    # Removing when only 1 left should do nothing
    harness.update_tree.reset_mock()
    harness.base_dir_remove()
    assert not harness.update_tree.called