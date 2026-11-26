"""Rotating file logs for the sidecar.

A desktop app cannot rely on a terminal staying open, so the first thing a bug
report needs is on disk next to the database. Logging is intentionally boring:
one rotating file, one format, no network sinks.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def configure_logging(data_dir: Path, level: str | None = None) -> Path:
    """Install a rotating file handler under ``<data_dir>/logs``.

    Idempotent: repeated imports (tests, reload) keep the original handler.
    Returns the log file path whether or not this call configured it.
    """

    global _CONFIGURED
    directory = Path(data_dir) / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "clipfactory.log"
    if _CONFIGURED:
        return path

    resolved = (level or os.environ.get("CLIPPER_LOG_LEVEL") or "INFO").upper()
    numeric = getattr(logging, resolved, logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(numeric)

    file_handler = RotatingFileHandler(
        path,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(numeric)
    root.addHandler(file_handler)

    # Keep stderr for dev; the Electron shell forwards it to its own log.
    if not any(
        isinstance(handler, logging.StreamHandler) and handler.stream is sys.stderr
        for handler in root.handlers
    ):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.setLevel(numeric)
        root.addHandler(stream)

    # Windows' Proactor event loop logs a full traceback for every client
    # disconnect (WinError 10054). Those are normal browser/tab closes, not
    # application faults, and they drown the log during UI iteration.
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)

    _CONFIGURED = True
    logging.getLogger(__name__).info("logging to %s (level %s)", path, resolved)
    return path
