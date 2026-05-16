"""Tests for BackupManager."""

import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from viewer.metadata.backup_manager import BackupManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def source_file(tmp_path):
    """A real file to be backed up."""
    fpath = tmp_path / "photo.jpg"
    fpath.write_bytes(b"JPEG_CONTENT")
    return str(fpath)


@pytest.fixture()
def backup_dir(tmp_path):
    return str(tmp_path / "backups")


# ── Off mode ──────────────────────────────────────────────────────────────────

def test_off_mode_returns_none(source_file):
    bm = BackupManager(mode="off")
    result = bm.backup_file(source_file)
    assert result is None


def test_off_mode_creates_no_files(source_file, tmp_path):
    bm = BackupManager(mode="off")
    bm.backup_file(source_file)
    # Only the original should exist in tmp_path
    files = [f for f in tmp_path.iterdir() if f.name != "photo.jpg"]
    assert files == []


# ── Same-dir mode ─────────────────────────────────────────────────────────────

def test_same_dir_returns_backup_path(source_file):
    bm = BackupManager(mode="same_dir")
    result = bm.backup_file(source_file)
    assert result is not None
    assert os.path.isfile(result)


def test_same_dir_backup_in_same_directory(source_file):
    bm = BackupManager(mode="same_dir")
    result = bm.backup_file(source_file)
    assert os.path.dirname(result) == os.path.dirname(os.path.abspath(source_file))


def test_same_dir_backup_has_timestamped_name(source_file):
    bm = BackupManager(mode="same_dir")
    result = bm.backup_file(source_file)
    name = os.path.basename(result)
    # e.g. photo_20260516_142233.jpg
    assert name.startswith("photo_")
    assert name.endswith(".jpg")
    suffix = name[len("photo_"):-len(".jpg")]
    assert len(suffix) == len("20260516_142233")
    assert suffix[8] == "_"


def test_same_dir_unique_names_on_two_calls(source_file):
    bm = BackupManager(mode="same_dir")
    with patch("viewer.metadata.backup_manager.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.side_effect = ["20260516_100001", "20260516_100002"]
        r1 = bm.backup_file(source_file)
        r2 = bm.backup_file(source_file)
    assert r1 != r2


def test_same_dir_backup_has_same_content(source_file):
    bm = BackupManager(mode="same_dir")
    result = bm.backup_file(source_file)
    assert open(result, "rb").read() == b"JPEG_CONTENT"


# ── Folder mode ───────────────────────────────────────────────────────────────

def test_folder_mode_returns_backup_path(source_file, backup_dir):
    bm = BackupManager(mode="folder", backup_dir=backup_dir)
    result = bm.backup_file(source_file)
    assert result is not None
    assert os.path.isfile(result)


def test_folder_mode_creates_date_subdirectory(source_file, backup_dir):
    bm = BackupManager(mode="folder", backup_dir=backup_dir)
    with patch("viewer.metadata.backup_manager.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "20260516_142233"
        result = bm.backup_file(source_file)
    assert "2026-05-16" in result


def test_folder_mode_backup_name_contains_time(source_file, backup_dir):
    bm = BackupManager(mode="folder", backup_dir=backup_dir)
    with patch("viewer.metadata.backup_manager.datetime") as mock_dt:
        mock_dt.now.return_value.strftime.return_value = "20260516_142233"
        result = bm.backup_file(source_file)
    assert "142233" in os.path.basename(result)


def test_folder_mode_creates_backup_dir_if_missing(source_file, backup_dir):
    assert not os.path.exists(backup_dir)
    bm = BackupManager(mode="folder", backup_dir=backup_dir)
    bm.backup_file(source_file)
    assert os.path.isdir(backup_dir)


def test_folder_mode_backup_has_same_content(source_file, backup_dir):
    bm = BackupManager(mode="folder", backup_dir=backup_dir)
    result = bm.backup_file(source_file)
    assert open(result, "rb").read() == b"JPEG_CONTENT"


def test_folder_mode_default_backup_dir(source_file):
    """When backup_dir is None, resolves to ~/.locus-photo-backups."""
    bm = BackupManager(mode="folder", backup_dir=None)
    expected_prefix = str(Path.home() / ".locus-photo-backups")
    with patch("shutil.copy2"):
        with patch("os.makedirs"):
            # Just check the path is built without errors
            ts = "20260516_142233"
            dest = bm._build_dest_path(source_file, ts)
    assert dest.startswith(expected_prefix)


# ── Non-file source ───────────────────────────────────────────────────────────

def test_backup_skipped_for_directory(tmp_path):
    bm = BackupManager(mode="same_dir")
    result = bm.backup_file(str(tmp_path))
    assert result is None


def test_backup_skipped_for_nonexistent_path(tmp_path):
    bm = BackupManager(mode="folder", backup_dir=str(tmp_path / "backups"))
    result = bm.backup_file(str(tmp_path / "ghost.jpg"))
    assert result is None


# ── Copy failure ──────────────────────────────────────────────────────────────

def test_copy_failure_returns_none(source_file, backup_dir):
    bm = BackupManager(mode="folder", backup_dir=backup_dir)
    logger = MagicMock()
    bm.logger = logger
    with patch("shutil.copy2", side_effect=OSError("disk full")):
        result = bm.backup_file(source_file)
    assert result is None
    logger.warning.assert_called_once()


def test_copy_failure_does_not_raise(source_file, backup_dir):
    bm = BackupManager(mode="folder", backup_dir=backup_dir)
    with patch("shutil.copy2", side_effect=PermissionError("no write")):
        # Must not raise
        bm.backup_file(source_file)


# ── Unknown mode ──────────────────────────────────────────────────────────────

def test_unknown_mode_falls_back_to_off():
    logger = MagicMock()
    bm = BackupManager(mode="invalid_mode", logger=logger)
    assert bm.mode == "off"
    logger.warning.assert_called_once()


def test_unknown_mode_returns_none(source_file):
    bm = BackupManager(mode="invalid_mode")
    result = bm.backup_file(source_file)
    assert result is None


# ── Properties ────────────────────────────────────────────────────────────────

def test_mode_property():
    bm = BackupManager(mode="same_dir")
    assert bm.mode == "same_dir"


def test_backup_dir_property(backup_dir):
    bm = BackupManager(mode="folder", backup_dir=backup_dir)
    assert bm.backup_dir == backup_dir
