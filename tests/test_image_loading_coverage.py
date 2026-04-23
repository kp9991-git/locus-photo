import pytest
from unittest.mock import MagicMock, patch, call
import os
import PIL.Image
from collections import OrderedDict

from viewer.mixins.image_loading import ImageLoadingMixin, _init_worker
import viewer.mixins.image_loading as image_loading_mixin

class _DummyQueue:
    def __init__(self, items):
        self.items = items
    
    def empty(self):
        return len(self.items) == 0

    def get(self):
        return self.items.pop(0)

class _DummyLock:
    def __enter__(self):
        pass
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class _DummyHarness(ImageLoadingMixin):
    def __init__(self):
        self.images = OrderedDict()
        self.max_cache_size = 3
        self.running = True
        self.image_load_queue = None
        self.nb_mp_processes = 2
        self.mp_pool = MagicMock()
        self.SUPPORTED_EXTENSIONS = [".jpg", ".raw"]
        self.IMAGE_SUPPORTED_EXTENSIONS = [".jpg"]
        self.use_logging = False
        self.MAX_FILE_SIZE = 1000
        self.thumbnail_via_exiftool = True
        self.read_raw_partially = True
        self.logger = MagicMock()
        self.exiftool = MagicMock()

def test_init_worker():
    with patch("viewer.mixins.image_loading.ExifToolWrapper") as mock_exiftool:
        _init_worker()
        assert image_loading_mixin._worker_exiftool is not None
        mock_exiftool.assert_called_once()
        image_loading_mixin._worker_exiftool = None # cleanup

@patch("viewer.mixins.image_loading.os.path.getsize")
def test_is_file_acceptable(mock_getsize):
    mock_getsize.return_value = 500
    
    # Acceptable
    assert ImageLoadingMixin._is_file_acceptable("test.jpg", 1000, [".jpg", ".png"]) is True
    
    # Extension not supported
    assert ImageLoadingMixin._is_file_acceptable("test.raw", 1000, [".jpg"]) is False
    
    # Size too large
    mock_getsize.return_value = 1500
    assert ImageLoadingMixin._is_file_acceptable("test.jpg", 1000, [".jpg"]) is False
    
    # No supported extensions specified
    assert ImageLoadingMixin._is_file_acceptable("test.jpg", 2000, None) is True
    
    # OSError
    mock_getsize.side_effect = OSError("File not found")
    assert ImageLoadingMixin._is_file_acceptable("test.jpg", 1000, [".jpg"]) is False

@patch("viewer.mixins.image_loading.PIL.Image.open")
def test_load_image_supported_ext(mock_pil_open):
    mock_exiftool = MagicMock()
    mock_exiftool.get_meta_data.return_value = {"test.jpg": {"metadata": "info"}}
    mock_pil_open.return_value = MagicMock()
    
    with patch("viewer.mixins.image_loading.os.path.getsize", return_value=100):
        with patch("viewer.mixins.image_loading.resize_image") as mock_resize:
            mock_resize.return_value = "resized_image"
            result = ImageLoadingMixin.load_image(
                "test.jpg", False, mock_exiftool, 1000, [".jpg"], [".jpg"], True, True
            )
            
            assert result is not None
            assert result.img == "resized_image"
            assert result.meta_data_num == {"metadata": "info"}

@patch("viewer.mixins.image_loading.PIL.Image.open")
def test_load_image_thumbnail_via_exiftool_jpegfromraw(mock_pil_open):
    mock_exiftool = MagicMock()
    mock_exiftool.get_meta_data.return_value = {"test.raw": {}}
    mock_exiftool.get_jpegfromraw.return_value = b"jpegdata"
    mock_pil_open.return_value = "pil_image"
    
    with patch("viewer.mixins.image_loading.os.path.getsize", return_value=100):
        with patch("viewer.mixins.image_loading.resize_image", return_value="resized_image"):
            result = ImageLoadingMixin.load_image(
                "test.raw", False, mock_exiftool, 1000, [".raw"], [".jpg"], True, True
            )
            
            assert result.img == "resized_image"
            mock_exiftool.get_jpegfromraw.assert_called_once_with("test.raw")

@patch("viewer.mixins.image_loading.PIL.Image.open")
def test_load_image_thumbnail_via_exiftool_previewimage(mock_pil_open):
    mock_exiftool = MagicMock()
    mock_exiftool.get_meta_data.return_value = {"test.raw": {}}
    mock_exiftool.get_jpegfromraw.side_effect = Exception("No jpegfromraw")
    mock_exiftool.get_previewimage.return_value = b"previewdata"
    mock_pil_open.return_value = "pil_image"
    
    with patch("viewer.mixins.image_loading.os.path.getsize", return_value=100):
        with patch("viewer.mixins.image_loading.resize_image", return_value="resized_image"):
            result = ImageLoadingMixin.load_image(
                "test.raw", True, mock_exiftool, 1000, [".raw"], [".jpg"], True, True
            )
            
            assert result.img == "resized_image"
            mock_exiftool.get_previewimage.assert_called_once_with("test.raw")

def test_load_image_unacceptable_file():
    with patch("viewer.mixins.image_loading.ImageLoadingMixin._is_file_acceptable", return_value=False):
        result = ImageLoadingMixin.load_image("bad.jpg", True, None, 1000, None, None, True, True)
        assert result is None

@patch("viewer.mixins.image_loading.ExifToolWrapper")
@patch("viewer.mixins.image_loading.PIL.Image.open")
def test_load_image_exiftool_none(mock_pil_open, mock_exif_wrapper):
    mock_exif_instance = MagicMock()
    mock_exif_wrapper.return_value = mock_exif_instance
    mock_exif_instance.get_meta_data.return_value = {"test.jpg": {}}
    mock_pil_open.return_value = "pil_image"
    
    # reset _worker_exiftool just in case
    image_loading_mixin._worker_exiftool = None
    
    with patch("viewer.mixins.image_loading.ImageLoadingMixin._is_file_acceptable", return_value=True):
        with patch("viewer.mixins.image_loading.resize_image", return_value="resized"):
            result = ImageLoadingMixin.load_image("test.jpg", False, None, 1000, None, [".jpg"], True, True)
            assert result is not None
            mock_exif_wrapper.assert_called_once()

@patch("viewer.mixins.image_loading.rawpy.imread")
@patch("viewer.mixins.image_loading.PIL.Image.open")
def test_load_image_read_raw_partially(mock_pil_open, mock_imread):
    mock_exiftool = MagicMock()
    mock_exiftool.get_meta_data.return_value = {"test.raw": {}}
    mock_exiftool.get_jpegfromraw.side_effect = Exception("err")
    mock_exiftool.get_previewimage.side_effect = Exception("err")
    
    mock_pil_open.return_value = "pil_image"
    mock_raw = MagicMock()
    mock_preview = MagicMock()
    import rawpy
    mock_preview.format = rawpy.ThumbFormat.JPEG
    mock_raw.extract_thumb.return_value = mock_preview
    mock_imread.return_value.__enter__.return_value = mock_raw
    
    with patch("viewer.mixins.image_loading.io.BytesIO"):
        with patch("viewer.mixins.image_loading.ImageLoadingMixin._is_file_acceptable", return_value=True):
            with patch("viewer.mixins.image_loading.resize_image", return_value="resized"):
                with patch("builtins.open", MagicMock()):
                    with patch("viewer.mixins.image_loading.os.fstat") as mock_fstat:
                        mock_fstat.return_value.st_size = 1000
                        result = ImageLoadingMixin.load_image(
                            "test.raw", True, mock_exiftool, 1000, [".raw"], [".jpg"], True, True
                        )
                        assert result is not None
                        assert result.img == "resized"

@patch("viewer.mixins.image_loading.rawpy.imread")
@patch("viewer.mixins.image_loading.PIL.Image.open")
def test_load_image_read_raw_partially_exception_fallback(mock_pil_open, mock_imread):
    mock_exiftool = MagicMock()
    mock_exiftool.get_meta_data.return_value = {"test.raw": {}}
    mock_exiftool.get_jpegfromraw.side_effect = Exception("err")
    mock_exiftool.get_previewimage.side_effect = Exception("err")
    
    # partially read fails
    mock_raw1 = MagicMock()
    mock_raw1.extract_thumb.side_effect = Exception("err")
    
    # full read succeeds
    mock_raw2 = MagicMock()
    class DummyPreview(bytes):
        pass
    mock_preview = DummyPreview(b"mock_data")
    import rawpy
    mock_preview.format = rawpy.ThumbFormat.JPEG
    mock_raw2.extract_thumb.return_value = mock_preview
    
    # imread is called twice. 1st is in 'with', 2nd is direct
    mock_imread.side_effect = [MagicMock(__enter__=MagicMock(return_value=mock_raw1)), mock_raw2]
    
    mock_pil_open.return_value = "pil_image"
    
    with patch("viewer.mixins.image_loading.io.BytesIO"):
        with patch("viewer.mixins.image_loading.ImageLoadingMixin._is_file_acceptable", return_value=True):
            with patch("viewer.mixins.image_loading.resize_image", return_value="resized"):
                with patch("builtins.open", MagicMock()):
                    with patch("viewer.mixins.image_loading.os.fstat", MagicMock()):
                        result = ImageLoadingMixin.load_image(
                            "test.raw", True, mock_exiftool, 1000, [".raw"], [".jpg"], True, True
                        )
                        assert result is not None
                        assert mock_raw2.extract_thumb.called

@patch("viewer.mixins.image_loading.rawpy.imread")
@patch("viewer.mixins.image_loading.PIL.Image.fromarray")
def test_load_image_raw_postprocess(mock_fromarray, mock_imread):
    mock_exiftool = MagicMock()
    mock_exiftool.get_meta_data.return_value = {"test.raw": {}}
    mock_exiftool.get_jpegfromraw.side_effect = Exception("err")
    mock_exiftool.get_previewimage.side_effect = Exception("err")
    
    mock_raw_full = MagicMock()
    mock_raw_full.extract_thumb.side_effect = Exception("err")
    mock_raw_full.postprocess.return_value = "rgb_array"
    
    mock_imread.return_value = mock_raw_full
    mock_fromarray.return_value = "pil_image"
    
    with patch("viewer.mixins.image_loading.ImageLoadingMixin._is_file_acceptable", return_value=True):
        with patch("viewer.mixins.image_loading.resize_image", return_value="resized"):
            result = ImageLoadingMixin.load_image(
                "test.raw", True, mock_exiftool, 1000, [".raw"], [".jpg"], True, False
            )
            assert result is not None
            mock_raw_full.postprocess.assert_called_once()
            mock_fromarray.assert_called_once_with("rgb_array", "RGB")

def test_load_image_raw_unsupported_thumb_format():
    # test line 98 `raise ValueError("Unsupported format")`
    mock_exiftool = MagicMock()
    mock_exiftool.get_meta_data.return_value = {"test.raw": {}}
    
    import rawpy
    mock_raw_full = MagicMock()
    class DummyPreview(bytes): pass
    mock_preview = DummyPreview(b"mock_data")
    mock_preview.format = rawpy.ThumbFormat.BITMAP # something not JPEG
    mock_raw_full.extract_thumb.return_value = mock_preview
    mock_raw_full.postprocess.return_value = "rgb_array"
    
    with patch("viewer.mixins.image_loading.rawpy.imread", return_value=mock_raw_full):
        with patch("viewer.mixins.image_loading.PIL.Image.fromarray", return_value="pil_image"):
            with patch("viewer.mixins.image_loading.ImageLoadingMixin._is_file_acceptable", return_value=True):
                with patch("viewer.mixins.image_loading.resize_image", return_value="resized"):
                    result = ImageLoadingMixin.load_image(
                        "test.raw", True, mock_exiftool, 1000, [".raw"], [".jpg"], False, False
                    )
                    assert result is not None
                    # It should fail extract_thumb, log info, and then run postprocess
                    assert mock_raw_full.postprocess.called

def test_load_image_general_exception():
    mock_exiftool = MagicMock()
    mock_exiftool.get_meta_data.side_effect = Exception("meta_data fail")
    
    with patch("viewer.mixins.image_loading.ImageLoadingMixin._is_file_acceptable", return_value=True):
        result = ImageLoadingMixin.load_image("test.jpg", True, mock_exiftool, 1000, None, [".jpg"], True, True)
        assert result is None

def test_get_image():
    harness = _DummyHarness()
    harness.images["test.jpg"] = "image_data"
    
    with patch("viewer.mixins.image_loading.lock", _DummyLock()):
        assert harness.get_image("test.jpg") == "image_data"
        assert harness.get_image("unknown.jpg") is None

def test_put_image_in_cache():
    harness = _DummyHarness()
    harness.max_cache_size = 2
    
    harness.put_image_in_cache("1.jpg", "img1")
    harness.put_image_in_cache("2.jpg", "img2")
    assert list(harness.images.keys()) == ["1.jpg", "2.jpg"]
    
    harness.put_image_in_cache("3.jpg", "img3")
    assert list(harness.images.keys()) == ["2.jpg", "3.jpg"]

def test_load_images_background():
    harness = _DummyHarness()
    harness.image_load_queue = _DummyQueue(["test1.jpg", "test2.jpg"])
    harness.mp_pool.starmap.return_value = ["img1", "img2"]
    
    def stop_running(*args, **kwargs):
        harness.running = False
        return ["img1", "img2"]
        
    harness.mp_pool.starmap.side_effect = stop_running
    
    with patch("viewer.mixins.image_loading.lock", _DummyLock()):
        harness.load_images_background()
        
    assert harness.images["test1.jpg"] == "img1"
    assert harness.images["test2.jpg"] == "img2"

def test_load_images_background_sequential_fallback():
    harness = _DummyHarness()
    harness.image_load_queue = _DummyQueue(["test1.jpg"])
    harness.mp_pool.starmap.side_effect = Exception("starmap failed")
    
    def mock_load_image(fpath, *args, **kwargs):
        harness.running = False
        return "img1_seq"
        
    with patch("viewer.mixins.image_loading.lock", _DummyLock()):
        with patch("viewer.mixins.image_loading.ImageLoadingMixin.load_image", side_effect=mock_load_image):
            harness.load_images_background()
            
    assert harness.images["test1.jpg"] == "img1_seq"
    
def test_load_images_background_empty_queue():
    harness = _DummyHarness()
    harness.image_load_queue = _DummyQueue([])
    
    def stop_running():
        harness.running = False
        
    with patch("viewer.mixins.image_loading.time.sleep", side_effect=lambda x: stop_running()):
        harness.load_images_background()


@patch("viewer.mixins.image_loading.PIL.Image.open")
def test_load_image_for_zoom_uses_exif_thumbnail_and_no_resize(mock_pil_open):
    mock_exiftool = MagicMock()
    mock_exiftool.get_meta_data.return_value = {"test.raw": {}}
    mock_exiftool.get_jpegfromraw.return_value = b"jpegdata"
    mock_pil_open.return_value = "pil_image"

    with patch("viewer.mixins.image_loading.ImageLoadingMixin._is_file_acceptable", return_value=True):
        with patch("viewer.mixins.image_loading.resize_image") as mock_resize:
            with patch("viewer.mixins.image_loading.rawpy.imread") as mock_imread:
                result = ImageLoadingMixin.load_image(
                    "test.raw",
                    False,
                    mock_exiftool,
                    1000,
                    [".raw"],
                    [".jpg"],
                    True,
                    True,
                    resize_ratio=None,
                )

    assert result is not None
    mock_exiftool.get_jpegfromraw.assert_called_once_with("test.raw")
    mock_exiftool.get_previewimage.assert_not_called()
    mock_imread.assert_not_called()
    mock_resize.assert_not_called()


@patch("viewer.mixins.image_loading.rawpy.imread")
@patch("viewer.mixins.image_loading.PIL.Image.fromarray")
def test_load_image_for_zoom_repeats_fallback_chain_without_resize(mock_fromarray, mock_imread):
    mock_exiftool = MagicMock()
    mock_exiftool.get_meta_data.return_value = {"test.raw": {}}
    mock_exiftool.get_jpegfromraw.side_effect = Exception("no jpegfromraw")
    mock_exiftool.get_previewimage.side_effect = Exception("no preview")

    mock_raw_full = MagicMock()
    mock_raw_full.extract_thumb.side_effect = Exception("thumb fail")
    mock_raw_full.postprocess.return_value = "rgb_array"

    full_ctx = MagicMock()
    full_ctx.__enter__.return_value = mock_raw_full
    full_ctx.__exit__.return_value = None

    mock_imread.return_value = full_ctx
    mock_fromarray.return_value = "pil_image"

    with patch("viewer.mixins.image_loading.ImageLoadingMixin._is_file_acceptable", return_value=True):
        with patch("viewer.mixins.image_loading.resize_image") as mock_resize:
            result = ImageLoadingMixin.load_image(
                "test.raw",
                True,
                mock_exiftool,
                1000,
                [".raw"],
                [".jpg"],
                True,
                False,
                resize_ratio=None,
            )

    assert result is not None
    mock_exiftool.get_jpegfromraw.assert_called_once_with("test.raw")
    mock_exiftool.get_previewimage.assert_called_once_with("test.raw")
    mock_raw_full.postprocess.assert_called_once()
    assert mock_imread.call_count == 1
    mock_resize.assert_not_called()
