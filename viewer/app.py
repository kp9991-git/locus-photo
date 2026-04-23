# Locus Photo - a photo viewer with GPS metadata editing and map integration.
# Copyright (C) 2026 Kyrylo Protsenko
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import sys
import os
import threading
import queue
import socket
import time
import uuid
from collections import OrderedDict, deque
import multiprocessing as mp
import PIL.Image
import platform
import yaml

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCore import Qt

from viewer.core.constants import APP_NAME
from viewer.core.logging_config import (
    lock,
    get_logger,
    LOG_LEVEL_ENV_KEY,
    LOG_DIAGNOSTICS_ENV_KEY,
    LOG_REDACT_GPS_ENV_KEY,
    LOG_RUN_ID_ENV_KEY,
)
from viewer.mixins.theme import ThemeMixin
from viewer.ui.styling import (
    DEFAULT_THEME,
    normalize_theme_choice,
)
from viewer.ui.widgets import WorkerSignals
from viewer.metadata.gps_operations import GpsOperationsMixin
from viewer.ui.dialogs import AboutDialog, TermsAcceptanceDialog, TERMS_VERSION
from viewer.core.enums import MetaTagName
from viewer.mixins.image_loading import ImageLoadingMixin, _init_worker as _mp_init_worker
from viewer.mixins.tree import TreeMixin
from viewer.mixins.photo_grid import PhotoGridMixin
from viewer.mixins.ui import UIMixin
from viewer.mixins.settings import SettingsMixin
from viewer.mixins.config import ConfigMixin


class MainApp(GpsOperationsMixin, ThemeMixin, ImageLoadingMixin, TreeMixin, PhotoGridMixin, UIMixin, SettingsMixin, ConfigMixin):

    CUSTOM_TITLEBAR_PLATFORMS = {"Linux", "Darwin"}

    selected_items = None
    nb_mp_processes = 4
    nb_image_queue = 30
    thumbnail_via_exiftool = True
    read_raw_partially = True
    max_cache_size = 100
    use_batch_loading = False

    ADD_DIR_LABEL = '     Add directory...'
    REMOVE_DIR_LABEL = '     Remove directory...'

    ENABLE_GRID = True
    DEFAULT_GRID_ITEMS_PER_PAGE = 4
    GRID_ITEMS_PER_PAGE_OPTIONS = [1, 4, 6, 9, 12]
    MIN_TREE_WIDTH = 140
    MIN_MAP_WIDTH = 180
    MIN_PHOTO_FRAME_WIDTH = 220
    MIN_PHOTO_FRAME_HEIGHT = 160
    TREE_ICON_SIZE = 18
    TREE_WIN_WIDTH_RATE = 0.2
    TREE_WIN_HEIGHT_RATE = 1
    MAP_WIN_WIDTH_RATE = 0.3
    MAP_WIN_HEIGHT_RATE = 1
    CANVAS_WIN_WIDTH_RATE = 0.5
    CANVAS_WIN_HEIGHT_RATE = 1

    DEFAULT_WINDOW_SCREEN_SCALE = 0.8

    MAX_FILE_SIZE = 2e+8  # 200 MB
    IMAGE_SUPPORTED_EXTENSIONS = list(PIL.Image.registered_extensions().keys())
    SUPPORTED_EXTENSIONS = None
    GPS_TAGS = (MetaTagName.GPSAltitude, MetaTagName.GPSLatitude, MetaTagName.GPSLongitude)
    GPS_HISTORY_LIMIT = 100

    def __init__(self, exiftool_registry, exiftool, use_logging=True, show_splash=True):
        self._init_core_variables(exiftool_registry, exiftool, use_logging, show_splash)
        self._init_config_and_logger()
        self._setup_main_window_and_theme()

        self.setup_layout_dims()
        self._setup_signals()

        self._setup_ui()

        self.images = OrderedDict()
        self.copied_gps_position = None

    @classmethod
    def create_for_tests(cls, exiftool_registry, exiftool, use_logging=False):
        # Build the UI object graph without launching runtime workers or the event loop.
        return cls(exiftool_registry, exiftool, use_logging=use_logging, show_splash=False)

    def _run_exiftool_startup_checks(self):
        logger = getattr(self, "logger", None)
        exiftool_instance = getattr(self, "exiftool", None)

        if logger:
            logger.info("Supported image extensions: {}".format(MainApp.IMAGE_SUPPORTED_EXTENSIONS))
            logger.debug("Startup check: querying ExifTool version...")
            try:
                exiftool_version = exiftool_instance.get_version() if exiftool_instance is not None else None
                logger.debug("Startup check: ExifTool version query completed.")
                if exiftool_version:
                    logger.info("ExifTool version: {}".format(exiftool_version))
            except Exception:
                logger.exception("Startup check failed while querying ExifTool version")

        if logger:
            logger.debug("Startup check: querying ExifTool supported extensions...")
        try:
            exiftool_supported_extensions = (
                exiftool_instance.get_list_of_supported_extensions()
                if exiftool_instance is not None
                else None
            )
        except Exception:
            exiftool_supported_extensions = None
            if logger:
                logger.exception("Startup check failed while querying ExifTool supported extensions")
        if logger:
            logger.debug("Startup check: ExifTool extension query completed.")
            logger.info("Supported extensions from exiftool: {}".format(exiftool_supported_extensions))
        if exiftool_supported_extensions is not None:
            MainApp.SUPPORTED_EXTENSIONS = exiftool_supported_extensions + MainApp.IMAGE_SUPPORTED_EXTENSIONS
        self._startup_checks_completed = True

    def run(self):
        if self._started:
            return
        self._started = True
        self._update_splash("Checking ExifTool...")
        if not getattr(self, "_startup_checks_completed", False):
            self._run_exiftool_startup_checks()
        self.mp_pool = mp.Pool(self.nb_mp_processes, initializer=_mp_init_worker)
        self._start_background_workers()

        # Apply configured theme stylesheet
        self._update_splash("Applying theme...")
        self._apply_theme_stylesheet()

        self.loading = False
        self._finalize_and_show_window()

    @staticmethod
    def _sanitize_window_geometry(value):
        if not isinstance(value, dict):
            return None
        try:
            width = max(320, int(value.get("width", 0)))
            height = max(240, int(value.get("height", 0)))
            x = int(value.get("x", 0))
            y = int(value.get("y", 0))
            maximized = bool(value.get("maximized", False))
        except (TypeError, ValueError):
            return None

        return {
            "width": width,
            "height": height,
            "x": x,
            "y": y,
            "maximized": maximized,
        }

    @staticmethod
    def _sanitize_splitter_sizes(value):
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return None
        try:
            sizes = [max(0, int(v)) for v in value]
        except (TypeError, ValueError):
            return None
        # Keep map pane visible on restore; reject persisted layouts with hidden map width.
        if sizes[2] <= 0:
            return None
        if sum(sizes) <= 0:
            return None
        return sizes

    @staticmethod
    def _sanitize_logging_enabled(value, fallback):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return fallback

    @staticmethod
    def _sanitize_logging_level(value, fallback="INFO"):
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
                return normalized
        return fallback

    @staticmethod
    def _sanitize_logging_diagnostics(value, fallback=False):
        return MainApp._sanitize_logging_enabled(value, fallback)

    def _init_core_variables(self, exiftool_registry, exiftool, use_logging, show_splash):
        # External dependencies and runtime flags.
        self.exiftool_registry = exiftool_registry
        self.exiftool = exiftool
        self.root = None
        self.running = True
        self.loading = True
        self.use_logging = use_logging
        self.log_level_name = "INFO"
        self.log_diagnostics = False
        self.log_redact_gps = True
        self.log_run_id = None
        self._network_diagnostics_started = False
        self._show_splash = show_splash

        # Current photo/grid selection and paging state.
        self.displayed_photos = []
        self.selected_items = []
        self.selected_photo_fpaths = []
        self.current_page_index = 0
        self.grid_items_per_page = MainApp.DEFAULT_GRID_ITEMS_PER_PAGE

        # GPS edit history state.
        self.gps_undo_stack = deque(maxlen=self.GPS_HISTORY_LIMIT)
        self.gps_redo_stack = deque(maxlen=self.GPS_HISTORY_LIMIT)
        self.gps_write_in_progress = False
        self.gps_read_in_progress = False

        # Theme and splash state.
        self.splash = None
        self.theme_choice = DEFAULT_THEME

        # Toolbar buttons and actions.
        self.copy_to_clipboard_button = None
        self.paste_from_clipboard_button = None
        self.undo_gps_button = None
        self.redo_gps_button = None
        self.first_page_button = None
        self.prev_page_button = None
        self.next_page_button = None
        self.last_page_button = None
        self.back_to_grid_button = None
        self.settings_button = None
        self.undo_gps_action = None
        self.redo_gps_action = None

        # Menu/action collections.
        self.theme_actions = {}
        self.grid_page_size_actions = {}

        # Core UI containers and dynamic image widgets.
        self.pagination_frame = None
        self.page_status_label = None
        self.photo_frame = None
        self.photo_grid_layout = None
        self.image_labels = []

        # Tree and GPS icon cache state.
        self.continue_iter = True
        self._fpath_to_tree_item = {}
        self._populated_dirs = set()
        self.has_gps_flags = {}
        self.shown_gps_flags = {}

        # Worker queues.
        self.image_load_queue = queue.LifoQueue()
        self.display_image_queue = queue.LifoQueue()
        self.gps_flags_queue = queue.Queue()
        self.map_location_queue = queue.Queue()

        # Map and canvas transient state.
        self.map_widget = None
        self._map_loaded = False
        self._initial_map_pos = None
        self.canvas_currently_displayed_image_fpath = None
        self.canvas_selected_fpath = None
        self.canvas_selected_fpath_loaded = False

        # Persisted layout and focus/restore state.
        self.main_splitter = None
        self._window_geometry = None
        self._splitter_sizes = None
        self._focused_grid_origin_fpaths = None
        self._focused_grid_origin_page_index = 0

        # Runtime worker/process lifecycle state.
        self.mp_pool = None
        self._started = False
        self._startup_checks_completed = False

    def _init_config_and_logger(self):
        config_fpath = MainApp.get_config_fpath()
        loaded_config = {}
        config_load_exc_info = None
        try:
            with open(config_fpath, 'r', encoding='utf-8') as f:
                loaded_config = yaml.safe_load(f)
        except Exception:
            config_load_exc_info = sys.exc_info()

        self.config = loaded_config if isinstance(loaded_config, dict) else {}

        logging_config = self.config.get("logging")
        if not isinstance(logging_config, dict):
            logging_config = {}

        logging_enabled_raw = logging_config.get("enabled", self.config.get("use_logging", self.use_logging))
        self.use_logging = MainApp._sanitize_logging_enabled(logging_enabled_raw, self.use_logging)

        default_log_level_name = getattr(self, "log_level_name", "INFO")
        logging_level_raw = logging_config.get("level", self.config.get("log_level", default_log_level_name))
        self.log_level_name = MainApp._sanitize_logging_level(logging_level_raw, default_log_level_name)

        default_log_diagnostics = getattr(self, "log_diagnostics", False)
        diagnostics_raw = logging_config.get("diagnostics", self.config.get("log_diagnostics", default_log_diagnostics))
        self.log_diagnostics = MainApp._sanitize_logging_diagnostics(diagnostics_raw, default_log_diagnostics)

        default_log_redact_gps = getattr(self, "log_redact_gps", True)
        redact_gps_raw = logging_config.get("redact_gps", self.config.get("log_redact_gps", default_log_redact_gps))
        self.log_redact_gps = MainApp._sanitize_logging_enabled(redact_gps_raw, default_log_redact_gps)

        if self.use_logging:
            run_id = os.environ.get(LOG_RUN_ID_ENV_KEY)
            if not run_id:
                run_id = uuid.uuid4().hex[:12]
            self.log_run_id = run_id
            os.environ[LOG_LEVEL_ENV_KEY] = self.log_level_name
            os.environ[LOG_DIAGNOSTICS_ENV_KEY] = "1" if self.log_diagnostics else "0"
            os.environ[LOG_REDACT_GPS_ENV_KEY] = "1" if self.log_redact_gps else "0"
            os.environ[LOG_RUN_ID_ENV_KEY] = run_id
            self.logger = get_logger(self.log_level_name)
        else:
            os.environ.pop(LOG_LEVEL_ENV_KEY, None)
            os.environ.pop(LOG_DIAGNOSTICS_ENV_KEY, None)
            os.environ.pop(LOG_REDACT_GPS_ENV_KEY, None)
            os.environ.pop(LOG_RUN_ID_ENV_KEY, None)
            self.log_run_id = None
            self.logger = None

        if self.logger and config_load_exc_info is not None:
            self.logger.error(
                "Failed to load config from %s. Continuing with defaults.",
                config_fpath,
                exc_info=config_load_exc_info,
            )

        if self.logger and self.log_diagnostics:
            self._log_diagnostics_snapshot(config_fpath)
            self._start_network_diagnostics_async()

        requested_theme = self.config.get('theme', DEFAULT_THEME)
        self.theme_choice = normalize_theme_choice(requested_theme)
        self._config_updated = False
        if self.config.get('theme') != self.theme_choice:
            self.config['theme'] = self.theme_choice
            self._config_updated = True

        self.grid_items_per_page = MainApp.sanitize_grid_items_per_page(
            self.config.get('grid_items_per_page', MainApp.DEFAULT_GRID_ITEMS_PER_PAGE)
        )
        if self.config.get('grid_items_per_page') != self.grid_items_per_page:
            self.config['grid_items_per_page'] = self.grid_items_per_page
            self._config_updated = True

        if self._config_updated:
            self.save_config()

        self._window_geometry = MainApp._sanitize_window_geometry(self.config.get("window_geometry"))
        self._splitter_sizes = MainApp._sanitize_splitter_sizes(self.config.get("splitter_sizes"))

        # Perform ExifTool startup checks after logger/config initialization so
        # extension support is cached and startup diagnostics are available.
        self._run_exiftool_startup_checks()

    def _log_diagnostics_snapshot(self, config_fpath):
        if not self.logger:
            return
        try:
            cwd = os.getcwd()
        except Exception:
            cwd = "<unavailable>"

        home_path = os.path.expanduser("~")
        proxy_present = {
            "HTTP_PROXY": bool(os.environ.get("HTTP_PROXY")),
            "HTTPS_PROXY": bool(os.environ.get("HTTPS_PROXY")),
            "NO_PROXY": bool(os.environ.get("NO_PROXY")),
        }
        self.logger.info(
            "Diagnostics snapshot: config=%s cwd=%s cwd_writable=%s home=%s home_writable=%s frozen=%s python=%s platform=%s proxies=%s",
            config_fpath,
            cwd,
            os.access(cwd, os.W_OK) if cwd != "<unavailable>" else False,
            home_path,
            os.access(home_path, os.W_OK),
            bool(getattr(sys, 'frozen', False)),
            platform.python_version(),
            platform.platform(),
            proxy_present,
        )

    def _start_network_diagnostics_async(self):
        if not self.logger or not self.log_diagnostics:
            return
        if getattr(self, "_network_diagnostics_started", False):
            return

        self._network_diagnostics_started = True
        thread = threading.Thread(
            daemon=True,
            name="viewer-network-diagnostics",
            target=self._run_network_diagnostics_checks,
        )
        thread.start()

    @staticmethod
    def _check_tcp_endpoint(host, port, timeout_seconds=2.5):
        started = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                elapsed_ms = int((time.monotonic() - started) * 1000)
                return True, elapsed_ms, None
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return False, elapsed_ms, str(exc)

    def _run_network_diagnostics_checks(self):
        if not self.logger:
            return

        endpoints = [
            ("Leaflet CDN", "unpkg.com", 443),
            ("OSM tiles", "tile.openstreetmap.org", 443),
            ("OpenStreetMap", "www.openstreetmap.org", 443),
        ]
        self.logger.info("Running startup network diagnostics for %d endpoints", len(endpoints))

        for label, host, port in endpoints:
            ok, elapsed_ms, error_text = MainApp._check_tcp_endpoint(host, port)
            if ok:
                self.logger.info("Network check passed: %s host=%s port=%s latency_ms=%s", label, host, port, elapsed_ms)
            else:
                self.logger.warning(
                    "Network check failed: %s host=%s port=%s latency_ms=%s error=%s",
                    label,
                    host,
                    port,
                    elapsed_ms,
                    error_text,
                )

    def _setup_main_window_and_theme(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setStyle("Fusion")
        self.root = QMainWindow()
        self.root.setWindowTitle(APP_NAME)
        self.use_custom_title_bar = platform.system() in MainApp.CUSTOM_TITLEBAR_PLATFORMS
        self.custom_title_bar = None
        self.window_size_grip = None
        if self.use_custom_title_bar:
            self.root.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self._setup_gps_shortcuts()
        self.app.styleHints().colorSchemeChanged.connect(self._on_system_color_scheme_changed)

        # Color scheme
        self._set_theme_colors(self.theme_choice)

        if self._show_splash:
            self._create_splash_screen()
            self._update_splash("Initializing...")

    def _setup_signals(self):
        self.signals = WorkerSignals()
        self.signals.update_tree_icons.connect(self._update_tree_icons_slot, Qt.ConnectionType.QueuedConnection)
        self.signals.display_images_signal.connect(self._display_images_slot, Qt.ConnectionType.QueuedConnection)
        self.signals.update_map_signal.connect(self._update_map_slot, Qt.ConnectionType.QueuedConnection)
        self.signals.clear_map_signal.connect(self._clear_map_slot, Qt.ConnectionType.QueuedConnection)
        self.signals.gps_write_completed.connect(self._on_gps_write_completed, Qt.ConnectionType.QueuedConnection)
        self.signals.gps_read_completed.connect(self._on_gps_read_completed, Qt.ConnectionType.QueuedConnection)
        self.signals.zoom_image_ready.connect(self._on_zoom_image_ready, Qt.ConnectionType.QueuedConnection)

    def _start_background_workers(self):
        image_load_thread = threading.Thread(daemon=True, target=self.load_images_background)
        image_load_thread.start()

        display_image_thread = threading.Thread(daemon=True, target=self.display_image_background)
        display_image_thread.start()

        load_file_gps_flags_thread = threading.Thread(daemon=True, target=self.load_file_gps_flags_background)
        load_file_gps_flags_thread.start()

        map_location_thread = threading.Thread(daemon=True, target=self.map_location_background)
        map_location_thread.start()

    def _finalize_and_show_window(self):
        screen = self.app.primaryScreen().availableGeometry()
        saved_geometry = getattr(self, "_window_geometry", None)
        if saved_geometry is not None:
            window_width = min(int(saved_geometry["width"]), int(screen.width()))
            window_height = min(int(saved_geometry["height"]), int(screen.height()))
            self.root.resize(window_width, window_height)

            max_x = screen.x() + max(0, screen.width() - window_width)
            max_y = screen.y() + max(0, screen.height() - window_height)
            saved_x = int(saved_geometry["x"])
            saved_y = int(saved_geometry["y"])
            self.root.move(min(max(saved_x, screen.x()), max_x), min(max(saved_y, screen.y()), max_y))
        else:
            scale = MainApp.DEFAULT_WINDOW_SCREEN_SCALE
            window_width = int(screen.width() * scale)
            window_height = int(screen.height() * scale)
            self.root.resize(window_width, window_height)
            centered_x = screen.x() + (screen.width() - window_width) // 2
            centered_y = screen.y() + (screen.height() - window_height) // 2
            self.root.move(centered_x, centered_y)

        self._update_splash("Almost ready...")
        if saved_geometry is not None and saved_geometry.get("maximized", False):
            self.root.showMaximized()
        else:
            self.root.show()
        self._apply_native_titlebar_theme()

        if self.splash is not None:
            self.splash.finish(self.root)
            self.splash = None

        if not self._prompt_terms_if_needed():
            # User declined the terms; shut down without entering the event loop.
            self.root.close()
            return

        self.app.aboutToQuit.connect(self._on_quit)
        self.app.exec()

    def _prompt_terms_if_needed(self):
        accepted_version = 0
        if isinstance(getattr(self, "config", None), dict):
            try:
                accepted_version = int(self.config.get("terms_accepted_version", 0) or 0)
            except (TypeError, ValueError):
                accepted_version = 0
        if accepted_version >= TERMS_VERSION:
            return True

        dialog = TermsAcceptanceDialog(self.root)
        result = dialog.exec()
        if result != dialog.DialogCode.Accepted:
            if self.logger:
                self.logger.info("User declined Terms of Use; exiting.")
            return False

        if isinstance(getattr(self, "config", None), dict):
            self.config["terms_accepted_version"] = TERMS_VERSION
            try:
                self.save_config()
            except Exception:
                if self.logger:
                    self.logger.exception("Failed to persist terms acceptance to config")
        return True

    def _persist_ui_state(self):
        if not isinstance(getattr(self, "config", None), dict):
            return

        config_updated = False

        if self.root is not None:
            is_maximized = bool(self.root.isMaximized())
            geometry = self.root.normalGeometry() if is_maximized else self.root.geometry()
            new_window_geometry = MainApp._sanitize_window_geometry({
                "width": geometry.width(),
                "height": geometry.height(),
                "x": geometry.x(),
                "y": geometry.y(),
                "maximized": is_maximized,
            })
            if new_window_geometry is not None and self.config.get("window_geometry") != new_window_geometry:
                self.config["window_geometry"] = new_window_geometry
                config_updated = True

        if self.main_splitter is not None:
            splitter_sizes = MainApp._sanitize_splitter_sizes(self.main_splitter.sizes())
            if splitter_sizes is not None and self.config.get("splitter_sizes") != splitter_sizes:
                self.config["splitter_sizes"] = splitter_sizes
                config_updated = True

        if config_updated:
            self.save_config()

    # ── Lifecycle ─────────────────────────────────────────────────────

    def _on_map_position_copied(self, lat, lng):
        if self.logger:
            self.logger.info(
                "Copied map position to clipboard: %s",
                (self._safe_gps_value_for_log(lat), self._safe_gps_value_for_log(lng)),
            )

    def _on_map_loaded(self, ok=True):
        self._map_loaded = True
        logger = getattr(self, "logger", None)
        if logger:
            if ok is False:
                logger.warning(
                    "Map load failed. Verify firewall/proxy settings and access to Leaflet CDN and OpenStreetMap tile endpoints."
                )
            elif getattr(self, "log_diagnostics", False):
                logger.info("Map load finished successfully")
        if self._initial_map_pos:
            self.map_widget.set_position(self._initial_map_pos[0], self._initial_map_pos[1], marker=True)
            if logger and getattr(self, "log_diagnostics", False):
                logger.info("Applied deferred initial map position from geolocation")
            self._initial_map_pos = None

    def _on_quit(self):
        self.running = False

        for queue_attr in ("map_location_queue", "display_image_queue"):
            queue_obj = getattr(self, queue_attr, None)
            if queue_obj is None:
                continue
            try:
                queue_obj.put(getattr(self, "WORKER_STOP_SIGNAL", None))
            except Exception:
                if getattr(self, "logger", None):
                    self.logger.debug("Could not wake %s during quit", queue_attr, exc_info=True)

        try:
            self._persist_ui_state()
        except Exception as exc:
            if self.logger:
                self.logger.debug("Could not persist UI state during quit: {}".format(exc))
        # Close the QWebEngineView explicitly so its Chromium C++ threads are
        # released while the Python interpreter is still fully initialised.
        # Without this, Python 3.13's _DeleteDummyThreadOnDel.__del__ fires
        # after _active_limbo_lock has been set to None, producing:
        #   TypeError: 'NoneType' object does not support the context manager protocol
        if self.map_widget is not None:
            self.map_widget.close()
        if self.mp_pool is not None:
            self.mp_pool.terminate()
            self.mp_pool.join()
            self.mp_pool = None

    # ── File operations ───────────────────────────────────────────────

    def refresh_file(self, fpath):
        with lock:
            if fpath == self.canvas_selected_fpath:
                self.canvas_selected_fpath_loaded = False
            self.images.pop(fpath, None)
            self.image_load_queue.put(fpath)

    # ── About dialog ──────────────────────────────────────────────────

    def about_button_click(self):
        dialog = AboutDialog(self.root, link_color=self.link_color)
        dialog.exec()
