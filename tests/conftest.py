import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from superpaper.paths import AppPaths


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path_factory):
    """Keep every test away from the real home directory and the desktop session."""
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
    for name in (
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "SNAP_USER_DATA",
        "SNAP_USER_COMMON",
        "SUPERPAPER_CONFIG_HOME",
        "SUPERPAPER_CACHE_HOME",
        "DESKTOP_SESSION",
        "KDE_FULL_SESSION",
        "XDG_SESSION_DESKTOP",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def app_paths(tmp_path):
    """Superpaper's directories for one test: created, and without example profiles."""
    config = tmp_path / "config"
    paths = AppPaths(config=config, profiles=config / "profiles", cache=tmp_path / "cache")
    paths.profiles.mkdir(parents=True)
    paths.cache.mkdir()
    return paths


@pytest.fixture
def profile_modules(monkeypatch):
    from superpaper import data
    from superpaper import wallpaper_processing as wpproc

    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: None)
    return data, wpproc


def monitor(x, y, width, height, width_mm=500, height_mm=300, name="display"):
    """A monitor as screeninfo reports it."""
    return SimpleNamespace(x=x, y=y, width=width, height=height, width_mm=width_mm, height_mm=height_mm, name=name)


# Two displays side by side: 1920x1080 and 1280x1024.
TWO_DISPLAYS = [monitor(0, 0, 1920, 1080, 531, 299), monitor(1920, 0, 1280, 1024, 376, 301)]


@pytest.fixture
def display_layout(monkeypatch, tmp_path):
    """Build the display layout Superpaper detects for the given monitors.

    The layouts are loaded from ``config_dir``, by default a directory with none saved.
    """
    from superpaper import wallpaper_processing as wpproc

    def build(monitors=TWO_DISPLAYS, config_dir=None):
        monkeypatch.setattr(wpproc, "get_monitors", lambda: monitors)
        return wpproc.DisplaySystem(config_dir or tmp_path / "no-saved-layouts")

    return build


def write_profile(path: Path, *, spanmode="single", sources=(), selected=()):
    lines = ["name=test", f"spanmode={spanmode}", "slideshow=false", "sortmode=alphabetical"]
    lines.extend(f"display{i}paths={source}" for i, source in enumerate(sources))
    if selected:
        lines.append("selected=" + ";".join(map(str, selected)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class ManualTimer:
    def __init__(self, clock, interval, callback):
        self.clock = clock
        self.interval = interval
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self, *, even_if_cancelled=False):
        if not self.cancelled or even_if_cancelled:
            self.callback()


class ManualClock:
    def __init__(self):
        self.timers = []

    def timer(self, interval, callback):
        timer = ManualTimer(self, interval, callback)
        self.timers.append(timer)
        return timer


@pytest.fixture
def manual_clock(monkeypatch):
    from superpaper import wallpaper_processing as wpproc

    clock = ManualClock()
    monkeypatch.setattr(wpproc, "Timer", clock.timer)
    return clock


@pytest.fixture
def slideshow_profile():
    return SimpleNamespace(name="slides", slideshow=True, delay_list=[12.5])


@pytest.fixture
def headless_tray_module(monkeypatch):
    """Import tray orchestration against minimal wx/view stubs."""

    class FakeTaskBarIcon:
        pass

    class FakeApp:
        pass

    wx = ModuleType("wx")
    wx_adv = ModuleType("wx.adv")
    wx.App = FakeApp
    wx.CallAfter = lambda function, *args, **kwargs: function(*args, **kwargs)
    wx.adv = wx_adv
    wx_adv.TaskBarIcon = FakeTaskBarIcon

    dialogs = ModuleType("superpaper.configuration_dialogs")
    dialogs.HelpFrame = object
    dialogs.SettingsFrame = object
    gui = ModuleType("superpaper.gui")
    gui.ConfigFrame = object
    messages = ModuleType("superpaper.message_dialog")
    messages.show_message_dialog = lambda *args, **kwargs: None

    import superpaper

    previous_package_tray = getattr(superpaper, "tray", None)
    had_package_tray = hasattr(superpaper, "tray")
    monkeypatch.setitem(sys.modules, "wx", wx)
    monkeypatch.setitem(sys.modules, "wx.adv", wx_adv)
    monkeypatch.setitem(sys.modules, "superpaper.configuration_dialogs", dialogs)
    monkeypatch.setitem(sys.modules, "superpaper.gui", gui)
    monkeypatch.setitem(sys.modules, "superpaper.message_dialog", messages)
    monkeypatch.delitem(sys.modules, "superpaper.tray", raising=False)

    import superpaper.tray as tray

    previous_active_profile = tray.wpproc.G_ACTIVE_PROFILE
    yield tray
    tray.wpproc.G_ACTIVE_PROFILE = previous_active_profile
    if had_package_tray:
        superpaper.tray = previous_package_tray
    elif hasattr(superpaper, "tray"):
        delattr(superpaper, "tray")
