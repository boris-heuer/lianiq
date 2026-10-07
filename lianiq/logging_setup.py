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
    faulthandler.enable(_FAULT_LOG, all_threads=True)
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
