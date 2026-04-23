from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QComboBox, QTreeWidget, QPushButton, QLabel, QGridLayout, QSizeGrip, QApplication, QStyle
from PySide6.QtCore import Qt
import threading
from viewer.ui.widgets import MapWidget, MapHintBubble, ThemedTitleBar
import geocoder

class UIMixin:
    def _setup_ui(self):
        # Central widget and main layout
        central_widget = QWidget()
        self.root.setCentralWidget(central_widget)
        if self.use_custom_title_bar:
            root_layout = QVBoxLayout(central_widget)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)

            self.custom_title_bar = ThemedTitleBar(self.root)
            root_layout.addWidget(self.custom_title_bar)

            content_widget = QWidget()
            root_layout.addWidget(content_widget, stretch=1)

            grip_row = QWidget()
            grip_row_layout = QHBoxLayout(grip_row)
            grip_row_layout.setContentsMargins(0, 0, 4, 4)
            grip_row_layout.setSpacing(0)
            grip_row_layout.addStretch()
            self.window_size_grip = QSizeGrip(grip_row)
            self.window_size_grip.setFixedSize(14, 14)
            grip_row_layout.addWidget(self.window_size_grip)
            root_layout.addWidget(grip_row)

            main_layout = QHBoxLayout(content_widget)
            main_layout.setContentsMargins(10, 8, 10, 10)
        else:
            main_layout = QHBoxLayout(central_widget)
            main_layout.setContentsMargins(10, 10, 10, 10)

        main_layout.setSpacing(10)

        left_panel = self._setup_left_panel()
        center_panel = self._setup_center_panel()
        self._setup_right_panel()

        # Use splitter for resizable panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(center_panel)
        splitter.addWidget(self.map_widget)
        splitter.setChildrenCollapsible(True)
        splitter.setCollapsible(2, False)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 3)
        initial_splitter_sizes = getattr(self, "_splitter_sizes", None)
        if isinstance(initial_splitter_sizes, (list, tuple)) and len(initial_splitter_sizes) == 3:
            splitter.setSizes([int(v) for v in initial_splitter_sizes])
        else:
            splitter.setSizes([self.tree_width, self.photo_frames_width, self.map_width])
        self.main_splitter = splitter
        main_layout.addWidget(splitter)

    def _setup_left_panel(self):
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)

        self.combobox = QComboBox()
        self.combobox.addItems(self.get_combobox_items())
        self.combobox.setCurrentText(self.config['base_dir_selected_label'])
        self.combobox.currentTextChanged.connect(self.select_combobox)
        left_layout.addWidget(self.combobox)

        # TreeWidget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(
            QTreeWidget.SelectionMode.ExtendedSelection if self.ENABLE_GRID
            else QTreeWidget.SelectionMode.SingleSelection
        )
        self.tree.setMinimumWidth(self.MIN_TREE_WIDTH)
        self.tree.itemSelectionChanged.connect(self.item_clicked)
        self.tree.itemExpanded.connect(self.item_expanded)
        left_layout.addWidget(self.tree)

        # Use Qt built-in standard icons for GPS present/absent indicators.
        style = self.root.style() if self.root is not None else QApplication.style()
        self.pin_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        self.cross_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton)

        self._update_splash("Scanning files...")
        self.update_tree()
        return left_panel

    def _setup_center_panel(self):
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(5)

        toolbar_frame = QWidget()
        toolbar_layout = QHBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(3)

        self.copy_to_clipboard_button = QPushButton("Copy GPS to clipboard")
        self.copy_to_clipboard_button.clicked.connect(self.copy_gps_to_clipboard)
        self.paste_from_clipboard_button = QPushButton("Paste GPS from clipboard")
        self.paste_from_clipboard_button.clicked.connect(self.paste_gps_from_clipboard)
        self.undo_gps_button = QPushButton("Undo GPS")
        self.undo_gps_button.clicked.connect(self.undo_last_gps_edit)
        self.redo_gps_button = QPushButton("Redo GPS")
        self.redo_gps_button.clicked.connect(self.redo_last_gps_edit)
        self.back_to_grid_button = QPushButton("Back to grid")
        restore_callback = getattr(self, "restore_grid_after_focus", None)
        if callable(restore_callback):
            self.back_to_grid_button.clicked.connect(restore_callback)
        else:
            self.back_to_grid_button.setEnabled(False)
        self.back_to_grid_button.setVisible(False)
        self.settings_button = self._create_settings_button()

        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.copy_to_clipboard_button)
        toolbar_layout.addWidget(self.paste_from_clipboard_button)
        toolbar_layout.addWidget(self.undo_gps_button)
        toolbar_layout.addWidget(self.redo_gps_button)
        toolbar_layout.addWidget(self.back_to_grid_button)
        toolbar_layout.addWidget(self.settings_button)
        toolbar_layout.addStretch()
        self._update_gps_history_controls()
        center_layout.addWidget(toolbar_frame)

        self.pagination_frame = QWidget()
        pagination_layout = QHBoxLayout(self.pagination_frame)
        pagination_layout.setContentsMargins(0, 0, 0, 0)
        pagination_layout.setSpacing(8)

        self.first_page_button = QPushButton()
        self.first_page_button.setToolTip("First page")
        self.first_page_button.clicked.connect(self.show_first_page)

        self.prev_page_button = QPushButton()
        self.prev_page_button.setToolTip("Previous page")
        self.prev_page_button.clicked.connect(self.show_previous_page)

        self.next_page_button = QPushButton()
        self.next_page_button.setToolTip("Next page")
        self.next_page_button.clicked.connect(self.show_next_page)

        self.last_page_button = QPushButton()
        self.last_page_button.setToolTip("Last page")
        self.last_page_button.clicked.connect(self.show_last_page)

        self.page_status_label = QLabel("")
        self.page_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for button in (
            self.first_page_button,
            self.prev_page_button,
            self.next_page_button,
            self.last_page_button,
        ):
            button.setFixedWidth(34)

        self._apply_button_icons()

        pagination_layout.addStretch()
        pagination_layout.addWidget(self.first_page_button)
        pagination_layout.addWidget(self.prev_page_button)
        pagination_layout.addWidget(self.page_status_label)
        pagination_layout.addWidget(self.next_page_button)
        pagination_layout.addWidget(self.last_page_button)
        pagination_layout.addStretch()
        center_layout.addWidget(self.pagination_frame)

        # Photo display area
        self.photo_frame = QWidget()
        self.photo_frame.setMinimumSize(self.MIN_PHOTO_FRAME_WIDTH, self.MIN_PHOTO_FRAME_HEIGHT)
        self.photo_frame.setStyleSheet(f"background-color: {self.bg_color};")
        self.photo_grid_layout = QGridLayout(self.photo_frame)
        self.photo_grid_layout.setContentsMargins(8, 8, 8, 8)
        self.photo_grid_layout.setSpacing(8)
        center_layout.addWidget(self.photo_frame, stretch=1)

        self._update_pagination_controls()
        return center_panel

    def _setup_right_panel(self):
        self.map_widget = MapWidget(logger=getattr(self, 'logger', None))
        self.map_widget.setMinimumWidth(self.MIN_MAP_WIDTH)
        self.map_widget.loadFinished.connect(self._on_map_loaded)
        self.map_widget.copy_position.connect(self._on_map_position_copied)
        self._load_initial_map_position_async()
        self._maybe_show_map_hint()

    def _maybe_show_map_hint(self):
        config = getattr(self, "config", None)
        if isinstance(config, dict) and bool(config.get("map_hint_dismissed", False)):
            return
        bubble = MapHintBubble("Right-click to copy coordinates of a location", self.map_widget)
        bubble.closed.connect(self._on_map_hint_closed)
        self.map_widget.set_overlay(bubble)
        bubble.show()

    def _on_map_hint_closed(self):
        config = getattr(self, "config", None)
        if not isinstance(config, dict):
            return
        if config.get("map_hint_dismissed") is True:
            return
        config["map_hint_dismissed"] = True
        self.save_config()

    def _load_initial_map_position_async(self):
        geolocation_thread = threading.Thread(
            daemon=True,
            target=self._fetch_initial_map_position_background,
        )
        geolocation_thread.start()

    def _fetch_initial_map_position_background(self):
        try:
            cur_pos = geocoder.ip('me').latlng
        except Exception as exc:
            if self.logger:
                self.logger.warning(
                    "Could not determine initial map position: %s",
                    exc,
                    exc_info=bool(getattr(self, "log_diagnostics", False)),
                )
            return

        if not cur_pos or len(cur_pos) < 2:
            if self.logger and getattr(self, "log_diagnostics", False):
                self.logger.warning("Geocoder returned no initial map position")
            return

        lat_lng = (cur_pos[0], cur_pos[1])
        self._initial_map_pos = lat_lng

        # If the map is already loaded, apply the position immediately on the UI thread.
        if self._map_loaded:
            self.signals.update_map_signal.emit([lat_lng])
            self._initial_map_pos = None

    # ── Layout ────────────────────────────────────────────────────────

    def setup_layout_dims(self, width=None, height=None):
        if width is not None and height is not None:
            self.window_width = width
            self.window_height = height
        else:
            saved_geometry = getattr(self, "_window_geometry", None)
            if isinstance(saved_geometry, dict):
                self.window_width = int(saved_geometry.get("width", 0))
                self.window_height = int(saved_geometry.get("height", 0))
            else:
                self.window_width = 0
                self.window_height = 0

            if self.window_width <= 0 or self.window_height <= 0:
                app = QApplication.instance()
                screen = app.primaryScreen().availableGeometry()
                scale = getattr(type(self), "DEFAULT_WINDOW_SCREEN_SCALE", 0.8)
                self.window_width = int(screen.width() * scale)
                self.window_height = int(screen.height() * scale)
        if self.logger:
            self.logger.debug("Window width: {}, height: {}".format(self.window_width, self.window_height))
        self.tree_width = int(self.window_width * self.TREE_WIN_WIDTH_RATE)
        self.tree_height = int(self.window_height * self.TREE_WIN_HEIGHT_RATE)
        self.map_width = int(self.window_width * self.MAP_WIN_WIDTH_RATE)
        self.map_height = int(self.window_height * self.MAP_WIN_HEIGHT_RATE)
        self.photo_frames_width = int(self.window_width * self.CANVAS_WIN_WIDTH_RATE)
        self.photo_frame_height = int(self.window_height * self.CANVAS_WIN_HEIGHT_RATE)

