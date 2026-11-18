"""Where Superpaper's log goes.

Nothing is configured at import. The entry point that knows whether the user asked for
debugging or a log file calls ``configure_logging`` once, before any work starts. Every
module logs through ``logging.getLogger(__name__)``, beneath the "superpaper" logger.
"""

import logging
import sys
from pathlib import Path

_PACKAGE_LOGGER = logging.getLogger("superpaper")


def configure_logging(*, debug: bool, log_file: Path | None = None) -> None:
    """Log to the console when debugging, and to ``log_file`` (which also means debugging).

    Without either, warnings and errors still reach stderr through Python's last-resort
    handler. Calling this again replaces the earlier configuration.
    """
    for handler in _PACKAGE_LOGGER.handlers[:]:
        _PACKAGE_LOGGER.removeHandler(handler)
        handler.close()
    debugging = debug or log_file is not None
    _PACKAGE_LOGGER.setLevel(logging.INFO if debugging else logging.NOTSET)
    if debugging:
        _PACKAGE_LOGGER.addHandler(logging.StreamHandler())
    if log_file is not None:
        _PACKAGE_LOGGER.addHandler(logging.FileHandler(log_file, mode="w", encoding="utf-8"))
    sys.excepthook = _log_uncaught_exception if log_file is not None else sys.__excepthook__


def _log_uncaught_exception(exception_type, exception, traceback) -> None:
    _PACKAGE_LOGGER.critical("Uncaught exception", exc_info=(exception_type, exception, traceback))
