import os
import tempfile
from unittest.mock import patch

from viewer.mixins.config import ConfigMixin
from viewer.mixins.image_loading import ImageLoadingMixin


class _ConfigHarness(ConfigMixin):
    MAX_FILE_SIZE = 10
    SUPPORTED_EXTENSIONS = {".jpg", ".jpeg"}

    def __init__(self):
        self.logger = None


def test_process_dir_replaces_username_placeholder():
    harness = _ConfigHarness()

    with patch.dict(os.environ, {"USERNAME": "alice"}, clear=False):
        with patch("viewer.mixins.config.os.path.exists", return_value=True):
            resolved = harness.process_dir(r"C:\Users\$$$USERNAME$$$\Pictures")

    assert resolved == r"C:\Users\alice\Pictures"


def test_process_dir_returns_none_when_path_missing():
    harness = _ConfigHarness()

    with patch("viewer.mixins.config.os.path.exists", return_value=False):
        resolved = harness.process_dir(r"D:\missing")

    assert resolved is None


def test_get_data_dir_returns_selected_path():
    harness = _ConfigHarness()
    harness.config = {
        "base_dir_labels": ["One", "Two"],
        "base_dirs": ["A", "B"],
        "base_dir_selected_label": "Two",
    }

    with patch.object(harness, "process_dir", return_value=r"D:\photos"):
        selected = harness.get_data_dir()
        selected_index = harness.get_data_dir(get_index=True)

    assert selected == r"D:\photos"
    assert selected_index == 1


def test_is_file_acceptable_respects_size_and_extension():
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(b"12345")
        file_path = tmp.name

    try:
        assert ImageLoadingMixin._is_file_acceptable(
            file_path=file_path,
            max_file_size=10,
            supported_extensions={".jpg", ".jpeg"},
        )
        assert not ImageLoadingMixin._is_file_acceptable(
            file_path=file_path,
            max_file_size=3,
            supported_extensions={".jpg", ".jpeg"},
        )
        assert not ImageLoadingMixin._is_file_acceptable(
            file_path=file_path,
            max_file_size=10,
            supported_extensions={".png"},
        )
    finally:
        os.remove(file_path)


def test_is_file_acceptable_handles_missing_file():
    assert not ImageLoadingMixin._is_file_acceptable(
        file_path=r"D:\does-not-exist.jpg",
        max_file_size=10,
        supported_extensions={".jpg"},
    )
