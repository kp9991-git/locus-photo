import os
import pytest
from unittest.mock import MagicMock, patch

import viewer.metadata.exiftool_wrapper as exiftool_wrapper
from viewer.core.constants import EXIFTOOL_WINDOWS_PATH, EXIFTOOL_UNIX_PATH
from viewer.core.enums import MetaTagName
from viewer.metadata.exiftool_wrapper import ExifToolWrapper, ExifToolWrapperRegistry


def test_registry_terminate_calls_wrappers_and_clears_registry():
    registry = ExifToolWrapperRegistry()
    registry.wrappers = []

    wrapper_one = MagicMock()
    wrapper_two = MagicMock()

    registry.add_wrapper(wrapper_one)
    registry.add_wrapper(wrapper_two)
    registry.terminate()

    wrapper_one.terminate.assert_called_once()
    wrapper_two.terminate.assert_called_once()
    assert registry.wrappers == []


def test_init_uses_local_exiftool_executable():
    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper") as helper_ctor:
        ExifToolWrapper()

    expected_relative = EXIFTOOL_WINDOWS_PATH if os.name == "nt" else EXIFTOOL_UNIX_PATH
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(exiftool_wrapper.__file__)))
    expected_executable = os.path.normpath(os.path.join(project_root, expected_relative))
    helper_ctor.assert_called_once_with(
        executable=expected_executable,
        common_args=["-G"],
        check_execute=False,
    )


def test_get_jpegfromraw_and_get_previewimage_use_raw_bytes_execute():
    helper = MagicMock()
    helper.execute.side_effect = [b"jpeg-bytes", b"preview-bytes"]

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper()

    jpeg = wrapper.get_jpegfromraw("a.raw")
    preview = wrapper.get_previewimage("a.raw")

    assert jpeg == b"jpeg-bytes"
    assert preview == b"preview-bytes"
    helper.execute.assert_any_call("-b", "-jpgfromraw", "a.raw", raw_bytes=True)
    helper.execute.assert_any_call("-b", "-previewimage", "a.raw", raw_bytes=True)


def test_get_meta_data_parses_recursive_output_with_numerical_tags():
    helper = MagicMock()
    helper.execute.return_value = (
        "======== child.jpg\r\n"
        "[Composite] GPS Latitude : 10.5\n"
        "[Composite] GPS Longitude : -2\n"
    )

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper(logger=MagicMock())

    result = wrapper.get_meta_data(
        "C:/folder",
        tags=[MetaTagName.GPSLatitude, MetaTagName.GPSLongitude],
        recursive=True,
    )

    expected_key = os.path.join("C:/folder", "child.jpg")
    assert result[expected_key][MetaTagName.GPSLatitude] == 10.5
    assert result[expected_key][MetaTagName.GPSLongitude] == -2.0
    assert helper.execute.call_args.args == (
        "-GPSLatitude",
        "-GPSLongitude",
        "-n",
        "-r",
        "C:/folder",
    )


def test_get_meta_data_returns_empty_map_for_file_without_tags():
    helper = MagicMock()
    helper.execute.return_value = ""

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper()

    result = wrapper.get_meta_data("photo.jpg", tags=[MetaTagName.GPSLatitude], recursive=False)

    assert result == {"photo.jpg": {}}


def test_extract_meta_data_item_parses_valid_line_and_ignores_invalid():
    tag, value = ExifToolWrapper.extract_meta_data_item("[Composite] GPS Latitude : 33.3")
    assert tag == MetaTagName.GPSLatitude
    assert value == 33.3

    tag, value = ExifToolWrapper.extract_meta_data_item("not a metadata line")
    assert tag is None
    assert value is None


def test_get_list_of_supported_extensions_success_and_failure():
    helper = MagicMock()
    helper.execute.return_value = "Supported\nJPG JPEG\nPNG"

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper()

    assert wrapper.get_list_of_supported_extensions() == [".jpg", ".jpeg", ".png"]

    helper.execute.side_effect = RuntimeError("failed")
    assert wrapper.get_list_of_supported_extensions() is None


def test_get_version_success_and_failure():
    helper = MagicMock()
    helper.execute.return_value = "12.90\n"

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper()

    assert wrapper.get_version() == "12.90"

    helper.execute.side_effect = RuntimeError("failed")
    assert wrapper.get_version() is None


def test_set_meta_data_adds_latitude_and_longitude_refs():
    helper = MagicMock()
    helper.execute.return_value = "updated"

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper(logger=MagicMock())

    tags = {
        MetaTagName.GPSLatitude: -10.0,
        MetaTagName.GPSLongitude: 20.0,
        MetaTagName.GPSAltitude: 100.0,
    }

    result = wrapper.set_meta_data("photo.jpg", tags)

    args = helper.execute.call_args.args
    assert args[0:2] == ("-overwrite_original", "-n")
    assert "-GPSLatitude=-10.0" in args
    assert "-GPSLatitudeRef=S" in args
    assert "-GPSLongitude=20.0" in args
    assert "-GPSLongitudeRef=E" in args
    assert "-GPSAltitude=100.0" in args
    assert args[-1] == "photo.jpg"
    assert result == "updated"


def test_clear_meta_data_builds_expected_arguments():
    helper = MagicMock()
    helper.execute.return_value = "cleared"

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper(logger=MagicMock())

    result = wrapper.clear_meta_data("photo.jpg", [MetaTagName.GPSLatitude, MetaTagName.GPSLongitude])

    assert helper.execute.call_args.args == (
        "-overwrite_original",
        "-GPSLatitude=",
        "-GPSLongitude=",
        "photo.jpg",
    )
    assert result == "cleared"


def test_set_meta_data_raises_timeout_error_when_exiftool_times_out():
    helper = MagicMock()
    helper.execute.return_value = "unused"

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper(logger=MagicMock())

    with patch.object(wrapper, "_execute_with_timeout", return_value=None):
        with pytest.raises(TimeoutError):
            wrapper.set_meta_data("photo.jpg", {MetaTagName.GPSLatitude: 10.0})


def test_clear_meta_data_raises_timeout_error_when_exiftool_times_out():
    helper = MagicMock()
    helper.execute.return_value = "unused"

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper(logger=MagicMock())

    with patch.object(wrapper, "_execute_with_timeout", return_value=None):
        with pytest.raises(TimeoutError):
            wrapper.clear_meta_data("photo.jpg", [MetaTagName.GPSLatitude])


def test_set_meta_data_logs_redacted_gps_arguments_when_enabled():
    helper = MagicMock()
    helper.execute.return_value = "updated"
    logger = MagicMock()

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper(logger=logger, redact_gps_logs=True)

    wrapper.set_meta_data(
        "photo.jpg",
        {
            MetaTagName.GPSLatitude: -10.0,
            MetaTagName.GPSLongitude: 20.0,
            MetaTagName.GPSAltitude: 100.0,
        },
    )

    arg_log = None
    for call in logger.info.call_args_list:
        if call.args and call.args[0] == "Updating meta tags. Arguments: %s":
            arg_log = call.args[1]
            break

    assert arg_log is not None
    assert "-GPSLatitude=<redacted>" in arg_log
    assert "-GPSLongitude=<redacted>" in arg_log
    assert "-GPSAltitude=<redacted>" in arg_log


def test_apply_meta_data_builds_single_transactional_command():
    helper = MagicMock()
    helper.execute.return_value = "updated"

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper(logger=MagicMock())

    wrapper.apply_meta_data(
        "photo.jpg",
        tags={
            MetaTagName.GPSLatitude: -10.0,
            MetaTagName.GPSLongitude: 20.0,
        },
        clear_tags=[MetaTagName.GPSAltitude, MetaTagName.GPSLatitude, MetaTagName.GPSLongitude],
    )

    args = helper.execute.call_args.args
    assert args[0:2] == ("-overwrite_original", "-n")
    assert "-GPSAltitude=" in args
    assert "-GPSLatitude=" in args
    assert "-GPSLongitude=" in args
    assert "-GPSLatitudeRef=" in args
    assert "-GPSLongitudeRef=" in args
    assert "-GPSLatitude=-10.0" in args
    assert "-GPSLatitudeRef=S" in args
    assert "-GPSLongitude=20.0" in args
    assert "-GPSLongitudeRef=E" in args
    assert args[-1] == "photo.jpg"


def test_apply_meta_data_raises_timeout_error_when_exiftool_times_out():
    helper = MagicMock()
    helper.execute.return_value = "unused"

    with patch("viewer.metadata.exiftool_wrapper.ExifToolHelper", return_value=helper):
        wrapper = ExifToolWrapper(logger=MagicMock())

    with patch.object(wrapper, "_execute_with_timeout", return_value=None):
        with pytest.raises(TimeoutError):
            wrapper.apply_meta_data(
                "photo.jpg",
                tags={MetaTagName.GPSLatitude: 10.0},
                clear_tags=[MetaTagName.GPSLatitude],
            )
