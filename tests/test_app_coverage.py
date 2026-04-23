import pytest
from unittest.mock import MagicMock, patch
from viewer.app import MainApp
import os
import sys

def test_init_config_and_logger_with_logger(tmp_path, monkeypatch):
    app_obj = MainApp.__new__(MainApp)
    app_obj.use_logging = True
    
    mock_logger = MagicMock()
    monkeypatch.setattr("viewer.app.get_logger", lambda *args, **kwargs: mock_logger)
    
    app_obj.exiftool = MagicMock()
    app_obj.exiftool.get_version.return_value = "12.90"
    app_obj.exiftool.get_list_of_supported_extensions.return_value = [".jpg"]
    
    config_path = tmp_path / "config.yaml"
    import json
    config_path.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr("viewer.app.MainApp.get_config_fpath", staticmethod(lambda copy_local=False: str(config_path)))
    
    app_obj.save_config = MagicMock()
    app_obj.sanitize_grid_items_per_page = staticmethod(lambda x: 4)
    
    import yaml
    with patch("viewer.app.yaml.safe_load", return_value={}):
        app_obj._init_config_and_logger()
        
    assert mock_logger.info.call_count == 3
    mock_logger.info.assert_any_call("ExifTool version: 12.90")
    mock_logger.info.assert_any_call("Supported extensions from exiftool: ['.jpg']")


def test_init_config_and_logger_can_disable_logging_from_config(tmp_path, monkeypatch):
    app_obj = MainApp.__new__(MainApp)
    app_obj.use_logging = True

    app_obj.exiftool = MagicMock()
    app_obj.exiftool.get_list_of_supported_extensions.return_value = []

    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("viewer.app.MainApp.get_config_fpath", staticmethod(lambda copy_local=False: str(config_path)))

    app_obj.save_config = MagicMock()
    app_obj.sanitize_grid_items_per_page = staticmethod(lambda x: 4)

    with patch("viewer.app.yaml.safe_load", return_value={"logging": {"enabled": False}}):
        app_obj._init_config_and_logger()

    assert app_obj.use_logging is False
    assert app_obj.logger is None


def test_init_config_and_logger_reads_log_level_from_config(tmp_path, monkeypatch):
    app_obj = MainApp.__new__(MainApp)
    app_obj.use_logging = True

    captured = {}
    mock_logger = MagicMock()

    def fake_get_logger(level=None):
        captured["level"] = level
        return mock_logger

    monkeypatch.setattr("viewer.app.get_logger", fake_get_logger)

    app_obj.exiftool = MagicMock()
    app_obj.exiftool.get_version.return_value = "13.55"
    app_obj.exiftool.get_list_of_supported_extensions.return_value = []

    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("viewer.app.MainApp.get_config_fpath", staticmethod(lambda copy_local=False: str(config_path)))

    app_obj.save_config = MagicMock()
    app_obj.sanitize_grid_items_per_page = staticmethod(lambda x: 4)

    with patch("viewer.app.yaml.safe_load", return_value={"logging": {"enabled": True, "level": "debug"}}):
        app_obj._init_config_and_logger()

    assert captured.get("level") == "DEBUG"
    assert app_obj.log_level_name == "DEBUG"


def test_init_config_and_logger_reads_diagnostics_and_redaction_flags(tmp_path, monkeypatch):
    app_obj = MainApp.__new__(MainApp)
    app_obj.use_logging = False
    app_obj.log_diagnostics = False
    app_obj.log_redact_gps = True

    app_obj.exiftool = MagicMock()
    app_obj.exiftool.get_list_of_supported_extensions.return_value = []

    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("viewer.app.MainApp.get_config_fpath", staticmethod(lambda copy_local=False: str(config_path)))

    app_obj.save_config = MagicMock()
    app_obj.sanitize_grid_items_per_page = staticmethod(lambda x: 4)

    with patch(
        "viewer.app.yaml.safe_load",
        return_value={"logging": {"enabled": False, "diagnostics": True, "redact_gps": False}},
    ):
        app_obj._init_config_and_logger()

    assert app_obj.log_diagnostics is True
    assert app_obj.log_redact_gps is False


def test_init_config_and_logger_starts_network_diagnostics_once(tmp_path, monkeypatch):
    app_obj = MainApp.__new__(MainApp)
    app_obj.use_logging = True
    app_obj.log_diagnostics = False
    app_obj.log_redact_gps = True
    app_obj._network_diagnostics_started = False

    mock_logger = MagicMock()
    monkeypatch.setattr("viewer.app.get_logger", lambda *args, **kwargs: mock_logger)

    app_obj.exiftool = MagicMock()
    app_obj.exiftool.get_version.return_value = "13.99"
    app_obj.exiftool.get_list_of_supported_extensions.return_value = []

    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("viewer.app.MainApp.get_config_fpath", staticmethod(lambda copy_local=False: str(config_path)))

    app_obj.save_config = MagicMock()
    app_obj.sanitize_grid_items_per_page = staticmethod(lambda x: 4)
    app_obj._start_network_diagnostics_async = MagicMock()

    with patch("viewer.app.yaml.safe_load", return_value={"logging": {"enabled": True, "diagnostics": True}}):
        app_obj._init_config_and_logger()

    app_obj._start_network_diagnostics_async.assert_called_once()


def test_init_config_and_logger_sets_run_id_env(tmp_path, monkeypatch):
    app_obj = MainApp.__new__(MainApp)
    app_obj.use_logging = True
    app_obj.log_diagnostics = False
    app_obj.log_redact_gps = True

    mock_logger = MagicMock()
    monkeypatch.setattr("viewer.app.get_logger", lambda *args, **kwargs: mock_logger)
    monkeypatch.delenv("LOCUS_PHOTO_LOG_RUN_ID", raising=False)

    app_obj.exiftool = MagicMock()
    app_obj.exiftool.get_version.return_value = "13.99"
    app_obj.exiftool.get_list_of_supported_extensions.return_value = []

    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("viewer.app.MainApp.get_config_fpath", staticmethod(lambda copy_local=False: str(config_path)))

    app_obj.save_config = MagicMock()
    app_obj.sanitize_grid_items_per_page = staticmethod(lambda x: 4)

    with patch("viewer.app.yaml.safe_load", return_value={"logging": {"enabled": True}}):
        app_obj._init_config_and_logger()

    run_id = os.environ.get("LOCUS_PHOTO_LOG_RUN_ID")
    assert run_id is not None
    assert len(run_id) == 12
    assert app_obj.log_run_id == run_id

def test_setup_main_window_and_theme_custom_titlebar():
    app_obj = MainApp.__new__(MainApp)
    app_obj.theme_choice = "dark"
    app_obj._show_splash = False
    
    with patch("viewer.app.QApplication.instance", return_value=MagicMock()), \
         patch("viewer.app.QApplication", return_value=MagicMock()), \
         patch("viewer.app.QMainWindow") as mock_qmainwindow, \
         patch("viewer.app.platform.system", return_value="Linux"), \
         patch.object(app_obj, "_setup_gps_shortcuts"), \
         patch.object(app_obj, "_set_theme_colors"):
        
        mock_root = MagicMock()
        mock_qmainwindow.return_value = mock_root
        
        app_obj._setup_main_window_and_theme()
        
        assert app_obj.use_custom_title_bar is True
        mock_root.setWindowFlags.assert_called_once()

def test_setup_main_window_and_theme_with_splash():
    app_obj = MainApp.__new__(MainApp)
    app_obj.theme_choice = "dark"
    app_obj._show_splash = True
    app_obj._create_splash_screen = MagicMock()
    app_obj._update_splash = MagicMock()
    
    with patch("viewer.app.QApplication.instance", return_value=MagicMock()), \
         patch("viewer.app.QApplication", return_value=MagicMock()), \
         patch("viewer.app.QMainWindow"), \
         patch("viewer.app.platform.system", return_value="Windows"), \
         patch.object(app_obj, "_setup_gps_shortcuts"), \
         patch.object(app_obj, "_set_theme_colors"):
        
        app_obj._setup_main_window_and_theme()
        
        app_obj._create_splash_screen.assert_called_once()
        app_obj._update_splash.assert_called_once_with("Initializing...")

def test_finalize_and_show_window():
    app_obj = MainApp.__new__(MainApp)
    app_obj.app = MagicMock()
    app_obj.root = MagicMock()
    app_obj.splash = MagicMock()
    app_obj._update_splash = MagicMock()
    app_obj._apply_native_titlebar_theme = MagicMock()
    app_obj._prompt_terms_if_needed = MagicMock(return_value=True)

    mock_screen = MagicMock()
    mock_screen.width.return_value = 1920
    mock_screen.height.return_value = 1080
    mock_screen.x.return_value = 0
    mock_screen.y.return_value = 0
    app_obj.app.primaryScreen.return_value.availableGeometry.return_value = mock_screen
    
    # Do not block on exec
    app_obj.app.exec.return_value = 0
    
    splash_mock = app_obj.splash
    
    app_obj._finalize_and_show_window()
    
    app_obj.root.resize.assert_called_once_with(1536, 864) # 1920*0.8, 1080*0.8
    app_obj.root.move.assert_called_once_with(192, 108)
    app_obj._update_splash.assert_called_once_with("Almost ready...")
    app_obj.root.show.assert_called_once()
    app_obj._apply_native_titlebar_theme.assert_called_once()
    splash_mock.finish.assert_called_once_with(app_obj.root)
    assert app_obj.splash is None
    app_obj.app.aboutToQuit.connect.assert_called_once_with(app_obj._on_quit)
    app_obj.app.exec.assert_called_once()
