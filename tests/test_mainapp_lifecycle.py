import json
import queue
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QWidget

from viewer.app import MainApp
from viewer.ui.styling import DEFAULT_THEME


class _DummySignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)


class _DummyMapWidget(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.loadFinished = _DummySignal()
        self.copy_position = _DummySignal()

    def set_position(self, *args, **kwargs):
        return None

    def delete_all_marker(self):
        return None

    def set_overlay(self, widget):
        if widget is not None:
            widget.setParent(self)


class _DummyExifTool:
    def get_list_of_supported_extensions(self):
        return []


class _DummyRegistry:
    def add_wrapper(self, _wrapper):
        return None


def test_run_starts_runtime_once():
    app_obj = MainApp.__new__(MainApp)
    app_obj._started = False
    app_obj.nb_mp_processes = 2
    app_obj._start_background_workers = MagicMock()
    app_obj._update_splash = MagicMock()
    app_obj._apply_theme_stylesheet = MagicMock()
    app_obj._finalize_and_show_window = MagicMock()
    app_obj.loading = True

    fake_pool = object()
    with patch("viewer.app.mp.Pool", return_value=fake_pool) as pool_ctor:
        app_obj.run()
        app_obj.run()  # second call should be a no-op

    assert app_obj._started is True
    assert app_obj.mp_pool is fake_pool
    assert app_obj.loading is False
    pool_ctor.assert_called_once()
    args, kwargs = pool_ctor.call_args
    assert args == (2,)
    assert kwargs.get("initializer") is not None
    app_obj._start_background_workers.assert_called_once()
    app_obj._apply_theme_stylesheet.assert_called_once()
    app_obj._finalize_and_show_window.assert_called_once()


def test_on_quit_terminates_pool_when_present():
    app_obj = MainApp.__new__(MainApp)
    app_obj.running = True
    app_obj.map_widget = None
    pool = MagicMock()
    app_obj.mp_pool = pool

    app_obj._on_quit()

    assert app_obj.running is False
    pool.terminate.assert_called_once()
    pool.join.assert_called_once()
    assert app_obj.mp_pool is None


def test_on_quit_handles_missing_pool():
    app_obj = MainApp.__new__(MainApp)
    app_obj.running = True
    app_obj.map_widget = None
    app_obj.mp_pool = None

    app_obj._on_quit()

    assert app_obj.running is False
    assert app_obj.mp_pool is None


def test_on_quit_wakes_worker_queues_with_stop_signal():
    app_obj = MainApp.__new__(MainApp)
    app_obj.running = True
    app_obj.map_widget = None
    app_obj.mp_pool = None
    app_obj.WORKER_STOP_SIGNAL = None
    app_obj.map_location_queue = MagicMock()
    app_obj.display_image_queue = MagicMock()

    app_obj._on_quit()

    app_obj.map_location_queue.put.assert_called_once_with(None)
    app_obj.display_image_queue.put.assert_called_once_with(None)


def test_refresh_file_invalidates_cache_and_enqueues_reload():
    app_obj = MainApp.__new__(MainApp)
    app_obj.canvas_selected_fpath = "photo.jpg"
    app_obj.canvas_selected_fpath_loaded = True
    app_obj.images = {"photo.jpg": object(), "other.jpg": object()}
    app_obj.image_load_queue = queue.LifoQueue()

    app_obj.refresh_file("photo.jpg")

    assert app_obj.canvas_selected_fpath_loaded is False
    assert "photo.jpg" not in app_obj.images
    assert "other.jpg" in app_obj.images
    assert app_obj.image_load_queue.get_nowait() == "photo.jpg"


def test_create_for_tests_builds_gui_without_runtime_start(qapp, monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        json.dumps({
            "theme": "dark",
            "grid_items_per_page": 4,
            "base_dir_labels": ["Temp"],
            "base_dirs": [str(tmp_path)],
            "base_dir_selected_label": "Temp",
        }),
        encoding="utf-8",
    )

    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr("viewer.app.MainApp.get_config_fpath", staticmethod(lambda copy_local=False: str(config_path)))
    monkeypatch.setattr("viewer.app.MainApp.update_tree", lambda self: None)
    monkeypatch.setattr("viewer.app.MainApp._load_initial_map_position_async", lambda self: None)
    monkeypatch.setattr("viewer.mixins.ui.MapWidget", _DummyMapWidget)
    monkeypatch.setattr("viewer.app.os.getcwd", lambda: str(project_root))

    app_obj = MainApp.create_for_tests(_DummyRegistry(), _DummyExifTool(), use_logging=False)

    assert app_obj.root is not None
    assert app_obj.tree is not None
    assert app_obj.photo_frame is not None
    assert app_obj.map_widget is not None
    assert app_obj.splash is None
    assert app_obj._show_splash is False
    assert app_obj._started is False
    assert app_obj.mp_pool is None


def test_on_map_loaded_with_initial_position():
    app_obj = MainApp.__new__(MainApp)
    app_obj._map_loaded = False
    app_obj._initial_map_pos = (10.0, 20.0)
    app_obj.map_widget = MagicMock()
    
    app_obj._on_map_loaded()
    
    assert app_obj._map_loaded is True
    app_obj.map_widget.set_position.assert_called_once_with(10.0, 20.0, marker=True)
    assert app_obj._initial_map_pos is None

def test_on_map_loaded_without_initial_position():
    app_obj = MainApp.__new__(MainApp)
    app_obj._map_loaded = False
    app_obj._initial_map_pos = None
    app_obj.map_widget = MagicMock()
    
    app_obj._on_map_loaded()
    
    assert app_obj._map_loaded is True
    app_obj.map_widget.set_position.assert_not_called()
    assert app_obj._initial_map_pos is None

def test_on_quit_closes_map_widget_if_present():
    app_obj = MainApp.__new__(MainApp)
    app_obj.running = True
    app_obj.mp_pool = None
    app_obj.map_widget = MagicMock()
    
    app_obj._on_quit()
    
    assert app_obj.running is False
    app_obj.map_widget.close.assert_called_once()

def test_about_button_click_shows_dialog():
    app_obj = MainApp.__new__(MainApp)
    app_obj.root = MagicMock()
    app_obj.link_color = "#123456"
    
    with patch("viewer.app.AboutDialog") as mock_dialog_class:
        mock_dialog_instance = MagicMock()
        mock_dialog_class.return_value = mock_dialog_instance
        
        app_obj.about_button_click()
        
        mock_dialog_class.assert_called_once_with(app_obj.root, link_color="#123456")
        mock_dialog_instance.exec.assert_called_once()

def test_init_config_saves_when_defaults_applied(tmp_path, monkeypatch):
    app_obj = MainApp.__new__(MainApp)
    app_obj.use_logging = False
    app_obj.exiftool = MagicMock()
    app_obj.exiftool.get_list_of_supported_extensions.return_value = []
    
    config_path = tmp_path / "config.yaml"
    # Provide an empty config dict so it falls back to defaults
    config_path.write_text(json.dumps({}), encoding="utf-8")
    
    monkeypatch.setattr("viewer.app.MainApp.get_config_fpath", staticmethod(lambda copy_local=False: str(config_path)))
    
    # We will mock save_config to verify it gets called
    app_obj.save_config = MagicMock()
    app_obj.sanitize_grid_items_per_page = staticmethod(lambda x: 4)
    
    import yaml
    with patch("viewer.app.yaml.safe_load", return_value={}):
        app_obj._init_config_and_logger()
    
    assert app_obj._config_updated is True
    app_obj.save_config.assert_called_once()
    assert hasattr(app_obj, 'theme_choice')

def test_init_config_skips_save_when_valid(tmp_path, monkeypatch):
    app_obj = MainApp.__new__(MainApp)
    app_obj.use_logging = False
    app_obj.exiftool = MagicMock()
    app_obj.exiftool.get_list_of_supported_extensions.return_value = []
    
    config_path = tmp_path / "config.yaml"
    # Provide a fully valid config
    config_path.write_text(json.dumps({"theme": "dark", "grid_items_per_page": 4}), encoding="utf-8")
    
    monkeypatch.setattr("viewer.app.MainApp.get_config_fpath", staticmethod(lambda copy_local=False: str(config_path)))
    
    app_obj.save_config = MagicMock()
    # Mock normalize_theme_choice and sanitize_grid_items_per_page
    monkeypatch.setattr("viewer.app.normalize_theme_choice", lambda x: x)
    app_obj.sanitize_grid_items_per_page = staticmethod(lambda x: x)
    
    import yaml
    with patch("viewer.app.yaml.safe_load", return_value={"theme": "dark", "grid_items_per_page": 4}):
        app_obj._init_config_and_logger()
    
    assert app_obj._config_updated is False
    app_obj.save_config.assert_not_called()

def test_start_background_workers_spawns_threads():
    app_obj = MainApp.__new__(MainApp)
    app_obj.load_images_background = MagicMock()
    app_obj.display_image_background = MagicMock()
    app_obj.load_file_gps_flags_background = MagicMock()
    app_obj.map_location_background = MagicMock()
    
    with patch("viewer.app.threading.Thread") as mock_thread_class:
        thread_instances = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        mock_thread_class.side_effect = thread_instances
        
        app_obj._start_background_workers()
        
        assert mock_thread_class.call_count == 4
        expected_targets = [
            app_obj.load_images_background,
            app_obj.display_image_background,
            app_obj.load_file_gps_flags_background,
            app_obj.map_location_background,
        ]
        for index, expected_target in enumerate(expected_targets):
            call_kwargs = mock_thread_class.call_args_list[index].kwargs
            assert call_kwargs["daemon"] is True
            assert call_kwargs["target"] == expected_target
            thread_instances[index].start.assert_called_once()


def test_persist_ui_state_saves_geometry_and_splitter():
    app_obj = MainApp.__new__(MainApp)
    app_obj.config = {}
    app_obj.save_config = MagicMock()

    geometry = MagicMock()
    geometry.width.return_value = 1200
    geometry.height.return_value = 720
    geometry.x.return_value = 100
    geometry.y.return_value = 50

    app_obj.root = MagicMock()
    app_obj.root.isMaximized.return_value = False
    app_obj.root.geometry.return_value = geometry
    app_obj.main_splitter = MagicMock()
    app_obj.main_splitter.sizes.return_value = [220, 640, 360]

    app_obj._persist_ui_state()

    assert app_obj.config["window_geometry"] == {
        "width": 1200,
        "height": 720,
        "x": 100,
        "y": 50,
        "maximized": False,
    }
    assert app_obj.config["splitter_sizes"] == [220, 640, 360]
    app_obj.save_config.assert_called_once()


def test_finalize_and_show_window_restores_saved_geometry_and_maximizes():
    app_obj = MainApp.__new__(MainApp)
    app_obj._window_geometry = {
        "width": 1000,
        "height": 700,
        "x": 120,
        "y": 80,
        "maximized": True,
    }
    app_obj._update_splash = MagicMock()
    app_obj._apply_native_titlebar_theme = MagicMock()
    app_obj._prompt_terms_if_needed = MagicMock(return_value=True)
    app_obj.root = MagicMock()
    app_obj.splash = None

    screen = MagicMock()
    screen.width.return_value = 1920
    screen.height.return_value = 1080
    screen.x.return_value = 0
    screen.y.return_value = 0

    app_obj.app = MagicMock()
    app_obj.app.primaryScreen.return_value.availableGeometry.return_value = screen

    app_obj._finalize_and_show_window()

    app_obj.root.resize.assert_called_once_with(1000, 700)
    app_obj.root.move.assert_called_once_with(120, 80)
    app_obj.root.show.assert_not_called()
    app_obj.root.showMaximized.assert_called_once()
    app_obj._apply_native_titlebar_theme.assert_called_once()
    app_obj.app.aboutToQuit.connect.assert_called_once_with(app_obj._on_quit)
    app_obj.app.exec.assert_called_once()
