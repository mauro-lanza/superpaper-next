"""Which OS module current() picks, and what is the same on every OS."""

import sys

import pytest

import superpaper.desktop as desktop
from superpaper.desktop import linux, process, unknown
from superpaper.desktop.wallpaper import Spanned
from tests.desktop.conftest import IMAGE, NO_ACTIVITIES, assert_satisfies_desktop
from tests.desktop.fake import FakeDesktop


def test_linux_is_chosen_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    assert desktop.current() is linux


def test_an_unknown_platform_gets_the_module_that_sets_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "plan9")

    assert desktop.current() is unknown


@pytest.mark.parametrize("module", [linux, unknown, FakeDesktop()])
def test_modules_satisfy_the_desktop_interface(module):
    assert_satisfies_desktop(module)


def test_an_unknown_platform_sets_nothing_and_says_so():
    result = unknown.set_wallpaper(Spanned(IMAGE), set_command="", activities=NO_ACTIVITIES)

    assert result.problem == f"Unknown platform: {sys.platform}"
    assert unknown.set_spanmode("").ok
    assert unknown.takes_pieces("") is False
    assert unknown.keeps_wallpaper() is False
    assert unknown.setter_problem("") is None


def test_an_unknown_platform_opens_folders_with_xdg_open(ran, tmp_path):
    assert unknown.open_folder(tmp_path).ok

    assert [command for command, _ in ran] == [["xdg-open", str(tmp_path)]]


@pytest.mark.parametrize("module", [linux, unknown])
def test_post_change_script_receives_each_source_as_an_argument(module, ran, tmp_path):
    script = tmp_path / "run-after-wp-change.py"

    assert module.run_hook(script, IMAGE, ["/a.png", "/b c.png"]).ok

    assert ran[-1][0] == ["python3", str(script), IMAGE, "/a.png", "/b c.png"]


def test_missing_python_for_the_post_change_script_is_reported_not_raised(monkeypatch, tmp_path):
    def run(command, **options):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(process.subprocess, "run", run)

    assert linux.run_hook(tmp_path / "script.py", IMAGE, ["/a.png"]).problem == "python3 is not installed."
