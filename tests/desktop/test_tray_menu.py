from types import SimpleNamespace

from superpaper.desktop.tray_menu import Check, Item, Notice, Separator, Submenu, failure_notice, tray_menu
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId


def stored(name, *, slideshow=True):
    return SimpleNamespace(
        profile=Profile(name=name, slideshow=slideshow), profile_id=ProfileId.parse(name, windows_names=False)
    )


def menu(profiles=(), running=None, *, paused=False, last_failure=None, calls=None):
    calls = [] if calls is None else calls

    def record(name):
        return lambda *args: calls.append((name, *args))

    return tray_menu(
        profiles,
        running,
        paused=paused,
        last_failure=last_failure,
        open_config_folder=record("config folder"),
        open_editor=record("editor"),
        open_settings=record("settings"),
        reload_profiles=record("reload"),
        start_profile=record("start"),
        next_wallpaper=record("next"),
        toggle_pause=record("pause"),
        about=record("about"),
        quit=record("quit"),
    )


def entry_labelled(entries, label):
    return next(entry for entry in entries if getattr(entry, "label", None) == label)


def profiles_of(entries):
    (profiles,) = (entry for entry in entries if isinstance(entry, Submenu))
    return profiles


def test_a_long_failure_reason_is_cut_to_its_first_line_with_an_ellipsis():
    assert failure_notice("y" * 200 + "\nsecond line").label == "Last change failed: " + "y" * 79 + "…"


def test_a_short_failure_reason_is_shown_whole():
    assert failure_notice("  Image missing\ndetails").label == "Last change failed: Image missing"


def test_every_entry_asks_what_it_was_given():
    work, calls = stored("Work"), []
    entries = menu([work], work, calls=calls)

    for entry in [*(e for e in entries if isinstance(e, (Item, Check))), *profiles_of(entries).items]:
        entry.action()

    assert calls == [
        ("config folder",),
        ("editor",),
        ("settings",),
        ("reload",),
        ("next",),
        ("pause",),
        ("about",),
        ("quit",),
        ("start", work),
    ]


def test_the_menu_lists_the_saved_profiles_and_shows_pause():
    entries = menu([stored("Work"), stored("Home")], paused=True)

    assert profiles_of(entries).label == "Profiles"
    assert [item.label for item in profiles_of(entries).items] == ["Work", "Home"]
    assert [entry.checked for entry in entries if isinstance(entry, Check)] == [True]
    assert sum(isinstance(entry, Separator) for entry in entries) == 3


def test_the_running_profile_is_the_one_checked():
    work, home = stored("Work"), stored("Home")

    entries = menu([work, home], home)

    assert [(item.label, item.checked) for item in profiles_of(entries).items] == [("Work", False), ("Home", True)]


def test_no_profile_is_checked_while_nothing_runs():
    assert [item.checked for item in profiles_of(menu([stored("Work")])).items] == [False]


def test_without_profiles_the_submenu_holds_a_disabled_placeholder():
    assert profiles_of(menu()).items == (Notice("(no profiles)"),)


def test_next_and_pause_are_disabled_while_nothing_runs():
    entries = menu([stored("Work")])

    assert entry_labelled(entries, "Next Wallpaper").enabled is False
    assert entry_labelled(entries, "Pause Timer").enabled is False


def test_pause_is_enabled_only_for_a_running_slideshow():
    slideshow, still = stored("Work"), stored("Home", slideshow=False)

    running_slideshow = menu([slideshow], slideshow)
    running_still = menu([still], still)

    assert entry_labelled(running_slideshow, "Pause Timer").enabled is True
    assert entry_labelled(running_slideshow, "Next Wallpaper").enabled is True
    assert entry_labelled(running_still, "Pause Timer").enabled is False
    assert entry_labelled(running_still, "Next Wallpaper").enabled is True


def test_a_failed_change_is_the_first_line_of_the_menu_until_cleared():
    assert not any(isinstance(entry, Notice) for entry in menu())

    entries = menu(last_failure="Image missing")

    assert entries[0] == Notice("Last change failed: Image missing")
    assert isinstance(entries[1], Separator)
