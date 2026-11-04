from __future__ import annotations

import faulthandler
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FAULT_LOG = None


def configure_logging(log_dir: Path, level: str = "INFO") -> None:
    global _FAULT_LOG
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    file_handler = RotatingFileHandler(
        log_dir / "lianiq.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    handlers: list[logging.Handler] = [file_handler]
    if sys.stderr is not None:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=handlers,
        force=True,
    )
    if _FAULT_LOG is not None:
        faulthandler.disable()
        _FAULT_LOG.close()
    _FAULT_LOG = (log_dir / "native-crash.log").open("a", encoding="utf-8")
    # On Windows faulthandler also reports exceptions that are handled afterwards, such as
    # the COM error 0x8001010d that UI Automation clients (Narrator) raise and handle. Dumping
    # *other* threads' frames while they run can then crash the process with an access
    # violation (lianiq#69), so on Windows only the reporting thread is dumped.
    faulthandler.enable(_FAULT_LOG, all_threads=sys.platform != "win32")
    sys.excepthook = _handle_unhandled_exception
    threading.excepthook = _handle_thread_exception


def _handle_unhandled_exception(exc_type, exc_value, traceback) -> None:
    logging.getLogger(__name__).critical(
        "Unhandled application exception",
        exc_info=(exc_type, exc_value, traceback),
    )


def _handle_thread_exception(args: threading.ExceptHookArgs) -> None:
    logging.getLogger(__name__).critical(
        "Unhandled exception in thread %s",
        args.thread.name if args.thread else "unknown",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
