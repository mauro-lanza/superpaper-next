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


def load_profile(paths, name):
    """The record of the saved profile ``name`` (or ProfileId), loaded as the tray loads
    it; None if it doesn't load."""
    from superpaper.profile_id import ProfileId
    from superpaper.profile_store import ProfileStore

    store = ProfileStore(paths)
    store.reload()
    return store.get(name if isinstance(name, ProfileId) else ProfileId(name))


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
    from superpaper import displays

    def build(monitors=TWO_DISPLAYS, config_dir=None):
        monkeypatch.setattr(displays, "get_monitors", lambda: monitors)
        return displays.DisplaySystem(config_dir or tmp_path / "no-saved-layouts")

    return build


def write_profile(path: Path, *, spanmode="single", sources=(), selected=()):
    lines = ["name=test", f"spanmode={spanmode}", "slideshow=false", "sortmode=alphabetical"]
    lines.extend(f"display{i}paths={source}" for i, source in enumerate(sources))
    if selected:
        lines.append("selected=" + ";".join(map(str, selected)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


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

    editor = ModuleType("superpaper.ui.editor")
    editor.ConfigFrame = object
    help_ = ModuleType("superpaper.ui.help")
    help_.HelpFrame = object
    settings_dialog = ModuleType("superpaper.ui.settings_dialog")
    settings_dialog.SettingsFrame = object
    messages = ModuleType("superpaper.ui.message")
    messages.show_message_dialog = lambda *args, **kwargs: None

    import superpaper.ui

    previous_package_tray = getattr(superpaper.ui, "tray", None)
    had_package_tray = hasattr(superpaper.ui, "tray")
    monkeypatch.setitem(sys.modules, "wx", wx)
    monkeypatch.setitem(sys.modules, "wx.adv", wx_adv)
    monkeypatch.setitem(sys.modules, "superpaper.ui.editor", editor)
    monkeypatch.setitem(sys.modules, "superpaper.ui.help", help_)
    monkeypatch.setitem(sys.modules, "superpaper.ui.settings_dialog", settings_dialog)
    monkeypatch.setitem(sys.modules, "superpaper.ui.message", messages)
    monkeypatch.delitem(sys.modules, "superpaper.ui.tray", raising=False)

    import superpaper.ui.tray as tray

    yield tray
    if had_package_tray:
        superpaper.ui.tray = previous_package_tray
    elif hasattr(superpaper.ui, "tray"):
        delattr(superpaper.ui, "tray")
