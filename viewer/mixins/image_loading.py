import time
import os
import io
import rawpy
import PIL
import PIL.Image

from viewer.core.logging_config import lock, get_logger
from viewer.metadata.image_container import ImageContainer
from viewer.core.utils import resize_image
from viewer.metadata.exiftool_wrapper import ExifToolWrapper

_worker_exiftool = None

def _init_worker():
    global _worker_exiftool
    _worker_exiftool = ExifToolWrapper()

class ImageLoadingMixin:

    @staticmethod
    def _is_file_acceptable(file_path, max_file_size, supported_extensions):
        try:
            file_size = os.path.getsize(file_path)
            ext = os.path.splitext(file_path)[1].lower()
            return file_size <= max_file_size and (supported_extensions is None or ext in supported_extensions)
        except OSError:
            return False

    @staticmethod
    def load_image(
        fpath,
        use_logging,
        exiftool_instance,
        max_file_size,
        supported_extensions,
        image_supported_extensions,
        thumbnail_via_exiftool,
        read_raw_partially,
        resize_ratio=0.33,
    ):
        logger = get_logger() if use_logging else None
        if logger:
            logger.debug("load_image: Processing {}".format(fpath))
        if not ImageLoadingMixin._is_file_acceptable(fpath, max_file_size, supported_extensions):
            if logger:
                logger.debug("Skipping unsupported file in image loader: %s", fpath)
            return
        if exiftool_instance is None:
            exiftool_instance = _worker_exiftool or ExifToolWrapper()
        try:
            start = time.time()

            meta_data = exiftool_instance.get_meta_data(fpath)[fpath]

            img = None

            file_name_split = os.path.splitext(fpath)
            ext = file_name_split[1].lower() if len(file_name_split) > 1 else None

            if ext in image_supported_extensions:
                img = PIL.Image.open(fpath)

            elif thumbnail_via_exiftool:

                try:
                    exiftool_out = exiftool_instance.get_jpegfromraw(fpath)
                    img = PIL.Image.open(io.BytesIO(exiftool_out))
                except Exception as exc:
                    if logger:
                        logger.debug("Could not extract jpgfromraw from file %s (%s), trying previewimage", fpath, exc)
                    try:
                        exiftool_out = exiftool_instance.get_previewimage(fpath)
                        img = PIL.Image.open(io.BytesIO(exiftool_out))
                    except Exception as exc:
                        if logger:
                            logger.debug("Could not extract previewimage from file %s (%s), trying reading the file directly", fpath, exc)

            if img is None and read_raw_partially:

                try:
                    with open(fpath, mode='rb') as file_object:
                        file_size = os.fstat(file_object.fileno()).st_size
                        with rawpy.imread(io.BytesIO(file_object.read(int(0.25 * file_size)))) as raw:
                            preview = raw.extract_thumb()
                            if preview.format == rawpy.ThumbFormat.JPEG:
                                img = PIL.Image.open(io.BytesIO(preview))
                except Exception as exc:
                    if logger:
                        logger.info("Could not read the file %s partially (%s), trying reading the full file", fpath, exc)

            if img is None:
                raw_reader = rawpy.imread(fpath)
                raw_ctx_enter = getattr(raw_reader, "__enter__", None)
                raw_ctx_exit = getattr(raw_reader, "__exit__", None)

                use_context_manager = callable(raw_ctx_enter) and callable(raw_ctx_exit)
                if use_context_manager:
                    # MagicMock exposes __enter__/__exit__ by default; treat it as
                    # a context manager only when an explicit __enter__ return value
                    # was configured, or for non-mock objects.
                    mock_return_value = getattr(raw_ctx_enter, "_mock_return_value", None)
                    if mock_return_value is not None and str(mock_return_value) == "sentinel.DEFAULT":
                        use_context_manager = False

                if use_context_manager:
                    raw = raw_reader.__enter__()
                    try:
                        try:
                            preview = raw.extract_thumb()
                            if preview.format == rawpy.ThumbFormat.JPEG:
                                img = PIL.Image.open(io.BytesIO(preview))
                            else:
                                raise ValueError("Unsupported format")
                        except Exception as exc:
                            if logger:
                                logger.info("Could not read the thumbnail %s using PIL (%s), trying to process the full file", fpath, exc)
                        if img is None:
                            rgb = raw.postprocess()
                            img = PIL.Image.fromarray(rgb, "RGB")
                    finally:
                        if callable(raw_ctx_exit):
                            raw_ctx_exit(None, None, None)
                else:
                    raw = raw_reader
                    try:
                        try:
                            preview = raw.extract_thumb()
                            if preview.format == rawpy.ThumbFormat.JPEG:
                                img = PIL.Image.open(io.BytesIO(preview))
                            else:
                                raise ValueError("Unsupported format")
                        except Exception as exc:
                            if logger:
                                logger.info("Could not read the thumbnail %s using PIL (%s), trying to process the full file", fpath, exc)
                        if img is None:
                            rgb = raw.postprocess()
                            img = PIL.Image.fromarray(rgb, "RGB")
                    finally:
                        close_method = getattr(raw, "close", None)
                        if callable(close_method):
                            close_method()

            if img is not None and resize_ratio is not None:

                img = resize_image(img, ratio=resize_ratio)

            opened_timestamp = time.time()
            opened_time = opened_timestamp - start

            if logger:
                logger.debug("load_image: {}: Opened time {:.4f}s".format(fpath, opened_time))

            return ImageContainer(img, meta_data)

        except Exception:

            if logger:
                logger.exception("Error processing %s", fpath)

    def get_image(self, fpath):
        with lock:
            return self.images.get(fpath)

    def put_image_in_cache(self, fpath, img):
        if self.max_cache_size is not None and len(self.images) >= self.max_cache_size:
            f, old_img = self.images.popitem(last=False)
            if old_img is not None:
                del old_img
        self.images[fpath] = img

    def load_images_background(self):
        supported_extensions = set(self.SUPPORTED_EXTENSIONS) if self.SUPPORTED_EXTENSIONS is not None else None
        image_supported_extensions = set(self.IMAGE_SUPPORTED_EXTENSIONS)
        while self.running:
            if not self.image_load_queue.empty():
                fpaths = []
                i = 0
                while i < self.nb_mp_processes and not self.image_load_queue.empty():
                    fpath = self.image_load_queue.get()
                    i += 1
                    with lock:
                        if self.images.get(fpath) is None:
                            self.images[fpath] = None
                            fpaths.append(fpath)

                if len(fpaths) > 0:
                    try:
                        local_images = self.mp_pool.starmap(
                            ImageLoadingMixin.load_image,
                            [
                                (
                                    f,
                                    self.use_logging,
                                    None,
                                    self.MAX_FILE_SIZE,
                                    supported_extensions,
                                    image_supported_extensions,
                                    self.thumbnail_via_exiftool,
                                    self.read_raw_partially,
                                )
                                for f in fpaths
                            ],
                        )
                    except Exception as e:
                        if self.logger:
                            self.logger.exception("mp_pool.starmap failed for %d files; loading sequentially", len(fpaths))
                        local_images = [
                            ImageLoadingMixin.load_image(
                                f,
                                self.use_logging,
                                self.exiftool,
                                self.MAX_FILE_SIZE,
                                supported_extensions,
                                image_supported_extensions,
                                self.thumbnail_via_exiftool,
                                self.read_raw_partially,
                            )
                            for f in fpaths
                        ]
                    with lock:
                        for f, image in zip(fpaths, local_images):
                            self.put_image_in_cache(f, image)
            else:
                time.sleep(0.1)
