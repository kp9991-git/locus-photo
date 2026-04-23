from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton, QStyle, QWidget

from viewer.ui.styling import SYSTEM_THEME, THEME_PRESETS, build_stylesheet
from viewer.mixins.theme import ThemeMixin
from viewer.mixins.ui import UIMixin


class _DummyStyleHints:
    def __init__(self, scheme):
        self._scheme = scheme

    def colorScheme(self):
        return self._scheme


class _DummyApp:
    def __init__(self, scheme, qapp):
        self._hints = _DummyStyleHints(scheme)
        self._style = qapp.style()
        self.processEvents = MagicMock()

    def styleHints(self):
        return self._hints

    def style(self):
        return self._style


class _DummyRoot:
    def __init__(self):
        self.stylesheet = ""

    def setStyleSheet(self, value):
        self.stylesheet = value

    def winId(self):
        return 1


class _DummyFrame:
    def __init__(self):
        self.stylesheet = ""

    def setStyleSheet(self, value):
        self.stylesheet = value


class _DummyLabel:
    def __init__(self):
        self.stylesheet = ""

    def setStyleSheet(self, value):
        self.stylesheet = value


class _ThemeHarness(ThemeMixin):
    def __init__(self, app):
        self.app = app
        self.logger = MagicMock()
        self.root = _DummyRoot()
        self.photo_frame = _DummyFrame()
        self.image_labels = [_DummyLabel()]
        self.custom_title_bar = None

        self.copy_to_clipboard_button = None
        self.paste_from_clipboard_button = None
        self.undo_gps_button = None
        self.redo_gps_button = None
        self.first_page_button = None
        self.prev_page_button = None
        self.next_page_button = None
        self.last_page_button = None
        self.settings_button = None
        self.undo_gps_action = None
        self.redo_gps_action = None

        self.config = {"theme": "light"}
        self.theme_choice = "light"
        self.theme_name = "light"

        self.save_config = MagicMock()
        self._sync_theme_menu_selection = MagicMock()
        self._apply_photo_label_decoration = MagicMock()


class _DummyLoadSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class _DummyMapWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.loadFinished = _DummyLoadSignal()
        self.copy_position = _DummyLoadSignal()
        self.min_width = None
        self.overlay = None

    def setMinimumWidth(self, width):
        self.min_width = width

    def set_overlay(self, widget):
        self.overlay = widget
        if widget is not None:
            widget.setParent(self)


class _UIRightHarness(UIMixin):
    MIN_MAP_WIDTH = 180

    def __init__(self):
        self._load_initial_map_position_async = MagicMock()

    def _on_map_loaded(self):
        return None

    def _on_map_position_copied(self, lat, lng):
        return None


class _UILayoutHarness(UIMixin):
    TREE_WIN_WIDTH_RATE = 0.2
    TREE_WIN_HEIGHT_RATE = 1
    MAP_WIN_WIDTH_RATE = 0.3
    MAP_WIN_HEIGHT_RATE = 1
    CANVAS_WIN_WIDTH_RATE = 0.5
    CANVAS_WIN_HEIGHT_RATE = 1

    def __init__(self):
        self.logger = MagicMock()


class _UICenterHarness(UIMixin):
    MIN_PHOTO_FRAME_WIDTH = 220
    MIN_PHOTO_FRAME_HEIGHT = 160

    def __init__(self):
        self.bg_color = "#222222"
        self._icons_applied = False
        self._history_controls_updated = False
        self._pagination_updated = False

    def copy_gps_to_clipboard(self):
        return None

    def paste_gps_from_clipboard(self):
        return None

    def undo_last_gps_edit(self):
        return None

    def redo_last_gps_edit(self):
        return None

    def _create_settings_button(self):
        return QPushButton("Settings")

    def _apply_button_icons(self):
        self._icons_applied = True

    def _update_gps_history_controls(self):
        self._history_controls_updated = True

    def _update_pagination_controls(self):
        self._pagination_updated = True

    def show_first_page(self):
        return None

    def show_previous_page(self):
        return None

    def show_next_page(self):
        return None

    def show_last_page(self):
        return None


def test_get_system_theme_name_dark_and_light(qapp):
    harness = _ThemeHarness(_DummyApp(Qt.ColorScheme.Dark, qapp))
    assert harness._get_system_theme_name() == "dark"

    harness.app = _DummyApp(Qt.ColorScheme.Light, qapp)
    assert harness._get_system_theme_name() == "light"


def test_set_theme_colors_resolves_system_theme(qapp):
    harness = _ThemeHarness(_DummyApp(Qt.ColorScheme.Dark, qapp))

    harness._set_theme_colors(SYSTEM_THEME)

    assert harness.theme_choice == SYSTEM_THEME
    assert harness.theme_name == "dark"
    assert harness.bg_color == harness.theme["bg_color"]


def test_get_button_icon_falls_back_to_style_icon(qapp):
    harness = _ThemeHarness(_DummyApp(Qt.ColorScheme.Dark, qapp))

    with patch("viewer.mixins.theme.QIcon.fromTheme", return_value=QIcon()):
        icon = harness._get_button_icon("missing-theme-icon", QStyle.StandardPixmap.SP_ArrowBack)

    assert icon.isNull() is False


def test_update_splash_ignores_when_splash_missing(qapp):
    harness = _ThemeHarness(_DummyApp(Qt.ColorScheme.Dark, qapp))
    harness.splash = None
    harness.text_color = "#ffffff"

    harness._update_splash("hello")

    harness.app.processEvents.assert_not_called()


def test_update_splash_shows_message_and_processes_events(qapp):
    harness = _ThemeHarness(_DummyApp(Qt.ColorScheme.Dark, qapp))
    harness.text_color = "#ffffff"
    calls = []
    harness.splash = SimpleNamespace(showMessage=lambda *args: calls.append(args))

    harness._update_splash("hello")

    assert len(calls) == 1
    assert calls[0][0] == "hello"
    harness.app.processEvents.assert_called_once()


def test_apply_theme_stylesheet_updates_root_photo_frame_and_labels(qapp):
    harness = _ThemeHarness(_DummyApp(Qt.ColorScheme.Dark, qapp))
    harness._set_theme_colors("dark")
    harness._apply_button_icons = MagicMock()
    harness._apply_native_titlebar_theme = MagicMock()

    harness._apply_theme_stylesheet()

    assert "QMainWindow" in harness.root.stylesheet
    assert "background-color" in harness.photo_frame.stylesheet
    harness._apply_photo_label_decoration.assert_called_once_with(harness.image_labels[0])
    harness._apply_button_icons.assert_called_once()
    harness._apply_native_titlebar_theme.assert_called_once()


def test_select_theme_persists_config_when_enabled(qapp):
    harness = _ThemeHarness(_DummyApp(Qt.ColorScheme.Dark, qapp))
    harness._apply_theme_stylesheet = MagicMock()

    harness.select_theme("dark", persist_config=True)

    assert harness.config["theme"] == "dark"
    harness.save_config.assert_called_once()
    harness._sync_theme_menu_selection.assert_called_once()


def test_on_system_color_scheme_changed_only_for_system_choice(qapp):
    harness = _ThemeHarness(_DummyApp(Qt.ColorScheme.Dark, qapp))
    harness.select_theme = MagicMock()

    harness.theme_choice = SYSTEM_THEME
    harness._on_system_color_scheme_changed(None)
    harness.select_theme.assert_called_once_with(SYSTEM_THEME, persist_config=False)

    harness.select_theme.reset_mock()
    harness.theme_choice = "dark"
    harness._on_system_color_scheme_changed(None)
    harness.select_theme.assert_not_called()


def test_setup_right_panel_initializes_map_and_connects_load_signal():
    harness = _UIRightHarness()
    with patch("viewer.mixins.ui.MapWidget", _DummyMapWidget):
        harness._setup_right_panel()

    assert isinstance(harness.map_widget, _DummyMapWidget)
    assert harness.map_widget.min_width == harness.MIN_MAP_WIDTH
    assert harness._on_map_loaded in harness.map_widget.loadFinished.callbacks
    harness._load_initial_map_position_async.assert_called_once()


def test_load_initial_map_position_async_starts_daemon_thread():
    harness = _UIRightHarness()
    harness._fetch_initial_map_position_background = MagicMock()
    thread_obj = MagicMock()

    with patch("viewer.mixins.ui.threading.Thread", return_value=thread_obj) as thread_ctor:
        UIMixin._load_initial_map_position_async(harness)

    thread_ctor.assert_called_once()
    kwargs = thread_ctor.call_args.kwargs
    assert kwargs["daemon"] is True
    assert kwargs["target"] == harness._fetch_initial_map_position_background
    thread_obj.start.assert_called_once()


def test_setup_layout_dims_uses_explicit_dimensions():
    harness = _UILayoutHarness()

    harness.setup_layout_dims(width=1000, height=500)

    assert harness.window_width == 1000
    assert harness.window_height == 500
    assert harness.tree_width == 200
    assert harness.map_width == 300
    assert harness.photo_frames_width == 500


def test_setup_layout_dims_uses_primary_screen_when_not_provided():
    harness = _UILayoutHarness()
    geom = SimpleNamespace(width=lambda: 1500, height=lambda: 900)
    dummy_app = SimpleNamespace(primaryScreen=lambda: SimpleNamespace(availableGeometry=lambda: geom))

    with patch("viewer.mixins.ui.QApplication.instance", return_value=dummy_app):
        harness.setup_layout_dims()

    assert harness.window_width == 1200
    assert harness.window_height == 720
    harness.logger.debug.assert_called_once()


def test_setup_center_panel_builds_arrow_only_pagination_controls(qapp):
    harness = _UICenterHarness()

    panel = harness._setup_center_panel()

    assert panel is not None
    assert harness.first_page_button.text() == ""
    assert harness.prev_page_button.text() == ""
    assert harness.next_page_button.text() == ""
    assert harness.last_page_button.text() == ""
    assert harness.back_to_grid_button.text() == "Back to grid"
    assert harness.back_to_grid_button.isEnabled() is False
    assert harness.back_to_grid_button.isVisible() is False
    assert harness.page_status_label.alignment() == Qt.AlignmentFlag.AlignCenter
    assert harness._icons_applied is True
    assert harness._history_controls_updated is True
    assert harness._pagination_updated is True


def test_build_stylesheet_includes_tooltip_rules_for_theme_readability():
    stylesheet = build_stylesheet(**THEME_PRESETS["dark"])

    assert "QToolTip" in stylesheet
    assert "background-color: #343638" in stylesheet
    assert "color: #dce4ee" in stylesheet
