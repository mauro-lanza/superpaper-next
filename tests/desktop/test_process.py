"""How host programs are run."""

import subprocess

import pytest

from superpaper.desktop import process
from tests.desktop.conftest import IMAGE


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (FileNotFoundError("setter"), "setter is not installed."),
        (PermissionError(13, "Permission denied"), "setter could not be run: [Errno 13] Permission denied"),
        (subprocess.TimeoutExpired("setter", 30), "setter did not finish within 30 seconds."),
        (
            subprocess.CompletedProcess(["setter"], 2, stdout="", stderr="no such display\n"),
            "setter failed with exit status 2: no such display",
        ),
    ],
)
def test_a_failed_program_is_reported_not_raised(monkeypatch, failure, message):
    def run(command, **options):
        if isinstance(failure, BaseException):
            raise failure
        return failure

    monkeypatch.setattr(process.subprocess, "run", run)

    assert process.run(["/usr/bin/setter", IMAGE], timeout=30).problem == message
