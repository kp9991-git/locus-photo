import threading
import logging
import logging.handlers
import sys
import os
import tempfile
import multiprocessing as mp

from viewer.core.constants import APP_NAME

lock = threading.Lock()

loggers = {}
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
LOG_LEVEL_ENV_KEY = "LOCUS_PHOTO_LOG_LEVEL"
LOG_DIAGNOSTICS_ENV_KEY = "LOCUS_PHOTO_LOG_DIAGNOSTICS"
LOG_REDACT_GPS_ENV_KEY = "LOCUS_PHOTO_LOG_REDACT_GPS"
LOG_RUN_ID_ENV_KEY = "LOCUS_PHOTO_LOG_RUN_ID"


class _RunIdFilter(logging.Filter):
    def __init__(self, run_id):
        super().__init__()
        self.run_id = run_id

    def filter(self, record):
        record.run_id = self.run_id
        return True


def _resolve_log_level(level=None):
    if level is None:
        level = os.environ.get(LOG_LEVEL_ENV_KEY, "INFO")

    if isinstance(level, str):
        normalized = level.strip().upper()
        if normalized in VALID_LOG_LEVELS:
            return getattr(logging, normalized)
        return logging.INFO

    if isinstance(level, int):
        return level

    return logging.INFO


def _iter_log_dir_candidates():
    app_slug = APP_NAME.lower().replace(" ", "-")
    return [
        os.path.join(os.getcwd(), "log"),
        os.path.join(os.path.expanduser("~"), ".{}".format(app_slug), "log"),
        os.path.join(tempfile.gettempdir(), app_slug, "log"),
    ]


def get_logger(level=None):
    resolved_level = _resolve_log_level(level)
    process_name = mp.current_process().name
    run_id = os.environ.get(LOG_RUN_ID_ENV_KEY, "-")
    with lock:
        if process_name in loggers:
            logger = loggers[process_name]
            logger.setLevel(resolved_level)
            return logger
    root = logging.getLogger(process_name)
    root.setLevel(resolved_level)
    root.propagate = False

    for existing_filter in list(root.filters):
        root.removeFilter(existing_filter)
    root.addFilter(_RunIdFilter(run_id))

    for existing_handler in list(root.handlers):
        root.removeHandler(existing_handler)
        try:
            existing_handler.close()
        except Exception:
            pass

    std_handler = logging.StreamHandler(sys.stdout)
    file_handler = None
    file_handler_errors = []
    for log_dir in _iter_log_dir_candidates():
        try:
            os.makedirs(log_dir, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                os.path.join(log_dir, '{}-{}.log'.format(APP_NAME, process_name)), 'a', 1024 * 1024, 10
            )
            break
        except Exception as exc:
            file_handler_errors.append((log_dir, exc))

    f = logging.Formatter('%(asctime)s run=%(run_id)s pid=%(process)d thread=%(threadName)s %(name)s %(levelname)-8s %(message)s')
    std_handler.setFormatter(f)
    root.addHandler(std_handler)
    if file_handler is not None:
        file_handler.setFormatter(f)
        root.addHandler(file_handler)
    else:
        for log_dir, exc in file_handler_errors:
            root.warning("Could not initialize file logging at %s: %s", log_dir, exc)

    with lock:
        loggers[process_name] = root
    return root
