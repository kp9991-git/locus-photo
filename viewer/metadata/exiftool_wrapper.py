import os
import shutil
import sys
import tempfile
import threading
from viewer.core.utils import singleton
from viewer.core.enums import MetaTagName
from viewer.core.constants import EXIFTOOL_WINDOWS_PATH, EXIFTOOL_UNIX_PATH
from typing import List, Dict
from exiftool import ExifToolHelper


lock = threading.Lock()


@singleton
class ExifToolWrapperRegistry:
    
    def __init__(self, logger=None):
        self.logger = logger
        self.wrappers = []
        
    def add_wrapper(self, wrapper):
        with lock:
            self.wrappers.append(wrapper)
        
    def terminate(self):
        for wrapper in self.wrappers:
            wrapper.terminate()
        self.wrappers = []


class ExifToolWrapper:

    GPS_LOG_REDACT_ENV_KEY = "LOCUS_PHOTO_LOG_REDACT_GPS"
    GPS_VALUE_KEYS_FOR_REDACTION = {"GPSLATITUDE", "GPSLONGITUDE", "GPSALTITUDE"}

    @staticmethod
    def _get_exiftool_relative_path() -> str:
        if os.name == "nt":
            return EXIFTOOL_WINDOWS_PATH
        return EXIFTOOL_UNIX_PATH

    @staticmethod
    def _resolve_exiftool_executable(base_dir: str) -> str:
        relative_path = ExifToolWrapper._get_exiftool_relative_path()
        normalized_relative = relative_path.replace("\\", os.sep).replace("/", os.sep)
        return os.path.normpath(os.path.join(base_dir, normalized_relative))

    @staticmethod
    def _prepare_isolated_exiftool_runtime(executable_path: str, logger=None) -> str:
        """Copy ExifTool assets to an isolated temp dir for this process.

        In one-file PyInstaller builds, running exiftool directly from the
        `_MEI...` extraction folder can pick up unrelated bundled DLLs and
        block on startup. Using a clean per-process directory keeps ExifTool's
        expected runtime layout intact.
        """
        runtime_dir = os.path.join(tempfile.gettempdir(), "locus-photo-exiftool-{}".format(os.getpid()))
        source_dir = os.path.dirname(executable_path)
        source_dir_name = os.path.basename(source_dir)
        source_executable_name = os.path.basename(executable_path)
        runtime_source_dir = os.path.join(runtime_dir, source_dir_name)
        runtime_executable = os.path.join(runtime_source_dir, source_executable_name)

        if os.path.exists(runtime_executable):
            return runtime_dir

        if os.path.isdir(runtime_dir):
            shutil.rmtree(runtime_dir, ignore_errors=True)
        os.makedirs(runtime_dir, exist_ok=True)

        shutil.copytree(source_dir, runtime_source_dir)

        if logger:
            logger.info("Prepared isolated ExifTool runtime at {}".format(runtime_dir))
        return runtime_dir

    def __init__(self, logger=None, redact_gps_logs=None):
        self.logger = logger
        self.redact_gps_logs = ExifToolWrapper._resolve_redact_gps_logs(redact_gps_logs)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        exiftool_executable = ExifToolWrapper._resolve_exiftool_executable(base_dir)
        if getattr(sys, 'frozen', False) and os.name == "nt":
            isolated_dir = ExifToolWrapper._prepare_isolated_exiftool_runtime(exiftool_executable, logger=logger)
            exiftool_executable = os.path.join(
                isolated_dir,
                os.path.basename(os.path.dirname(exiftool_executable)),
                os.path.basename(exiftool_executable),
            )
        self._exiftool_executable = exiftool_executable
        self.exiftool = ExifToolHelper(executable=exiftool_executable, common_args=["-G"], check_execute=False)

    @staticmethod
    def _resolve_redact_gps_logs(value):
        if isinstance(value, bool):
            return value

        env_value = os.environ.get(ExifToolWrapper.GPS_LOG_REDACT_ENV_KEY, "1")
        normalized = str(env_value).strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return False
        return True

    def _sanitize_args_for_log(self, args):
        if not self.redact_gps_logs:
            return list(args)

        sanitized_args = []
        for arg in args:
            if isinstance(arg, str) and arg.startswith("-") and "=" in arg:
                key, value = arg[1:].split("=", 1)
                if key.upper() in ExifToolWrapper.GPS_VALUE_KEYS_FOR_REDACTION:
                    sanitized_args.append("-{}=<redacted>".format(key))
                    continue
            sanitized_args.append(arg)
        return sanitized_args

    def _execute_with_timeout(self, args, raw_bytes=False, timeout_seconds=8):
        result_container = {}
        error_container = {}

        def _invoke():
            try:
                result_container["value"] = self.exiftool.execute(*args, raw_bytes=raw_bytes)
            except Exception as exc:
                error_container["error"] = exc

        worker = threading.Thread(target=_invoke, daemon=True)
        worker.start()
        worker.join(timeout_seconds)

        if worker.is_alive():
            if self.logger:
                self.logger.error(
                    "ExifTool call timed out after %ss. args=%r",
                    timeout_seconds,
                    self._sanitize_args_for_log(args),
                )
            try:
                self.exiftool.terminate()
            except Exception:
                pass
            try:
                self.exiftool = ExifToolHelper(
                    executable=self._exiftool_executable,
                    common_args=["-G"],
                    check_execute=False,
                )
            except Exception as exc:
                if self.logger:
                    self.logger.error("Failed to restart ExifTool helper after timeout: {}".format(exc))
            return None

        if "error" in error_container:
            raise error_container["error"]
        return result_container.get("value")
        
    def terminate(self):
        self.exiftool.terminate()

    def get_version(self):
        try:
            output = self._execute_with_timeout(["-ver"], timeout_seconds=5)
            return output.strip() if output is not None else None
        except Exception:
            if self.logger:
                self.logger.exception("Failed to query ExifTool version")
            return None

    def get_jpegfromraw(self, fpath: str):
        args = ["-b", "-jpgfromraw", fpath]
        output = self._execute_with_timeout(args, raw_bytes=True, timeout_seconds=12)
        return output if output is not None else b""

    def get_previewimage(self, fpath: str):
        args = ["-b", "-previewimage", fpath]
        output = self._execute_with_timeout(args, raw_bytes=True, timeout_seconds=12)
        return output if output is not None else b""

    def get_meta_data(self, fpath: str, numerical=True, tags=None, recursive=False) -> Dict[str, Dict[MetaTagName, object]]:
        if self.logger: self.logger.debug("Exif: Processing file {}".format(fpath))

        if tags is None:
            tags = list(MetaTagName)
        
        args = ['-' + t.name for t in tags]
        
        if numerical:
            args += ['-n']
            
        if recursive:
            args += ['-r']

        args += [fpath]

        output = self._execute_with_timeout(args, timeout_seconds=20)
        if output is None:
            if self.logger:
                self.logger.warning("ExifTool metadata query timed out for %s", fpath)
            return {fpath: {}}

        lines = output.split('\n')
        res = {}
        cur_key = fpath
        for line in lines:
            if line.startswith("======== "):
                fname_key = line.split("======== ")[1].replace('\r', '')
                cur_key = os.path.join(fpath, fname_key)
                res[cur_key] = {}
            else:
                tag, content = ExifToolWrapper.extract_meta_data_item(line)
                if tag is not None:
                    if cur_key not in res:
                        res[cur_key] = {}
                    res[cur_key][tag] = content
        if len(res) == 0:
            res[fpath] = {}
        if self.logger: self.logger.debug("   Parsed file {} : {} {} {} positions, {} orient".format(fpath, res.get(MetaTagName.GPSAltitude), res.get(MetaTagName.GPSLatitude), res.get(MetaTagName.GPSLongitude), res.get(MetaTagName.Orientation)))
        return res
    
    def get_list_of_supported_extensions(self):
        args = ["-listf"]
        try:
            output = self._execute_with_timeout(args, timeout_seconds=8)
            if output is None:
                return None
            exts = output.split('\n')[1:]
            res = []
            for e in exts:
                res += ['.' + x for x in e.lower().strip().split(' ')]
            return res
        except Exception:
            if self.logger:
                self.logger.exception("Failed to query supported extensions from ExifTool")
            return None
            
    @staticmethod
    def extract_meta_data_item(line):
        exif_arr = line.split(":")
        if len(exif_arr) > 1:
            tag_with_group = exif_arr[0].strip().split("]")
            tag = MetaTagName(tag_with_group[1].strip())
            content = exif_arr[1].strip()
            return tag, float(content)
        else:
            return None, None       

    def set_meta_data(self, fpath: str, tags: Dict[MetaTagName, object]) -> None:
        args = ["-overwrite_original", "-n"]
        for t in tags:
            value = tags[t]
            args.append('-' + t.name + '=' + str(value))
            if t == MetaTagName.GPSLatitude:
                args.append('-GPSLatitudeRef=' + ('S' if float(value) < 0 else 'N'))
            elif t == MetaTagName.GPSLongitude:
                args.append('-GPSLongitudeRef=' + ('W' if float(value) < 0 else 'E'))
        args.append(fpath)

        if self.logger:
            self.logger.info("Updating meta tags. Arguments: %s", self._sanitize_args_for_log(args))

        result = self._execute_with_timeout(args, timeout_seconds=20)
        if result is None:
            raise TimeoutError("Timed out while setting ExifTool metadata for {}".format(fpath))
        if self.logger: self.logger.info("Updating meta tags. Result: {!r}".format(result))
        return result

    def clear_meta_data(self, fpath: str, tags: List[MetaTagName]) -> None:
        args = ["-overwrite_original"] + ['-' + t.name + '=' for t in tags] + [fpath]

        if self.logger:
            self.logger.info("Clearing meta tags. Arguments: %s", self._sanitize_args_for_log(args))

        result = self._execute_with_timeout(args, timeout_seconds=20)
        if result is None:
            raise TimeoutError("Timed out while clearing ExifTool metadata for {}".format(fpath))
        if self.logger: self.logger.info("Clearing meta tags. Result: {!r}".format(result))
        return result

    def apply_meta_data(self, fpath: str, tags: Dict[MetaTagName, object], clear_tags: List[MetaTagName] | None = None) -> None:
        args = ["-overwrite_original", "-n"]

        clear_tags = clear_tags or []
        for tag in clear_tags:
            args.append('-' + tag.name + '=')
            if tag == MetaTagName.GPSLatitude:
                args.append('-GPSLatitudeRef=')
            elif tag == MetaTagName.GPSLongitude:
                args.append('-GPSLongitudeRef=')

        for tag, value in tags.items():
            args.append('-' + tag.name + '=' + str(value))
            if tag == MetaTagName.GPSLatitude:
                args.append('-GPSLatitudeRef=' + ('S' if float(value) < 0 else 'N'))
            elif tag == MetaTagName.GPSLongitude:
                args.append('-GPSLongitudeRef=' + ('W' if float(value) < 0 else 'E'))

        args.append(fpath)

        if self.logger:
            self.logger.info("Applying meta tags transactionally. Arguments: %s", self._sanitize_args_for_log(args))

        result = self._execute_with_timeout(args, timeout_seconds=20)
        if result is None:
            raise TimeoutError("Timed out while applying ExifTool metadata for {}".format(fpath))
        if self.logger:
            self.logger.info("Applying meta tags transactionally. Result: {!r}".format(result))
        return result
