"""Superpaper's logger.

Nothing is configured at import. The entry point that knows whether the user asked for
debugging or a log file calls ``configure_logging`` once, before any work starts.
"""

import logging
import sys
from pathlib import Path

# Modules that log through logging.getLogger(__name__) sit beneath G_LOGGER, so the
# handlers configure_logging gives it receive their records too.
G_LOGGER = logging.getLogger("superpaper")
# Whether to log detail that only helps when debugging. Set by configure_logging.
DEBUG = False


def configure_logging(*, debug: bool, log_file: Path | None = None) -> None:
    """Log to the console when debugging, and to ``log_file`` (which also means debugging).

    Without either, warnings and errors still reach stderr through Python's last-resort
    handler. Calling this again replaces the earlier configuration.
    """
    global DEBUG
    for handler in G_LOGGER.handlers[:]:
        G_LOGGER.removeHandler(handler)
        handler.close()
    DEBUG = debug or log_file is not None
    G_LOGGER.setLevel(logging.INFO if DEBUG else logging.NOTSET)
    if DEBUG:
        G_LOGGER.addHandler(logging.StreamHandler())
    if log_file is not None:
        G_LOGGER.addHandler(logging.FileHandler(log_file, mode="w", encoding="utf-8"))
    sys.excepthook = _log_uncaught_exception if log_file is not None else sys.__excepthook__


def _log_uncaught_exception(exception_type, exception, traceback) -> None:
    G_LOGGER.critical("Uncaught exception", exc_info=(exception_type, exception, traceback))
