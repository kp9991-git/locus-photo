"""BackupManager — creates timestamped copies of files before GPS metadata writes."""

import os
import shutil
from datetime import datetime
from pathlib import Path


VALID_MODES = ("off", "same_dir", "folder")


class BackupManager:
    """Creates a timestamped backup of a file before it is modified in-place.

    Modes
    -----
    ``"off"``
        No backup is made.
    ``"same_dir"``
        The backup is placed next to the original:
        ``<stem>_<YYYYMMDD_HHMMSS><ext>``
    ``"folder"``
        The backup is placed under *backup_dir* in a ``YYYY-MM-DD`` subfolder:
        ``<backup_dir>/<YYYY-MM-DD>/<stem>_<HHMMSS><ext>``

    All copy errors are caught, logged as warnings, and swallowed — a failed
    backup never blocks the write operation.
    """

    def __init__(self, mode: str = "off", backup_dir: str | None = None, logger=None):
        if mode not in VALID_MODES:
            if logger:
                logger.warning(
                    "Unknown backup mode %r — falling back to 'off'. Valid modes: %s",
                    mode,
                    VALID_MODES,
                )
            mode = "off"
        self._mode = mode
        self._backup_dir = backup_dir
        self.logger = logger

    # ── Public API ────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def backup_dir(self) -> str | None:
        return self._backup_dir

    def backup_file(self, fpath: str) -> str | None:
        """Copy *fpath* to a timestamped backup location.

        Returns the backup path on success, ``None`` if the mode is ``"off"``
        or if the copy could not be completed.
        """
        if self._mode == "off":
            return None

        if not os.path.isfile(fpath):
            if self.logger:
                self.logger.warning("Backup skipped: source is not a file: %s", fpath)
            return None

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            dest = self._build_dest_path(fpath, ts)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(fpath, dest)
            if self.logger:
                self.logger.info("Backup created: %s -> %s", fpath, dest)
            return dest
        except Exception:
            if self.logger:
                self.logger.warning(
                    "Backup failed for %s — continuing with write",
                    fpath,
                    exc_info=True,
                )
            return None

    # ── Internal helpers ──────────────────────────────────────────────

    def _build_dest_path(self, fpath: str, ts: str) -> str:
        stem, ext = os.path.splitext(os.path.basename(fpath))
        if self._mode == "same_dir":
            dest_dir = os.path.dirname(os.path.abspath(fpath))
            dest_name = "{}_{}{}".format(stem, ts, ext)
            return os.path.join(dest_dir, dest_name)

        # folder mode
        date_part = ts[:8]          # YYYYMMDD
        time_part = ts[9:]          # HHMMSS
        formatted_date = "{}-{}-{}".format(date_part[:4], date_part[4:6], date_part[6:])
        dest_dir = os.path.join(self._resolve_backup_dir(), formatted_date)
        dest_name = "{}_{}{}".format(stem, time_part, ext)
        return os.path.join(dest_dir, dest_name)

    def resolved_backup_dir(self) -> str:
        """Return the effective backup directory (expands ``~``, applies default)."""
        if self._backup_dir:
            return os.path.expanduser(self._backup_dir)
        return str(Path.home() / ".locus-photo-backups")

    # keep old name as alias for internal callers
    _resolve_backup_dir = resolved_backup_dir
