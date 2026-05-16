from PySide6.QtWidgets import QToolButton, QMenu, QFileDialog
from PySide6.QtGui import QActionGroup
from viewer.metadata.backup_manager import BackupManager

class SettingsMixin:
    # ── Settings menu ─────────────────────────────────────────────────

    def _create_settings_button(self):
        settings_button = QToolButton()
        settings_button.setText("\u2699 Settings")
        settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        settings_menu = QMenu(settings_button)
        theme_menu = settings_menu.addMenu("Theme")

        self.theme_action_group = QActionGroup(settings_button)
        self.theme_action_group.setExclusive(True)
        self.theme_actions = {}

        for label, theme_key in (("Dark", "dark"), ("Gray", "gray"), ("Light", "light"), ("System", "system")):
            action = theme_menu.addAction(label)
            action.setCheckable(True)
            action.setData(theme_key)
            self.theme_action_group.addAction(action)
            self.theme_actions[theme_key] = action

        grid_menu = settings_menu.addMenu("Grid Items Per Page")
        self.grid_page_size_action_group = QActionGroup(settings_button)
        self.grid_page_size_action_group.setExclusive(True)
        self.grid_page_size_actions = {}

        for value in self._iter_grid_items_per_page_options():
            action = grid_menu.addAction(str(value))
            action.setCheckable(True)
            action.setData(value)
            self.grid_page_size_action_group.addAction(action)
            self.grid_page_size_actions[value] = action

        settings_menu.addSeparator()
        backup_mode_menu = settings_menu.addMenu("Backup Mode")
        self.backup_mode_action_group = QActionGroup(settings_button)
        self.backup_mode_action_group.setExclusive(True)
        self.backup_mode_actions = {}

        for label, mode_key in (("Off", "off"), ("Same Directory", "same_dir"), ("Dedicated Folder", "folder")):
            action = backup_mode_menu.addAction(label)
            action.setCheckable(True)
            action.setData(mode_key)
            self.backup_mode_action_group.addAction(action)
            self.backup_mode_actions[mode_key] = action

        set_folder_action = settings_menu.addAction("Set Backup Folder...")
        set_folder_action.triggered.connect(self._on_set_backup_folder_triggered)

        settings_menu.addSeparator()
        about_action = settings_menu.addAction("About")
        about_action.triggered.connect(self.about_button_click)

        self.theme_action_group.triggered.connect(self._on_theme_action_triggered)
        self.grid_page_size_action_group.triggered.connect(self._on_grid_items_per_page_triggered)
        self.backup_mode_action_group.triggered.connect(self._on_backup_mode_action_triggered)
        settings_button.setMenu(settings_menu)
        self._sync_theme_menu_selection()
        self._sync_grid_items_per_page_menu_selection()
        self._sync_backup_mode_menu_selection()
        return settings_button

    def _on_theme_action_triggered(self, action):
        theme_choice = action.data()
        if theme_choice:
            self.select_theme(theme_choice)

    def _sync_theme_menu_selection(self):
        if not self.theme_actions:
            return
        selected = self.theme_choice if self.theme_choice in self.theme_actions else self.theme_name
        action = self.theme_actions.get(selected)
        if action is not None:
            action.setChecked(True)

    def _iter_grid_items_per_page_options(self):
        return sorted(set(self.GRID_ITEMS_PER_PAGE_OPTIONS + [self.grid_items_per_page]))

    def _on_grid_items_per_page_triggered(self, action):
        items_per_page = action.data()
        if items_per_page is not None:
            self._set_grid_items_per_page(items_per_page)

    def _sync_grid_items_per_page_menu_selection(self):
        if not self.grid_page_size_actions:
            return
        action = self.grid_page_size_actions.get(self.grid_items_per_page)
        if action is not None:
            action.setChecked(True)

    def _set_grid_items_per_page(self, items_per_page, persist_config=True):
        previous = self.grid_items_per_page
        self.grid_items_per_page = self.sanitize_grid_items_per_page(items_per_page)
        self._sync_grid_items_per_page_menu_selection()
        self.current_page_index = 0
        self._queue_current_page_for_display()
        if persist_config and self.config.get('grid_items_per_page') != self.grid_items_per_page:
            self.config['grid_items_per_page'] = self.grid_items_per_page
            self.save_config()
        if self.logger and previous != self.grid_items_per_page:
            self.logger.info("Grid items per page changed from {} to {}".format(previous, self.grid_items_per_page))

    @classmethod
    def sanitize_grid_items_per_page(cls, value):
        try:
            items_per_page = int(value)
        except (TypeError, ValueError):
            items_per_page = cls.DEFAULT_GRID_ITEMS_PER_PAGE
        return max(1, items_per_page)

    # ── Backup mode ───────────────────────────────────────────────────

    def _sync_backup_mode_menu_selection(self):
        if not getattr(self, "backup_mode_actions", None):
            return
        backup_config = self.config.get("backup")
        mode = backup_config.get("mode", "off") if isinstance(backup_config, dict) else "off"
        action = self.backup_mode_actions.get(mode)
        if action is not None:
            action.setChecked(True)

    def _on_backup_mode_action_triggered(self, action):
        mode = action.data()
        if not mode:
            return
        backup_config = self.config.get("backup")
        if not isinstance(backup_config, dict):
            backup_config = {}
            self.config["backup"] = backup_config
        backup_config["mode"] = mode
        backup_dir = backup_config.get("dir") or None
        self.backup_manager = BackupManager(mode=mode, backup_dir=backup_dir, logger=getattr(self, "logger", None))
        self.save_config()
        if self.logger:
            self.logger.info("Backup mode changed to %r", mode)

    def _on_set_backup_folder_triggered(self):
        start_dir = getattr(self, "backup_manager", None)
        start_dir = start_dir.resolved_backup_dir() if start_dir is not None else ""
        folder = QFileDialog.getExistingDirectory(self.root, "Select Backup Folder", start_dir)
        if not folder:
            return
        backup_config = self.config.get("backup")
        if not isinstance(backup_config, dict):
            backup_config = {}
            self.config["backup"] = backup_config
        backup_config["dir"] = folder
        mode = backup_config.get("mode", "off")
        self.backup_manager = BackupManager(mode=mode, backup_dir=folder, logger=getattr(self, "logger", None))
        self.save_config()
        if self.logger:
            self.logger.info("Backup folder set to %r", folder)

