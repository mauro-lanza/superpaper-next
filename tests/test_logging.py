"""Logging is configured once, by the entry point. Reading settings never touches it."""

import logging
import sys

import pytest

from superpaper import sp_logging
from superpaper.settings import read_settings


@pytest.fixture(autouse=True)
def unconfigured_logging():
    yield
    sp_logging.configure_logging(debug=False)


def test_without_debugging_nothing_is_configured():
    sp_logging.configure_logging(debug=False)

    assert sp_logging.G_LOGGER.handlers == []
    assert sp_logging.DEBUG is False
    assert sys.excepthook is sys.__excepthook__


def test_debugging_logs_to_the_console():
    sp_logging.configure_logging(debug=True)

    assert [type(handler) for handler in sp_logging.G_LOGGER.handlers] == [logging.StreamHandler]
    assert sp_logging.DEBUG is True


def test_a_log_file_also_records_uncaught_exceptions(tmp_path):
    log_file = tmp_path / "log"
    sp_logging.configure_logging(debug=False, log_file=log_file)

    sp_logging.G_LOGGER.info("started")
    message = "boom"
    try:
        raise ValueError(message)  # noqa: TRY301
    except ValueError:
        sys.excepthook(*sys.exc_info())
    for handler in sp_logging.G_LOGGER.handlers:
        handler.flush()

    assert sp_logging.DEBUG is True
    log = log_file.read_text(encoding="utf-8")
    assert "started" in log
    assert "ValueError: boom" in log


def test_configuring_again_replaces_the_handlers(tmp_path):
    for _ in range(3):
        sp_logging.configure_logging(debug=True, log_file=tmp_path / "log")

    assert len(sp_logging.G_LOGGER.handlers) == 2


def test_a_module_logger_writes_to_the_log_file(tmp_path):
    log_file = tmp_path / "log"
    sp_logging.configure_logging(debug=False, log_file=log_file)

    logging.getLogger("superpaper.desktop.kde").info("from a module")
    for handler in sp_logging.G_LOGGER.handlers:
        handler.flush()

    assert "from a module" in log_file.read_text(encoding="utf-8")


def test_reading_settings_with_logging_on_adds_no_handlers(tmp_path):
    settings_file = tmp_path / "general_settings"
    settings_file.write_text("logging=true\n", encoding="utf-8")

    for _ in range(3):
        assert read_settings(settings_file, "linux").logging is True

    assert sp_logging.G_LOGGER.handlers == []
