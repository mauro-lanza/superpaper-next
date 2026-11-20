import os
import stat
import sys

import pytest

from tests.desktop.conftest import assert_satisfies_desktop


def test_windows_keeps_the_wallpaper_and_takes_one_image(windows):
    assert windows.keeps_wallpaper() is True
    assert windows.takes_pieces("") is False
    assert windows.setter_problem("") is None


def test_the_config_folder_opens_through_the_shell(windows, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr("os.startfile", opened.append, raising=False)

    assert windows.open_folder(tmp_path).ok

    assert opened == [tmp_path]


def test_a_folder_that_will_not_open_is_reported_not_raised(windows, monkeypatch, tmp_path):
    def startfile(folder):
        message = "no handler"
        raise OSError(message)

    monkeypatch.setattr("os.startfile", startfile, raising=False)

    assert windows.open_folder(tmp_path).problem == f"Could not open {tmp_path}: no handler"


def test_windows_satisfies_the_desktop_interface(windows):
    assert_satisfies_desktop(windows)


def test_windows_defaults_are_jpeg_renders_hotkeys_and_strict_profile_names(windows):
    assert windows.render_extension() == "jpg"
    assert windows.hotkeys_by_default() is True
    assert windows.strict_profile_names() is True


def test_a_portable_install_keeps_files_beside_the_program(windows, tmp_path):
    (tmp_path / "app").mkdir()

    dirs = windows.default_dirs({"LOCALAPPDATA": str(tmp_path / "lad")}, tmp_path / "app")

    assert dirs == (tmp_path / "app", tmp_path / "app" / "temp")
    assert os.listdir(tmp_path / "app") == []  # the write probe cleans up


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs a directory this user can't write")
def test_an_installed_program_uses_local_appdata(windows, tmp_path):
    install = tmp_path / "app"
    install.mkdir()
    install.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        dirs = windows.default_dirs({"LOCALAPPDATA": str(tmp_path / "lad")}, install)
    finally:
        install.chmod(stat.S_IRWXU)

    assert dirs == (tmp_path / "lad" / "Superpaper", tmp_path / "lad" / "Superpaper" / "temp")
