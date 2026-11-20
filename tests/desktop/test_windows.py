import sys
from types import ModuleType, SimpleNamespace

import pytest

import superpaper.desktop as desktop
from tests.desktop.conftest import assert_satisfies_desktop


@pytest.fixture
def windows(monkeypatch):
    """The superpaper.desktop.windows module, importable here with the win32 modules faked."""
    shell_package = ModuleType("win32com")
    shell_module = ModuleType("win32com.shell")
    shell_module.shell = SimpleNamespace()
    shell_module.shellcon = SimpleNamespace()
    shell_package.shell = shell_module
    for name, module in {
        "winreg": ModuleType("winreg"),
        "pythoncom": ModuleType("pythoncom"),
        "win32gui": ModuleType("win32gui"),
        "win32com": shell_package,
        "win32com.shell": shell_module,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr("ctypes.windll", SimpleNamespace(user32=SimpleNamespace()), raising=False)
    from superpaper.desktop import windows

    yield windows
    sys.modules.pop("superpaper.desktop.windows", None)
    if hasattr(desktop, "windows"):
        del desktop.windows


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
