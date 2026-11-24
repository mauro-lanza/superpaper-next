"""The tray icon: which icon is shown, and what its menu does. The native SNI menu renders the
same menu (see desktop/test_sni_tray)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from superpaper.desktop.process import Result
from superpaper.desktop.tray_menu import Check, Item, Submenu
from superpaper.paths import AppPaths
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId
from tests.desktop.fake import FakeDesktop

CONFIG_DIR = Path("/config")


class Recorder:
    """The application's side of the menu, and the session's, recording what is asked."""

    def __init__(self):
        self.calls = []

    def __call__(self, name):
        return lambda *args: self.calls.append((name, *args))


def profile(name, *, slideshow=True):
    return SimpleNamespace(
        profile=Profile(name=name, slideshow=slideshow), profile_id=ProfileId.parse(name, windows_names=False)
    )


@pytest.fixture
def recorder():
    return Recorder()


def icon(tray, recorder, *, desktop=None, profiles=(), paused=False, failure=None, running=None):
    """A tray icon, built as the application builds it, with the wx icon."""
    store = SimpleNamespace(profiles=list(profiles))
    session = SimpleNamespace(paused=paused, running=running, toggle_pause=recorder("pause"))
    return tray.TaskBarIcon(
        store,
        session,
        desktop or FakeDesktop(),
        last_failure=lambda: failure,
        paths=AppPaths(config=CONFIG_DIR, profiles=CONFIG_DIR / "profiles", cache=CONFIG_DIR / "cache"),
        open_editor=recorder("editor"),
        open_settings=recorder("settings"),
        reload_profiles=recorder("reload"),
        start_profile=recorder("start"),
        next_wallpaper=recorder("next"),
        quit=recorder("quit"),
    )


@pytest.fixture
def tray(headless_tray_module, monkeypatch):
    """The tray module, with a recording wx icon."""
    monkeypatch.setattr(headless_tray_module.TaskBarIcon, "set_icon", lambda self, path: setattr(self, "wx_icon", path))
    return headless_tray_module


def test_the_menu_asks_the_application_and_the_session(tray, recorder):
    work = profile("Work")
    entries = icon(tray, recorder, profiles=[work], running=work).menu()
    # Open Config Folder and About are the tray's own, tested on their own.
    own = {"Open Config Folder", "About"}
    clickable = [entry for entry in entries if isinstance(entry, (Item, Check)) and entry.label not in own]
    (profiles,) = (entry for entry in entries if isinstance(entry, Submenu))

    for entry in [*clickable, *profiles.items]:
        entry.action()

    assert [entry.label for entry in clickable] == [
        "Wallpaper Configuration",
        "Settings",
        "Reload Profiles",
        "Next Wallpaper",
        "Pause Timer",
        "Exit",
    ]
    assert recorder.calls == [
        ("editor",),
        ("settings",),
        ("reload",),
        ("next",),
        ("pause",),
        ("quit",),
        ("start", work),
    ]


def test_a_left_click_opens_the_editor(tray, recorder):
    icon(tray, recorder).on_left_down(None)

    assert recorder.calls == [("editor",)]


def test_a_config_folder_that_cant_be_opened_is_reported(tray, recorder, desktop, monkeypatch):
    shown = []
    desktop.folder_answer = Result("no file manager")
    monkeypatch.setattr(tray, "show_message", lambda message: shown.append(message))

    icon(tray, recorder, desktop=desktop).open_config()

    assert desktop.opened == [CONFIG_DIR]
    assert shown == ["There was an error trying to open the config folder."]


def test_the_config_folder_menu_item_opens_the_config_folder(tray, recorder, desktop):
    entries = icon(tray, recorder, desktop=desktop).menu()

    (item,) = (entry for entry in entries if isinstance(entry, Item) and entry.label == "Open Config Folder")
    item.action()

    assert desktop.opened == [CONFIG_DIR]


@pytest.mark.parametrize(
    ("registers", "wx_clickable", "native", "clickable"),
    [
        (True, False, True, True),
        # No native tray: the wx icon, which the desktop may not deliver clicks for.
        (False, False, False, False),
        (False, True, False, True),
    ],
)
def test_the_native_tray_is_preferred_where_it_registers(tray, recorder, registers, wx_clickable, native, clickable):
    native_tray = SimpleNamespace(remove=recorder("native tray removed"))
    desktop = FakeDesktop()
    desktop.native_tray = native_tray if registers else None
    desktop.wx_tray_is_clickable = wx_clickable

    tray_icon = icon(tray, recorder, desktop=desktop)

    assert (tray_icon._native_tray is native_tray) is native
    assert hasattr(tray_icon, "wx_icon") is not native
    assert tray_icon.clickable is clickable


def test_the_native_tray_gets_the_menu_and_the_clicks(tray, recorder):
    desktop = FakeDesktop()
    tray_icon = icon(tray, recorder, desktop=desktop)
    (built,) = desktop.tray_requests

    built["activate"]()
    built["secondary_activate"]()

    assert built["menu"] == tray_icon.menu
    assert recorder.calls == [("editor",), ("next",)]


def test_taking_the_icon_away_removes_the_native_tray_too(tray, recorder):
    desktop = FakeDesktop()
    desktop.native_tray = SimpleNamespace(remove=recorder("native tray removed"))
    tray_icon = icon(tray, recorder, desktop=desktop)
    tray_icon.Destroy = recorder("icon destroyed")

    tray_icon.remove()

    assert recorder.calls == [("native tray removed",), ("icon destroyed",)]
