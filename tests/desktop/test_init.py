"""Which OS module current() picks, and what is the same on every OS."""

import sys

import pytest

import superpaper.desktop as desktop
from superpaper.desktop import linux, unknown
from superpaper.desktop.wallpaper import Spanned
from tests.desktop.conftest import IMAGE, NO_PROFILES, assert_satisfies_desktop
from tests.desktop.fake import FakeDesktop


def test_linux_is_chosen_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    assert desktop.current() is linux


def test_macos_is_chosen_on_darwin(monkeypatch, appkit):
    macos = appkit(screens=[(0, 0, 1920, 1080)])
    monkeypatch.setattr(sys, "platform", "darwin")

    assert desktop.current() is macos


def test_windows_is_chosen_on_win32(monkeypatch, windows):
    monkeypatch.setattr(sys, "platform", "win32")

    assert desktop.current() is windows


def test_an_unknown_platform_gets_the_module_that_sets_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "plan9")

    assert desktop.current() is unknown


@pytest.mark.parametrize("module", [linux, unknown, FakeDesktop()])
def test_modules_satisfy_the_desktop_interface(module):
    assert_satisfies_desktop(module)


def test_an_unknown_platform_sets_nothing_and_says_so():
    result = unknown.set_wallpaper(Spanned(IMAGE), set_command="", profiles=NO_PROFILES)

    assert result.problem == f"Unknown platform: {sys.platform}"
    assert unknown.setter_problem("") == f"Unknown platform: {sys.platform}"


def test_an_unknown_platform_cannot_watch_the_displays():
    assert unknown.watch_displays(lambda: None) is False


def test_windows_reports_display_changes_through_wx_so_it_registers_nothing(windows):
    assert windows.watch_displays(lambda: None) is True


def test_an_unknown_platform_keeps_its_files_beside_the_program(tmp_path):
    assert unknown.default_dirs({"HOME": str(tmp_path)}, tmp_path / "app") == (
        tmp_path / "app",
        tmp_path / "app" / "temp",
    )


def test_an_unknown_platform_opens_folders_with_xdg_open(ran, tmp_path):
    assert unknown.open_folder(tmp_path).ok

    assert [command for command, _ in ran] == [["xdg-open", str(tmp_path)]]
