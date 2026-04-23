"""Mixin providing all GPS editing operations for MainApp."""

import os
import threading
from typing import Tuple

import pyperclip

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence

from viewer.core.logging_config import lock
from viewer.core.enums import MetaTagName
from viewer.metadata.exiftool_wrapper import ExifToolWrapper


class GpsOperationsMixin:
    """GPS editing methods mixed into MainApp.
    """

    # ── Shortcuts ─────────────────────────────────────────────────────

    def _setup_gps_shortcuts(self):
        self.undo_gps_action = QAction("Undo GPS edit", self.root)
        self.undo_gps_action.setShortcuts([
            QKeySequence(QKeySequence.StandardKey.Undo),
            QKeySequence("Ctrl+Z"),
        ])
        self.undo_gps_action.triggered.connect(self.undo_last_gps_edit)
        self.root.addAction(self.undo_gps_action)

        self.redo_gps_action = QAction("Redo GPS edit", self.root)
        self.redo_gps_action.setShortcuts([
            QKeySequence(QKeySequence.StandardKey.Redo),
            QKeySequence("Ctrl+Y"),
            QKeySequence("Ctrl+Shift+Z"),
        ])
        self.redo_gps_action.triggered.connect(self.redo_last_gps_edit)
        self.root.addAction(self.redo_gps_action)

    def _update_gps_history_controls(self):
        can_undo = len(self.gps_undo_stack) > 0
        can_redo = len(self.gps_redo_stack) > 0

        if self.undo_gps_button is not None:
            self.undo_gps_button.setEnabled(can_undo)
        if self.redo_gps_button is not None:
            self.redo_gps_button.setEnabled(can_redo)
        if self.undo_gps_action is not None:
            self.undo_gps_action.setEnabled(can_undo)
        if self.redo_gps_action is not None:
            self.redo_gps_action.setEnabled(can_redo)

    # ── Cache helpers ─────────────────────────────────────────────────

    def has_gps_flag_for_file_in_cache(self, fpath) -> Tuple[str, bool]:
        if fpath in self.has_gps_flags:
            return fpath, self.has_gps_flags[fpath]
        elif fpath.replace("\\", "/") in self.has_gps_flags:
            return fpath.replace("\\", "/"), self.has_gps_flags[fpath.replace("\\", "/")]
        else:
            return fpath, None

    def extract_gps_coordinates_and_put_in_cache(self, fpath, exiftool_local=None):
        if exiftool_local is None:
            exiftool_local = self.exiftool
        if os.path.isdir(fpath):
            if self.logger:
                self.logger.debug("Reading GPS flags for directory file {}".format(fpath))
            res = exiftool_local.get_meta_data(fpath, tags=[MetaTagName.GPSLatitude, MetaTagName.GPSLongitude], recursive=True)
            keys = list(res.keys())
            flags = [len(res[k]) > 0 for k in keys]
            with lock:
                for k, f in zip(keys, flags):
                    self.has_gps_flags[k] = f
            return False, True
        else:
            if self.logger:
                self.logger.debug("Reading GPS flags from file {}".format(fpath))
            if not self.is_file_acceptable(fpath):
                if self.logger:
                    self.logger.debug("Skipping unsupported file for GPS cache update: %s", fpath)
                return False, True
            gps_position = exiftool_local.get_meta_data(fpath, tags=[MetaTagName.GPSLatitude, MetaTagName.GPSLongitude])
            gps_position_for_fpath = gps_position.get(fpath)
            if gps_position_for_fpath is None:
                if self.logger:
                    self.logger.debug("No GPS data for file {}".format(fpath))
                res = False
            else:
                res = len(gps_position_for_fpath) > 0
                with lock:
                    self.has_gps_flags[fpath] = res
            return res, True

    def update_has_gps_flag(self, fpath):
        res, updated = self.extract_gps_coordinates_and_put_in_cache(fpath)
        tree_item = self._find_tree_item(fpath)
        if tree_item:
            if res:
                tree_item.setIcon(0, self.pin_icon)
            else:
                tree_item.setIcon(0, self.cross_icon)

    # ── Tag helpers ───────────────────────────────────────────────────

    def _normalize_gps_tags(self, tags):
        normalized_tags = {}
        if not isinstance(tags, dict):
            return normalized_tags
        for tag in self.GPS_TAGS:
            value = tags.get(tag)
            if value is None:
                continue
            try:
                normalized_tags[tag] = float(value)
            except (TypeError, ValueError):
                if self.logger:
                    self.logger.info("Skipping invalid GPS value {} for {}".format(value, tag.name))
        return normalized_tags

    def _read_gps_tags(self, fpath, exiftool_instance=None):
        if exiftool_instance is None:
            exiftool_instance = self.exiftool
        try:
            gps_position = exiftool_instance.get_meta_data(fpath, tags=list(self.GPS_TAGS))
        except Exception as e:
            if self.logger:
                self.logger.error("Failed to read GPS tags for %s", fpath, exc_info=True)
            return {}
        gps_for_fpath = gps_position.get(fpath)
        if gps_for_fpath is None:
            gps_for_fpath = gps_position.get(fpath.replace("\\", "/"))
        if gps_for_fpath is None and len(gps_position) == 1:
            gps_for_fpath = next(iter(gps_position.values()))
        return self._normalize_gps_tags(gps_for_fpath)

    def _apply_gps_tags(self, fpath, tags, exiftool_instance=None):
        if exiftool_instance is None:
            exiftool_instance = self.exiftool
        normalized_tags = self._normalize_gps_tags(tags)
        exiftool_instance.apply_meta_data(
            fpath,
            tags=normalized_tags,
            clear_tags=list(self.GPS_TAGS),
        )
        return normalized_tags

    def _parse_clipboard_gps(self, clipboard):
        gps_data = [item for item in clipboard.replace(',', ' ').split() if item]
        altitude = None
        if len(gps_data) == 3:
            altitude_str, latitude_str, longitude_str = gps_data
        elif len(gps_data) == 2:
            altitude_str = None
            latitude_str, longitude_str = gps_data
        else:
            return None

        try:
            latitude = float(latitude_str)
        except (TypeError, ValueError):
            if self.logger:
                self.logger.info("Latitude {} is not in the numerical format".format(latitude_str))
            return None

        try:
            longitude = float(longitude_str)
        except (TypeError, ValueError):
            if self.logger:
                self.logger.info("Longitude {} is not in the numerical format".format(longitude_str))
            return None

        if altitude_str is not None:
            try:
                altitude = float(altitude_str)
            except (TypeError, ValueError):
                if self.logger:
                    self.logger.info("Altitude {} is not in the numerical format".format(altitude_str))

        tags = {
            MetaTagName.GPSLatitude: latitude,
            MetaTagName.GPSLongitude: longitude,
        }
        if altitude is not None:
            tags[MetaTagName.GPSAltitude] = altitude
        return tags

    def _gps_logs_redacted(self):
        return bool(getattr(self, "log_redact_gps", True))

    def _safe_gps_value_for_log(self, value):
        if value is None:
            return None
        if self._gps_logs_redacted():
            return "<redacted>"
        return value

    def _format_gps_tags_for_log(self, tags):
        if not isinstance(tags, dict):
            return {}
        formatted = {}
        for tag, value in tags.items():
            tag_name = tag.name if isinstance(tag, MetaTagName) else str(tag)
            formatted[tag_name] = self._safe_gps_value_for_log(value)
        return formatted

    def _iter_selected_files_for_gps_edit(self):
        for fpath in self.selected_items:
            if os.path.isdir(fpath):
                continue
            if not self.is_file_acceptable(fpath):
                if self.logger:
                    self.logger.info("Skipping unsupported file {}".format(fpath))
                continue
            yield fpath

    # ── History ───────────────────────────────────────────────────────

    def _record_gps_history_entry(self, label, changes):
        effective_changes = []
        for change in changes:
            before = self._normalize_gps_tags(change.get("before", {}))
            after = self._normalize_gps_tags(change.get("after", {}))
            if before != after:
                effective_changes.append({
                    "fpath": change["fpath"],
                    "before": before,
                    "after": after,
                })

        if len(effective_changes) == 0:
            if self.logger:
                self.logger.info("No GPS changes to store in history")
            return

        self._append_gps_history_entry(self.gps_undo_stack, {
            "label": label,
            "changes": effective_changes,
        })
        self.gps_redo_stack.clear()
        self._update_gps_history_controls()

    def _append_gps_history_entry(self, stack, history_entry):
        stack.append(history_entry)
        limit = getattr(self, "GPS_HISTORY_LIMIT", 0)
        if isinstance(limit, int) and limit > 0:
            while len(stack) > limit:
                stack.pop(0)

    def _apply_gps_history_entry(self, history_entry, apply_after_state):
        state_key = "after" if apply_after_state else "before"
        selected_fpaths = set(self.selected_items)
        selected_locations = []
        changed_selected_item = False

        for change in history_entry["changes"]:
            fpath = change["fpath"]
            tags = change.get(state_key, {})
            try:
                applied_tags = self._apply_gps_tags(fpath, tags)
                self.update_has_gps_flag(fpath)
                self.refresh_file(fpath)
                if fpath in selected_fpaths:
                    changed_selected_item = True
                    if MetaTagName.GPSLatitude in applied_tags and MetaTagName.GPSLongitude in applied_tags:
                        selected_locations.append((applied_tags[MetaTagName.GPSLatitude], applied_tags[MetaTagName.GPSLongitude]))
            except Exception as e:
                if self.logger:
                    self.logger.error("Failed to apply GPS history to %s", fpath, exc_info=True)

        if changed_selected_item:
            self.signals.clear_map_signal.emit()
            if len(selected_locations) > 0:
                self.signals.update_map_signal.emit(selected_locations)

    # ── Busy state ────────────────────────────────────────────────────

    def _set_gps_operation_busy(self, busy):
        self.gps_write_in_progress = busy

        if self.copy_to_clipboard_button is not None:
            self.copy_to_clipboard_button.setEnabled(not busy)
        if self.paste_from_clipboard_button is not None:
            self.paste_from_clipboard_button.setEnabled(not busy)

        if busy:
            if self.undo_gps_button is not None:
                self.undo_gps_button.setEnabled(False)
            if self.redo_gps_button is not None:
                self.redo_gps_button.setEnabled(False)
            if self.undo_gps_action is not None:
                self.undo_gps_action.setEnabled(False)
            if self.redo_gps_action is not None:
                self.redo_gps_action.setEnabled(False)
            if self.root is not None:
                self.root.setCursor(Qt.CursorShape.WaitCursor)
        else:
            self._update_gps_history_controls()
            if self.root is not None:
                self.root.unsetCursor()

    # ── Read metadata (background thread) ────────────────────────────

    def _start_gps_read(self, read_kind, fpath, map_position=None):
        if self.gps_write_in_progress:
            if self.logger:
                self.logger.info("Cannot read GPS while write operation is in progress")
            return

        if getattr(self, "gps_read_in_progress", False):
            if self.logger:
                self.logger.info("GPS read operation already in progress")
            return

        if not fpath:
            if self.logger:
                self.logger.info("GPS read skipped: no file path provided (read_kind=%s)", read_kind)
            return

        self.gps_read_in_progress = True
        worker_thread = threading.Thread(
            target=self._run_gps_read,
            args=(read_kind, fpath, map_position),
            daemon=True,
        )
        worker_thread.start()

    def _run_gps_read(self, read_kind, fpath, map_position=None):
        result = {
            "read_kind": read_kind,
            "fpath": fpath,
            "gps_tags": {},
            "map_position": map_position,
            "error": None,
        }
        exiftool_local = ExifToolWrapper(logger=self.logger)

        try:
            gps_position = exiftool_local.get_meta_data(
                fpath,
                tags=[MetaTagName.GPSAltitude, MetaTagName.GPSLatitude, MetaTagName.GPSLongitude],
            )
            gps_for_fpath = gps_position.get(fpath)
            if gps_for_fpath is None:
                gps_for_fpath = gps_position.get(fpath.replace("\\", "/"))
            if gps_for_fpath is None and len(gps_position) == 1:
                gps_for_fpath = next(iter(gps_position.values()))
            result["gps_tags"] = self._normalize_gps_tags(gps_for_fpath)
        except Exception as e:
            result["error"] = str(e)
            if self.logger:
                self.logger.error("Failed to read GPS metadata for %s", fpath, exc_info=True)
        finally:
            try:
                exiftool_local.terminate()
            except Exception:
                pass

            gps_read_signal = getattr(self.signals, "gps_read_completed", None)
            if gps_read_signal is not None:
                gps_read_signal.emit(result)
            else:
                self._on_gps_read_completed(result)

    def _copy_gps_to_clipboard_from_tags(self, fpath, pos, map_position=None):
        map_latitude = None
        map_longitude = None
        if isinstance(map_position, (tuple, list)) and len(map_position) == 2:
            try:
                map_latitude = float(map_position[0])
                map_longitude = float(map_position[1])
            except (TypeError, ValueError):
                map_latitude = None
                map_longitude = None

        if map_latitude is None or map_longitude is None:
            try:
                map_latitude, map_longitude = self.map_widget.get_position()
            except Exception:
                map_latitude, map_longitude = 0.0, 0.0

        latitude = pos.get(MetaTagName.GPSLatitude)
        longitude = pos.get(MetaTagName.GPSLongitude)
        altitude = pos.get(MetaTagName.GPSAltitude)

        if latitude is None or longitude is None:
            clipboard_value = "{}, {}".format(map_latitude, map_longitude)
            log_message = (
                "No GPS data in file %s, copied map position %s",
                fpath,
                (self._safe_gps_value_for_log(map_latitude), self._safe_gps_value_for_log(map_longitude)),
            )
        elif abs(map_latitude - latitude) > 1e-6 or abs(map_longitude - longitude) > 1e-6:
            if self.logger:
                self.logger.info(
                    "GPS from map differs from file %s: map=%s file=%s",
                    fpath,
                    (self._safe_gps_value_for_log(map_latitude), self._safe_gps_value_for_log(map_longitude)),
                    self._format_gps_tags_for_log(pos),
                )
            clipboard_value = "{}, {}".format(map_latitude, map_longitude)
            log_message = None
        elif altitude is not None:
            clipboard_value = "{}, {}, {}".format(altitude, latitude, longitude)
            log_message = ("Copied GPS from file %s: %s", fpath, self._format_gps_tags_for_log(pos))
        else:
            clipboard_value = "{}, {}".format(latitude, longitude)
            log_message = ("Copied GPS from file %s: %s", fpath, self._format_gps_tags_for_log(pos))

        try:
            pyperclip.copy(clipboard_value)
            if self.logger and log_message:
                self.logger.info(*log_message)
        except Exception as e:
            if self.logger:
                self.logger.warning("Failed to copy GPS to clipboard: %s", e)

    def _on_gps_read_completed(self, result):
        self.gps_read_in_progress = False

        if not isinstance(result, dict):
            return

        read_kind = result.get("read_kind")
        fpath = result.get("fpath")
        error = result.get("error")
        if error is not None:
            if self.logger:
                self.logger.warning("GPS read failed for %s: %s", fpath, error)
            return

        gps_tags = result.get("gps_tags", {})
        if read_kind == "copy_from_file":
            self.copied_gps_position = gps_tags
            if self.logger:
                self.logger.info(
                    "Copied GPS from file %s: %s",
                    fpath,
                    self._format_gps_tags_for_log(self.copied_gps_position),
                )
        elif read_kind == "copy_to_clipboard":
            self._copy_gps_to_clipboard_from_tags(fpath, gps_tags, map_position=result.get("map_position"))
        elif self.logger:
            self.logger.info("Unknown GPS read operation kind: %s", read_kind)

    # ── Bulk write (background thread) ────────────────────────────────

    def _start_bulk_gps_write(self, operation_label, target_tags, target_fpaths=None):
        if self.gps_write_in_progress:
            if self.logger:
                self.logger.info("GPS write operation already in progress")
            return

        normalized_tags = self._normalize_gps_tags(target_tags)
        if len(normalized_tags) == 0:
            if self.logger:
                self.logger.info("GPS data has invalid format")
            return

        if target_fpaths is None:
            target_fpaths = list(dict.fromkeys(self._iter_selected_files_for_gps_edit()))
        if len(target_fpaths) == 0:
            if self.logger:
                self.logger.info("No files selected for GPS write")
            return

        self._set_gps_operation_busy(True)
        worker_thread = threading.Thread(
            target=self._run_bulk_gps_write,
            args=(operation_label, normalized_tags, target_fpaths),
            daemon=True,
        )
        worker_thread.start()

    def _start_history_gps_write(self, history_entry, apply_after_state):
        if self.gps_write_in_progress:
            if self.logger:
                self.logger.info("GPS write operation already in progress")
            return False

        if not isinstance(history_entry, dict) or len(history_entry.get("changes", [])) == 0:
            if self.logger:
                self.logger.info("No history changes to apply")
            return False

        selected_fpaths = list(set(self.selected_items))
        self._set_gps_operation_busy(True)
        worker_thread = threading.Thread(
            target=self._run_history_gps_write,
            args=(history_entry, apply_after_state, selected_fpaths),
            daemon=True,
        )
        worker_thread.start()
        return True

    def _run_bulk_gps_write(self, operation_label, target_tags, target_fpaths):
        history_changes = []
        applied_tags_by_file = {}
        selected_locations = []
        errors = []

        exiftool_local = ExifToolWrapper(logger=self.logger)

        try:
            for fpath in target_fpaths:
                try:
                    if self.logger:
                        self.logger.info("Updating {}".format(fpath))
                    previous_tags = self._read_gps_tags(fpath, exiftool_instance=exiftool_local)
                    applied_tags = self._apply_gps_tags(fpath, target_tags, exiftool_instance=exiftool_local)
                    if self.logger:
                        readback = self._read_gps_tags(fpath, exiftool_instance=exiftool_local)
                        self.logger.info("Read back GPS for %s: %s", fpath, self._format_gps_tags_for_log(readback))
                    applied_tags_by_file[fpath] = dict(applied_tags)
                    history_changes.append({
                        "fpath": fpath,
                        "before": previous_tags,
                        "after": dict(applied_tags),
                    })
                    if MetaTagName.GPSLatitude in applied_tags and MetaTagName.GPSLongitude in applied_tags:
                        selected_locations.append((applied_tags[MetaTagName.GPSLatitude], applied_tags[MetaTagName.GPSLongitude]))
                except Exception as e:
                    errors.append((fpath, str(e)))
                    if self.logger:
                        self.logger.error("Failed to update GPS for %s", fpath, exc_info=True)
        finally:
            try:
                exiftool_local.terminate()
            except Exception:
                pass
            result = {
                "operation_kind": "paste",
                "label": operation_label,
                "history_changes": history_changes,
                "applied_tags_by_file": applied_tags_by_file,
                "selected_locations": selected_locations,
                "changed_selected_item": len(applied_tags_by_file) > 0,
                "errors": errors,
            }
            self.signals.gps_write_completed.emit(result)

    def _run_history_gps_write(self, history_entry, apply_after_state, selected_fpaths):
        state_key = "after" if apply_after_state else "before"
        direction = "redo" if apply_after_state else "undo"
        selected_fpaths_set = set(selected_fpaths)

        applied_tags_by_file = {}
        selected_locations = []
        changed_selected_item = False
        errors = []

        exiftool_local = ExifToolWrapper(logger=self.logger)

        try:
            for change in history_entry.get("changes", []):
                fpath = change.get("fpath")
                if not fpath:
                    continue
                tags = change.get(state_key, {})
                try:
                    applied_tags = self._apply_gps_tags(fpath, tags, exiftool_instance=exiftool_local)
                    applied_tags_by_file[fpath] = dict(applied_tags)

                    if fpath in selected_fpaths_set:
                        changed_selected_item = True
                        if MetaTagName.GPSLatitude in applied_tags and MetaTagName.GPSLongitude in applied_tags:
                            selected_locations.append((applied_tags[MetaTagName.GPSLatitude], applied_tags[MetaTagName.GPSLongitude]))
                except Exception as e:
                    errors.append((fpath, str(e)))
                    if self.logger:
                        self.logger.error("Failed to apply GPS history to %s", fpath, exc_info=True)
        finally:
            try:
                exiftool_local.terminate()
            except Exception:
                pass
            result = {
                "operation_kind": "history",
                "history_direction": direction,
                "history_entry": history_entry,
                "applied_tags_by_file": applied_tags_by_file,
                "selected_locations": selected_locations,
                "changed_selected_item": changed_selected_item,
                "errors": errors,
            }
            self.signals.gps_write_completed.emit(result)

    def _on_gps_write_completed(self, result):
        self._set_gps_operation_busy(False)

        if not isinstance(result, dict):
            return

        operation_kind = result.get("operation_kind", "paste")

        applied_tags_by_file = result.get("applied_tags_by_file", {})
        for fpath, applied_tags in applied_tags_by_file.items():
            has_gps = MetaTagName.GPSLatitude in applied_tags and MetaTagName.GPSLongitude in applied_tags

            with lock:
                self.has_gps_flags[fpath] = has_gps

            tree_item = self._find_tree_item(fpath)
            if tree_item:
                tree_item.setIcon(0, self.pin_icon if has_gps else self.cross_icon)
            self.shown_gps_flags[fpath] = has_gps
            self.refresh_file(fpath)

        if operation_kind == "paste":
            self._record_gps_history_entry(result.get("label", "Paste GPS"), result.get("history_changes", []))
        elif operation_kind == "history":
            history_direction = result.get("history_direction")
            history_entry = result.get("history_entry")
            errors = result.get("errors", [])
            has_successful_write = len(applied_tags_by_file) > 0

            if isinstance(history_entry, dict):
                if history_direction == "undo":
                    if has_successful_write or len(errors) == 0:
                        self._append_gps_history_entry(self.gps_redo_stack, history_entry)
                        if self.logger:
                            self.logger.info("Undo GPS edit: {}".format(history_entry.get("label", "unknown")))
                    else:
                        self._append_gps_history_entry(self.gps_undo_stack, history_entry)
                elif history_direction == "redo":
                    if has_successful_write or len(errors) == 0:
                        self._append_gps_history_entry(self.gps_undo_stack, history_entry)
                        if self.logger:
                            self.logger.info("Redo GPS edit: {}".format(history_entry.get("label", "unknown")))
                    else:
                        self._append_gps_history_entry(self.gps_redo_stack, history_entry)

            self._update_gps_history_controls()

        if result.get("changed_selected_item", len(applied_tags_by_file) > 0):
            self.signals.clear_map_signal.emit()
            selected_locations = result.get("selected_locations", [])
            if len(selected_locations) > 0:
                self.signals.update_map_signal.emit(selected_locations)

        errors = result.get("errors", [])
        if len(errors) > 0 and self.logger:
            self.logger.warning("GPS write completed with {} failures".format(len(errors)))

    # ── Public actions ────────────────────────────────────────────────

    def copy_gps_from_file(self):
        if self.canvas_selected_fpath is not None:
            self._start_gps_read("copy_from_file", self.canvas_selected_fpath)

    def paste_gps_to_file(self):
        if self.copied_gps_position is None:
            if self.logger:
                self.logger.info("No GPS data copied from file")
            return

        target_tags = self._normalize_gps_tags(self.copied_gps_position)
        if len(target_tags) == 0:
            if self.logger:
                self.logger.info("Copied GPS data has invalid format")
            return
        self._start_bulk_gps_write("Paste copied GPS", target_tags)

    def copy_gps_to_clipboard(self):
        map_position = None
        if self.map_widget is not None:
            try:
                map_position = self.map_widget.get_position()
            except Exception:
                map_position = None
        if self.logger:
            self.logger.info(
                "Copy GPS to clipboard: selected_fpath=%s map_position=%s",
                self.canvas_selected_fpath,
                map_position,
            )
        if self.canvas_selected_fpath is not None:
            self._start_gps_read("copy_to_clipboard", self.canvas_selected_fpath, map_position=map_position)
        else:
            self._copy_gps_to_clipboard_from_tags(None, {}, map_position=map_position)

    def paste_gps_from_clipboard(self):
        clipboard = pyperclip.paste()
        if len(clipboard) == 0:
            if self.logger:
                self.logger.info("Nothing in clipboard")
            return

        if self.logger:
            clipboard_log_value = "<redacted>" if self._gps_logs_redacted() else clipboard
            self.logger.info("Clipboard: %s", clipboard_log_value)
        target_tags = self._parse_clipboard_gps(clipboard)
        if target_tags is None:
            if self.logger:
                invalid_clipboard_value = "<redacted>" if self._gps_logs_redacted() else clipboard
                self.logger.info("Invalid clipboard GPS format: %s", invalid_clipboard_value)
            return
        target_fpaths = list(dict.fromkeys(self._iter_selected_files_for_gps_edit()))
        if self.logger:
            self.logger.info(
                "Pasting GPS to %s selected file(s): %s",
                len(target_fpaths),
                self._format_gps_tags_for_log(target_tags),
            )
        self._start_bulk_gps_write("Paste GPS from clipboard", target_tags, target_fpaths=target_fpaths)

    def undo_last_gps_edit(self):
        if self.gps_write_in_progress:
            if self.logger:
                self.logger.info("Cannot undo while GPS write is in progress")
            return
        if len(self.gps_undo_stack) == 0:
            if self.logger:
                self.logger.info("No GPS edit to undo")
            return

        history_entry = self.gps_undo_stack.pop()
        if not self._start_history_gps_write(history_entry, apply_after_state=False):
            self.gps_undo_stack.append(history_entry)
            self._update_gps_history_controls()

    def redo_last_gps_edit(self):
        if self.gps_write_in_progress:
            if self.logger:
                self.logger.info("Cannot redo while GPS write is in progress")
            return
        if len(self.gps_redo_stack) == 0:
            if self.logger:
                self.logger.info("No GPS edit to redo")
            return

        history_entry = self.gps_redo_stack.pop()
        if not self._start_history_gps_write(history_entry, apply_after_state=True):
            self.gps_redo_stack.append(history_entry)
            self._update_gps_history_controls()
