"""System-wide hotkeys: what each key combination is bound to, and what pressing it does.

system_hotkey is replaced by a recorder that refuses keys it doesn't know, as the real
library does; pressing keys calls what they were registered with.
"""

import sys
from types import SimpleNamespace

import pytest

from superpaper.desktop import hotkeys as hotkeys_module
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId
from superpaper.settings import Settings

KNOWN_KEYS = {"control", "super", "shift", "alt", "w", "p", "h", "x", "y"}


class FakeSystemHotkey:
    """system_hotkey's SystemHotkey: binds keys to a callback, or to arguments that its
    consumer gets when they are pressed."""

    def __init__(self, consumer="callback", check_queue_interval=0.01):
        self.consumer = consumer
        self.bound = {}

    def register(self, hotkey, *args, callback=None, overwrite=False):
        if not set(hotkey) <= KNOWN_KEYS:
            message = f"unknown key in {hotkey}"
            raise ValueError(message)
        if tuple(hotkey) in self.bound and not overwrite:
            message = f"{hotkey} is bound already"
            raise RuntimeError(message)
        self.bound[tuple(hotkey)] = callback if self.consumer == "callback" else args

    def unregister(self, hotkey):
        del self.bound[tuple(hotkey)]

    def press(self, hotkey):
        bound = self.bound[tuple(hotkey)]
        if self.consumer == "callback":
            bound("an event")
        else:
            self.consumer("an event", hotkey, [bound])


class Recorder:
    """The hotkeys' actions and the messages shown, in order."""

    def __init__(self):
        self.events = []

    def __call__(self, name):
        return lambda *args: self.events.append((name, *args))


@pytest.fixture
def setup(monkeypatch):
    recorder = Recorder()
    monkeypatch.setitem(sys.modules, "system_hotkey", SimpleNamespace(SystemHotkey=FakeSystemHotkey))
    monkeypatch.setattr(hotkeys_module, "running_kde", lambda: False)
    hotkeys = hotkeys_module.Hotkeys(
        next_wallpaper=recorder("next"),
        pause=recorder("pause"),
        start_profile=recorder("start profile"),
        call_soon=lambda action: action(),
        report=lambda message: recorder("dialog")(message),
    )
    return SimpleNamespace(module=hotkeys_module, hotkeys=hotkeys, events=recorder.events)


def saved(name, hotkey):
    return SimpleNamespace(profile_id=ProfileId(name), profile=Profile(name=name, hotkey=hotkey))


NEXT = ("control", "super", "w")
PAUSE = ("control", "super", "shift", "p")
GENERAL = Settings(hk_binding_next=NEXT, hk_binding_pause=PAUSE)


def press(setup, keys):
    """Press ``keys``, bound to the next wallpaper, pause or a profile."""
    hotkeys = setup.hotkeys
    general = hotkeys._general
    (general if tuple(keys) in general.bound else hotkeys._profiles).press(keys)


def test_the_general_hotkeys_run_their_actions(setup):
    setup.hotkeys.register_general(GENERAL)

    press(setup, NEXT)
    press(setup, PAUSE)

    assert setup.events == [("next",), ("pause",)]


def test_registering_the_same_settings_again_changes_nothing(setup):
    work = saved("Work", ("control", "x"))
    setup.hotkeys.register_general(GENERAL)
    setup.hotkeys.register_profiles([work])

    # Saving the general settings registers them again; nothing is "bound already".
    setup.hotkeys.register_general(GENERAL)

    assert setup.events == []
    assert set(setup.hotkeys._general.bound) == {NEXT, PAUSE}


def test_a_changed_general_hotkey_replaces_its_keys(setup):
    setup.hotkeys.register_general(GENERAL)

    setup.hotkeys.register_general(Settings(hk_binding_next=("control", "w"), hk_binding_pause=PAUSE))

    assert set(setup.hotkeys._general.bound) == {("control", "w"), PAUSE}
    press(setup, ("control", "w"))
    assert setup.events == [("next",)]


def test_a_general_hotkey_that_isnt_set_is_left_unbound(setup):
    setup.hotkeys.register_general(Settings(hk_binding_next=None, hk_binding_pause=PAUSE))

    assert set(setup.hotkeys._general.bound) == {PAUSE}
    assert setup.events == []


def test_a_general_hotkey_cleared_in_settings_is_released(setup):
    setup.hotkeys.register_general(GENERAL)

    setup.hotkeys.register_general(Settings(hk_binding_next=None, hk_binding_pause=PAUSE))

    assert set(setup.hotkeys._general.bound) == {PAUSE}
    assert NEXT not in setup.hotkeys._owners


def test_a_profile_hotkey_starts_its_profile_by_identity(setup):
    setup.hotkeys.register_profiles([saved("Work", ("control", "x")), saved("Home", None)])

    press(setup, ("control", "x"))

    assert setup.events == [("start profile", ProfileId("Work"))]


def test_keys_bound_already_are_refused_with_a_message(setup):
    setup.hotkeys.register_general(GENERAL)

    setup.hotkeys.register_profiles(
        [saved("Work", NEXT), saved("Home", ("control", "h")), saved("Copy", ("control", "h"))]
    )

    assert [event[0] for event in setup.events] == ["dialog", "dialog"]
    assert "for profile: 'Work'" in setup.events[0][1]
    assert "for profile: 'Copy'" in setup.events[1][1]
    press(setup, ("control", "h"))
    assert setup.events[-1] == ("start profile", ProfileId("Home"))


def test_keys_the_library_refuses_are_reported(setup):
    setup.hotkeys.register_profiles([saved("Work", ("control", "bogus"))])

    assert setup.events == [
        (
            "dialog",
            "Error: could not register hotkey control+bogus. Check that it is formatted properly and valid keys.",
        )
    ]
    assert setup.hotkeys._profiles.bound == {}


def test_hotkey_errors_are_only_logged_on_kde(setup, monkeypatch, caplog):
    monkeypatch.setattr(setup.module, "running_kde", lambda: True)

    setup.hotkeys.register_profiles([saved("Work", ("control", "bogus"))])

    assert setup.events == []
    assert "could not register hotkey control+bogus" in caplog.text


def test_a_renamed_profile_keeps_its_hotkey(setup):
    work = saved("Work", ("control", "x"))
    setup.hotkeys.register_profiles([work])

    setup.hotkeys.profile_changed(work, saved("Office", ("control", "x")))
    press(setup, ("control", "x"))

    assert setup.events == [("start profile", ProfileId("Office"))]


def test_a_changed_profile_hotkey_replaces_its_keys(setup):
    work = saved("Work", ("control", "x"))
    setup.hotkeys.register_profiles([work])

    setup.hotkeys.profile_changed(work, saved("Work", ("control", "y")))

    assert set(setup.hotkeys._profiles.bound) == {("control", "y")}


def test_a_new_profile_with_a_hotkey_is_bound(setup):
    setup.hotkeys.profile_changed(None, saved("Work", ("control", "x")))

    assert set(setup.hotkeys._profiles.bound) == {("control", "x")}


def test_a_deleted_profile_frees_its_hotkey(setup):
    work = saved("Work", ("control", "x"))
    setup.hotkeys.register_profiles([work])

    setup.hotkeys.profile_changed(work, None)
    setup.hotkeys.profile_changed(None, saved("Home", ("control", "x")))
    press(setup, ("control", "x"))

    assert setup.events == [("start profile", ProfileId("Home"))]


def test_saving_a_profile_without_changing_its_hotkey_changes_nothing(setup):
    work = saved("Work", ("control", "x"))
    setup.hotkeys.register_profiles([work])
    bound = dict(setup.hotkeys._profiles.bound)

    setup.hotkeys.profile_changed(work, saved("Work", ("control", "x")))

    assert setup.hotkeys._profiles.bound == bound
    assert setup.events == []


def test_another_profiles_hotkey_is_left_alone(setup):
    home = saved("Home", ("control", "h"))
    setup.hotkeys.register_profiles([home])

    # Work was saved with Home's keys, which it couldn't get; giving them up again must
    # not unbind Home.
    setup.hotkeys.profile_changed(saved("Work", ("control", "h")), saved("Work", None))
    press(setup, ("control", "h"))

    assert setup.events[-1] == ("start profile", ProfileId("Home"))
