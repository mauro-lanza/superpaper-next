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
    from superpaper.profiles.profile_id import ProfileId
    from superpaper.profiles.profile_store import ProfileStore

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
    from superpaper.geometry import display_detection

    def build(monitors=TWO_DISPLAYS, config_dir=None):
        monkeypatch.setattr(display_detection, "get_monitors", lambda: monitors)
        return display_detection.detect_layout(config_dir or tmp_path / "no-saved-layouts")

    return build


def write_profile(path: Path, *, spanmode="single", sources=(), selected=()):
    lines = ["name=test", f"spanmode={spanmode}", "slideshow=false", "sortmode=alphabetical"]
    lines.extend(f"display{i}paths={source}" for i, source in enumerate(sources))
    if selected:
        lines.append("selected=" + ";".join(map(str, selected)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def import_headless(monkeypatch, name, stubs):
    """Import ``superpaper.ui.<name>`` afresh, with ``stubs`` in sys.modules in place of the
    modules it imports. Returns the module and ``forget()``, which leaves sys.modules and
    the package as they were."""
    import importlib

    import superpaper.ui

    full_name = f"superpaper.ui.{name}"
    previous_module = sys.modules.get(full_name)
    previous_attribute = getattr(superpaper.ui, name, None)
    for stub_name, stub in stubs.items():
        monkeypatch.setitem(sys.modules, stub_name, stub)
    sys.modules.pop(full_name, None)
    module = importlib.import_module(full_name)

    def forget():
        if previous_module is None:
            sys.modules.pop(full_name, None)
        else:
            sys.modules[full_name] = previous_module
        if previous_attribute is None:
            if hasattr(superpaper.ui, name):
                delattr(superpaper.ui, name)
        else:
            setattr(superpaper.ui, name, previous_attribute)

    return module, forget


def wx_stub():
    """Just enough of wx for the UI modules' logic: CallAfter runs at once."""

    class FakeTaskBarIcon:
        def Bind(self, *args, **kwargs):
            pass

        def Destroy(self):
            pass

    class FakeApp:
        pass

    wx = ModuleType("wx")
    wx_adv = ModuleType("wx.adv")
    wx.App = FakeApp
    wx.CallAfter = lambda function, *args, **kwargs: function(*args, **kwargs)
    wx.adv = wx_adv
    wx_adv.TaskBarIcon = FakeTaskBarIcon
    for event in ("EVT_TASKBAR_LEFT_DOWN", "EVT_TASKBAR_LEFT_DCLICK", "EVT_TASKBAR_RIGHT_DOWN"):
        setattr(wx_adv, event, event)
    return {"wx": wx, "wx.adv": wx_adv}


def module_stub(name, **attributes):
    module = ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    return {name: module}


@pytest.fixture
def headless_tray_module(monkeypatch):
    """Import the tray icon against minimal wx stubs."""
    stubs = {
        **wx_stub(),
        **module_stub("superpaper.ui.message", show_message_dialog=lambda *args, **kwargs: None),
    }
    tray, forget = import_headless(monkeypatch, "tray", stubs)
    yield tray
    forget()


@pytest.fixture
def headless_app_module(monkeypatch):
    """Import the tray application against minimal wx and window stubs."""
    stubs = {
        **wx_stub(),
        **module_stub("superpaper.ui.editor", ConfigFrame=object),
        **module_stub("superpaper.ui.help", HelpFrame=object),
        **module_stub("superpaper.ui.settings_dialog", SettingsFrame=object),
        **module_stub("superpaper.ui.message", show_message_dialog=lambda *args, **kwargs: None),
        **module_stub("superpaper.ui.hotkeys", Hotkeys=object),
        **module_stub("superpaper.ui.tray", TaskBarIcon=object),
    }
    app, forget = import_headless(monkeypatch, "app", stubs)
    yield app
    forget()
