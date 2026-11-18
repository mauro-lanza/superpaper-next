"""The tray icon: which icon is shown, and what its menu does. The native SNI menu renders the
same menu (see test_sni_menu)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from superpaper.desktop.process import Result
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId
from superpaper.ui.tray_menu import Check, Item, Separator, Submenu

CONFIG_DIR = Path("/config")


class Recorder:
    """The application's side of the menu, and the session's, recording what is asked."""

    def __init__(self):
        self.calls = []

    def __call__(self, name):
        return lambda *args: self.calls.append((name, *args))


def profile(name):
    return SimpleNamespace(profile=Profile(name=name), profile_id=ProfileId(name))


@pytest.fixture
def recorder():
    return Recorder()


def icon(tray, recorder, *, profiles=(), paused=False):
    """A tray icon, built as the application builds it, with the wx icon."""
    store = SimpleNamespace(profiles=list(profiles))
    session = SimpleNamespace(paused=paused, next=recorder("next"), toggle_pause=recorder("pause"))
    return tray.TaskBarIcon(
        store,
        session,
        config_dir=CONFIG_DIR,
        open_editor=recorder("editor"),
        open_settings=recorder("settings"),
        reload_profiles=recorder("reload"),
        start_profile=recorder("start"),
        quit=recorder("quit"),
    )


@pytest.fixture
def tray(headless_tray_module, monkeypatch):
    """The tray module, without a native tray and with a recording wx icon."""
    monkeypatch.setattr(headless_tray_module, "sni_supported", lambda: False)
    monkeypatch.setattr(headless_tray_module.TaskBarIcon, "set_icon", lambda self, path: setattr(self, "wx_icon", path))
    return headless_tray_module


def test_the_menu_asks_the_application_and_the_session(tray, recorder):
    work = profile("Work")
    entries = icon(tray, recorder, profiles=[work]).menu()
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


def test_the_menu_lists_the_saved_profiles_and_shows_pause(tray, recorder):
    work, home = profile("Work"), profile("Home")

    entries = icon(tray, recorder, profiles=[work, home], paused=True).menu()

    (profiles,) = (entry for entry in entries if isinstance(entry, Submenu))
    assert profiles.label == "Profiles"
    assert [item.label for item in profiles.items] == ["Work", "Home"]
    assert [entry.checked for entry in entries if isinstance(entry, Check)] == [True]
    assert sum(isinstance(entry, Separator) for entry in entries) == 3


def test_a_left_click_opens_the_editor(tray, recorder):
    icon(tray, recorder).on_left_down(None)

    assert recorder.calls == [("editor",)]


def test_a_config_folder_that_cant_be_opened_is_reported(tray, recorder, monkeypatch):
    opened, shown = [], []
    monkeypatch.setattr(tray.desktop, "open_folder", lambda folder: opened.append(folder) or Result("no file manager"))
    monkeypatch.setattr(tray, "show_message_dialog", lambda message: shown.append(message))

    icon(tray, recorder).open_config()

    assert opened == [CONFIG_DIR]
    assert shown == ["There was an error trying to open the config folder."]


@pytest.mark.parametrize(
    ("supported", "registers", "kde", "native", "clickable"),
    [
        (True, True, True, True, True),
        # Registration fails: the wx icon, which can't be clicked on KDE Plasma 6.
        (True, False, True, False, False),
        (False, False, True, False, False),
        (False, False, False, False, True),
    ],
)
def test_the_native_tray_is_preferred_where_it_registers(
    tray, recorder, monkeypatch, supported, registers, kde, native, clickable
):
    native_tray = SimpleNamespace(remove=recorder("native tray removed"))
    monkeypatch.setattr(tray.sys, "platform", "linux")
    monkeypatch.setattr(tray, "sni_supported", lambda: supported)
    monkeypatch.setattr(tray, "build_tray", lambda **kwargs: native_tray if registers else None)
    monkeypatch.setattr(tray, "running_kde", lambda: kde)

    tray_icon = icon(tray, recorder)

    assert (tray_icon._sni_tray is native_tray) is native
    assert hasattr(tray_icon, "wx_icon") is not native
    assert tray_icon.clickable is clickable


def test_the_native_tray_gets_the_menu_and_the_clicks(tray, recorder, monkeypatch):
    built = {}
    monkeypatch.setattr(tray.sys, "platform", "linux")
    monkeypatch.setattr(tray, "sni_supported", lambda: True)
    monkeypatch.setattr(tray, "build_tray", lambda **kwargs: built.update(kwargs) or SimpleNamespace())
    tray_icon = icon(tray, recorder)

    built["activate"]()
    built["secondary_activate"]()

    assert built["menu"] == tray_icon.menu
    assert recorder.calls == [("editor",), ("next",)]


def test_taking_the_icon_away_removes_the_native_tray_too(tray, recorder, monkeypatch):
    native_tray = SimpleNamespace(remove=recorder("native tray removed"))
    monkeypatch.setattr(tray.sys, "platform", "linux")
    monkeypatch.setattr(tray, "sni_supported", lambda: True)
    monkeypatch.setattr(tray, "build_tray", lambda **kwargs: native_tray)
    tray_icon = icon(tray, recorder)
    tray_icon.Destroy = recorder("icon destroyed")

    tray_icon.remove()

    assert recorder.calls == [("native tray removed",), ("icon destroyed",)]
