"""Logging is configured once, by the entry point. Reading settings never touches it."""

import logging
import sys

import pytest

from superpaper import sp_logging
from superpaper.settings import read_settings

module_logger = logging.getLogger("superpaper.test_logging")


@pytest.fixture(autouse=True)
def unconfigured_logging():
    yield
    sp_logging.configure_logging(debug=False)


def test_without_debugging_nothing_is_configured():
    sp_logging.configure_logging(debug=False)

    assert not module_logger.isEnabledFor(logging.INFO)
    assert sys.excepthook is sys.__excepthook__


def test_debugging_logs_to_the_console(capsys):
    sp_logging.configure_logging(debug=True)

    module_logger.info("from a module")

    assert module_logger.isEnabledFor(logging.INFO)
    assert capsys.readouterr().err == "from a module\n"


def test_a_log_file_also_records_uncaught_exceptions(tmp_path):
    log_file = tmp_path / "log"
    sp_logging.configure_logging(debug=False, log_file=log_file)

    module_logger.info("started")
    message = "boom"
    try:
        raise ValueError(message)  # noqa: TRY301
    except ValueError:
        sys.excepthook(*sys.exc_info())

    log = log_file.read_text(encoding="utf-8")
    assert "started" in log
    assert "ValueError: boom" in log


def test_configuring_again_replaces_the_handlers(tmp_path, capsys):
    log_file = tmp_path / "log"
    for _ in range(3):
        sp_logging.configure_logging(debug=True, log_file=log_file)

    module_logger.info("once")

    assert capsys.readouterr().err == "once\n"
    assert log_file.read_text(encoding="utf-8") == "once\n"


def test_reading_settings_with_logging_on_adds_no_handlers(tmp_path, capsys):
    settings_file = tmp_path / "general_settings"
    settings_file.write_text("logging=true\n", encoding="utf-8")

    for _ in range(3):
        assert read_settings(settings_file, "linux").logging is True

    module_logger.info("not shown")
    assert not module_logger.isEnabledFor(logging.INFO)
    assert capsys.readouterr().err == ""
