import os
import time
import queue
import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from viewer.core.utils import clear_queue
from viewer.metadata.exiftool_wrapper import ExifToolWrapper

class TreeMixin:

    def _safe_listdir(self, fpath_dir, context_label="listing directory"):
        try:
            return os.listdir(fpath_dir)
        except OSError:
            if self.logger:
                self.logger.warning(
                    "Could not list directory %s while %s",
                    fpath_dir,
                    context_label,
                    exc_info=True,
                )
            return []

    def _get_image_preload_count(self):
        return max(1, self.grid_items_per_page * 2)

    def _get_gps_deferred_backlog_limit(self):
        return max(32, self.grid_items_per_page * 8)

    def _next_gps_scan_generation(self):
        generation = getattr(self, "_gps_scan_generation", 0) + 1
        self._gps_scan_generation = generation
        return generation

    def _deferred_enqueue_gps_flags(self, fpaths, generation):
        backlog_limit = self._get_gps_deferred_backlog_limit()
        for fpath in dict.fromkeys(fpaths):
            if os.path.isdir(fpath):
                continue
            if getattr(self, "_gps_scan_generation", 0) != generation:
                return
            if not getattr(self, "running", True):
                return

            while self.gps_flags_queue.qsize() > backlog_limit:
                if getattr(self, "_gps_scan_generation", 0) != generation:
                    return
                if not getattr(self, "running", True):
                    return
                time.sleep(0.02)

            self.gps_flags_queue.put(fpath)
            # Keep low impact while still progressing tree icon updates.
            time.sleep(0.003)

    def _start_deferred_gps_scan(self, fpaths):
        deferred_paths = [f for f in dict.fromkeys(fpaths) if not os.path.isdir(f)]
        generation = self._next_gps_scan_generation()
        if len(deferred_paths) == 0:
            self._gps_scan_thread = None
            return
        thread = threading.Thread(
            name="viewer-gps-deferred-scan",
            target=self._deferred_enqueue_gps_flags,
            args=(deferred_paths, generation),
            daemon=True,
        )
        thread.start()
        self._gps_scan_thread = thread

    def _find_tree_item(self, fpath):
        return self._fpath_to_tree_item.get(fpath) or self._fpath_to_tree_item.get(fpath.replace("\\", "/"))

    def _tree_exists(self, fpath):
        return self._find_tree_item(fpath) is not None

    def tree_iterate_items(self, parent_item):
        if not self.continue_iter:
            return
        if parent_item is None:
            for i in range(self.tree.topLevelItemCount()):
                if self.continue_iter:
                    self.tree_iterate_items(self.tree.topLevelItem(i))
            return

        for i in range(parent_item.childCount()):
            if not self.continue_iter:
                return
            child = parent_item.child(i)
            fpath = child.data(0, Qt.ItemDataRole.UserRole)
            if fpath and not os.path.isdir(fpath):
                flag_value = self.has_gps_flag_for_file_in_cache(fpath)[1]
                if flag_value is not None:
                    if flag_value != self.shown_gps_flags.get(fpath):
                        if self.logger:
                            self.logger.debug("Showing GPS flags for file {}, flag value is {}".format(fpath, flag_value))
                        try:
                            if flag_value:
                                child.setIcon(0, self.pin_icon)
                            else:
                                child.setIcon(0, self.cross_icon)
                            self.shown_gps_flags[fpath] = flag_value
                        except Exception:
                            if self.logger:
                                self.logger.error(
                                    "Error setting GPS icons for file %s, flag value is %s",
                                    fpath,
                                    flag_value,
                                    exc_info=True,
                                )
            self.tree_iterate_items(child)

    def _update_tree_icons_slot(self, updates):
        for fpath, flag_value in updates:
            tree_item = self._find_tree_item(fpath)
            if tree_item is None:
                continue
            try:
                if flag_value:
                    tree_item.setIcon(0, self.pin_icon)
                else:
                    tree_item.setIcon(0, self.cross_icon)
                self.shown_gps_flags[fpath] = flag_value
            except Exception:
                if self.logger:
                    self.logger.error(
                        "Error setting GPS icon for file %s, flag value is %s",
                        fpath,
                        flag_value,
                        exc_info=True,
                    )

    def load_file_gps_flags_background(self):
        exiftool_local = ExifToolWrapper()
        self.exiftool_registry.add_wrapper(exiftool_local)
        pending_icon_updates = {}
        last_flush_time = time.monotonic()
        max_batch_size = 32
        flush_interval_sec = 0.08

        def flush_icon_updates(force=False):
            nonlocal last_flush_time
            if not pending_icon_updates:
                return
            now = time.monotonic()
            if not force and len(pending_icon_updates) < max_batch_size and (now - last_flush_time) < flush_interval_sec:
                return
            self.signals.update_tree_icons.emit(list(pending_icon_updates.items()))
            pending_icon_updates.clear()
            last_flush_time = now

        while self.running:
            try:
                fpath = self.gps_flags_queue.get(timeout=0.1)
            except queue.Empty:
                flush_icon_updates(force=True)
                continue
            if not self.is_file_acceptable(fpath):
                if self.logger:
                    self.logger.debug("Skipping unsupported file during GPS flag scan: %s", fpath)
                flush_icon_updates()
                continue
            self.continue_iter = True
            if self.logger:
                self.logger.info("load_file_gps_flags_background: Processing file {}".format(fpath))
            updated = False
            flag_value = self.has_gps_flag_for_file_in_cache(fpath)[1]
            if flag_value is None:
                try:
                    flag_value, updated = self.extract_gps_coordinates_and_put_in_cache(fpath, exiftool_local=exiftool_local)
                except Exception:
                    if self.logger:
                        self.logger.error("Error extracting GPS flags for file %s", fpath, exc_info=True)
            if flag_value is not None:
                shown_flag = self.shown_gps_flags.get(fpath)
                if shown_flag is None:
                    shown_flag = self.shown_gps_flags.get(fpath.replace("\\", "/"))
                if updated or shown_flag != flag_value:
                    pending_icon_updates[fpath] = flag_value
            flush_icon_updates()

    def update_tree(self):
        self._next_gps_scan_generation()
        self.continue_iter = False
        self.tree.clear()
        self._fpath_to_tree_item = {}
        self._populated_dirs = set()
        data_dir = self.get_data_dir()
        root_item = None
        if data_dir is not None:
            root_item = QTreeWidgetItem(self.tree, [data_dir])
            root_item.setData(0, Qt.ItemDataRole.UserRole, data_dir)
            self._fpath_to_tree_item[data_dir] = root_item
            self.insert_files(data_dir, root_item)
        self.has_gps_flags = {}
        self.shown_gps_flags = {}
        self.selected_items = []
        self.selected_photo_fpaths = []
        self.current_page_index = 0
        self._clear_grid_focus_state()
        self._clear_photo_grid()
        self._update_pagination_controls()
        clear_queue(self.image_load_queue)
        clear_queue(self.display_image_queue)
        clear_queue(self.gps_flags_queue)
        clear_queue(self.map_location_queue)
        self.continue_iter = True
        if root_item is not None:
            root_item.setExpanded(True)

    def _populate_children(self, fpath_dir, parent_item):
        if fpath_dir in self._populated_dirs:
            return [], []
        if not os.path.exists(fpath_dir):
            self._populated_dirs.add(fpath_dir)
            return [], []
        try:
            with os.scandir(fpath_dir) as it:
                entries = list(it)
        except OSError:
            if self.logger:
                self.logger.warning(
                    "Could not list directory %s while %s",
                    fpath_dir,
                    "building file tree",
                    exc_info=True,
                )
            self._populated_dirs.add(fpath_dir)
            return [], []

        dir_entries = []
        file_entries = []
        for entry in entries:
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                dir_entries.append(entry)
            else:
                file_entries.append(entry)
        dir_entries.sort(key=lambda e: e.name)
        file_entries.sort(key=lambda e: e.name)

        dir_paths = []
        file_paths = []
        for entry in dir_entries + file_entries:
            child_item = QTreeWidgetItem(parent_item, [entry.name])
            child_item.setData(0, Qt.ItemDataRole.UserRole, entry.path)
            self._fpath_to_tree_item[entry.path] = child_item
            try:
                if entry.is_dir():
                    child_item.setChildIndicatorPolicy(
                        QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                    )
                    dir_paths.append(entry.path)
                else:
                    file_paths.append(entry.path)
            except OSError:
                file_paths.append(entry.path)

        self._populated_dirs.add(fpath_dir)
        return dir_paths, file_paths

    def insert_files(self, fpath_dir, parent_item):
        self._populate_children(fpath_dir, parent_item)

    def item_clicked(self):
        selected_tree_items = self.tree.selectedItems()
        self.selected_items = []
        for item in selected_tree_items:
            fpath = item.data(0, Qt.ItemDataRole.UserRole)
            if fpath:
                self.selected_items.append(fpath)

        fpaths_to_load = []
        fpaths_to_display = []
        for fpath in self.selected_items:
            if os.path.isdir(fpath):
                fs = self._safe_listdir(fpath, context_label="loading selected directory")
                for f in fs:
                    full_fpath = os.path.join(fpath, f)
                    if not os.path.isdir(full_fpath):
                        fpaths_to_load.append(full_fpath)
                        fpaths_to_display.append(full_fpath)
            else:
                fpaths_to_load += [fpath]
                fpaths_to_display.append(fpath)

        preload_count = self._get_image_preload_count()
        priority_paths = list(dict.fromkeys(fpaths_to_display[:preload_count]))
        for fpath_ in dict.fromkeys(fpaths_to_display[:preload_count]):
            if not os.path.isdir(fpath_):
                if self.logger:
                    self.logger.info(f"Putting {fpath_} into the image load queue")
                self.image_load_queue.put(fpath_)

        all_gps_candidates = list(dict.fromkeys(fpaths_to_load))
        priority_set = set(priority_paths)
        deferred_gps_paths = []
        for fpath_ in all_gps_candidates:
            if os.path.isdir(fpath_):
                continue
            if fpath_ in priority_set:
                if self.logger:
                    self.logger.info(f"Putting {fpath_} into the gps flag queue")
                self.gps_flags_queue.put(fpath_)
            else:
                deferred_gps_paths.append(fpath_)

        self._start_deferred_gps_scan(deferred_gps_paths)

        self.selected_photo_fpaths = list(dict.fromkeys(fpaths_to_display))
        self.current_page_index = 0
        self._clear_grid_focus_state()
        self._queue_current_page_for_display()

    def item_expanded(self, item):
        fpath = item.data(0, Qt.ItemDataRole.UserRole)
        if not fpath or not os.path.isdir(fpath):
            return

        if fpath in self._populated_dirs:
            file_paths = []
            for f in self._safe_listdir(fpath, context_label="expanding tree item"):
                full_fpath = os.path.join(fpath, f)
                if not os.path.isdir(full_fpath):
                    file_paths.append(full_fpath)
        else:
            _, file_paths = self._populate_children(fpath, item)

        expanded_paths = []
        for full_fpath in file_paths:
            self.image_load_queue.put(full_fpath)
            expanded_paths.append(full_fpath)

        self._start_deferred_gps_scan(expanded_paths)

    def select_combobox(self, choice):
        if choice == self.ADD_DIR_LABEL:
            self.base_dir_add()
        elif choice == self.REMOVE_DIR_LABEL:
            self.base_dir_remove()
        else:
            self.config['base_dir_selected_label'] = choice
            self.update_tree()
            self.save_config()
