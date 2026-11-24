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


def test_post_change_script_receives_each_source_as_an_argument(ran, tmp_path):
    script = tmp_path / "run-after-wp-change.py"

    assert process.run_hook(script, IMAGE, ["/a.png", "/b c.png"]).ok

    assert ran[-1][0] == ["python3", str(script), IMAGE, "/a.png", "/b c.png"]


def test_host_programs_run_in_the_host_environment(monkeypatch, ran):
    monkeypatch.setenv("SUPERPAPER_HOSTENV_XDG_DATA_DIRS", "/host/data")

    process.run(["setter", IMAGE])

    env = ran[0][1]["env"]
    assert env["XDG_DATA_DIRS"] == "/host/data"
    assert not any(key.startswith("SUPERPAPER_HOSTENV_") for key in env)


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"LD_LIBRARY_PATH": "/bundle/lib", "LD_LIBRARY_PATH_ORIG": "/host/lib"}, {"LD_LIBRARY_PATH": "/host/lib"}),
        ({"LD_LIBRARY_PATH": "/bundle/lib", "LD_LIBRARY_PATH_ORIG": ""}, {}),
        (
            {"APPDIR": "/mnt/app", "LD_LIBRARY_PATH": "/mnt/app/lib:/mnt/app:/mnt/appy/lib:/host/lib"},
            {"APPDIR": "/mnt/app", "LD_LIBRARY_PATH": "/mnt/appy/lib:/host/lib"},
        ),
        ({"APPDIR": "/mnt/app", "LD_LIBRARY_PATH": "/mnt/app/lib"}, {"APPDIR": "/mnt/app"}),
        ({"DYLD_LIBRARY_PATH": "/frozen:/host/lib"}, {"DYLD_LIBRARY_PATH": "/host/lib"}),
        (
            {"XDG_DATA_DIRS": "/bundle/share", "SUPERPAPER_HOSTENV_XDG_DATA_DIRS": "/host/share"},
            {"XDG_DATA_DIRS": "/host/share"},
        ),
        ({"PYTHONHOME": "/bundle", "SUPERPAPER_HOSTENV_PYTHONHOME": "__SUPERPAPER_UNSET__"}, {}),
        ({"HOME": "/home/me"}, {"HOME": "/home/me"}),
    ],
)
def test_host_spawn_env_undoes_the_bundle_overrides(monkeypatch, environ, expected):
    monkeypatch.setattr(process.os, "environ", environ)
    monkeypatch.setattr(process.sys, "_MEIPASS", "/frozen", raising=False)

    assert process.host_spawn_env() == expected
