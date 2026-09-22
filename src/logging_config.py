"""
Central logging configuration for the assistant (Phase 0.5, Task A).

Replaces ad-hoc ``print("[DEBUG] ...")`` calls with the stdlib ``logging``
framework. Two sinks are wired:

* a rotating file handler — durable, timestamped record on disk that survives
  the window being minimised to the tray or closed; rotation caps total disk
  use instead of letting one file grow forever;
* a console handler — so live runs still show output when the window is open.

The file is UTF-8 encoded so RU/UK (Cyrillic) transcripts and content are
written without a codec crash on a legacy console code page — mirroring the
UTF-8 stream reconfiguration done at the top of ``main.py``.

Usage::

    from src.logging_config import setup_logging
    logger = setup_logging()
    logger.info("started")
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# logs/ lives at the project root (sibling of src/), so it is found regardless
# of the current working directory the app is launched from (tray/powershell).
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "assistant.log"

LOGGER_NAME = "assistant"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# RotatingFileHandler settings: 1 MB per file, 5 backups
# (assistant.log, assistant.log.1 ... assistant.log.5) => ~6 MB ceiling.
MAX_BYTES = 1_000_000
BACKUP_COUNT = 5

# Guard so repeated imports / calls don't attach duplicate handlers, which
# would multiply every log line once per extra handler.
_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Configure and return the application logger. Idempotent: safe to call more
    than once; handlers are attached only on the first call.

    Parameters
    ----------
    level:
        Root level for the app logger and both handlers. INFO by default;
        pass ``logging.DEBUG`` for verbose diagnostics.
    """
    global _configured

    logger = logging.getLogger(LOGGER_NAME)

    if _configured:
        return logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.setLevel(level)
    # Don't hand records up to the root logger — avoids double emission if the
    # root ever gets its own handlers (e.g. a library calling basicConfig).
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _configured = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Return the app logger, or a named child of it (e.g. ``get_logger("voice")``
    -> logger ``assistant.voice``). Children inherit the handlers configured by
    :func:`setup_logging`, so call that once at startup first.
    """
    base = logging.getLogger(LOGGER_NAME)
    return base.getChild(name) if name else base
