"""The tray: its menus, hotkeys and startup ask the session to do things, and it keeps the
session told about the saved profiles."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superpaper.paths import AppPaths
from superpaper.profile_id import ProfileId
from superpaper.profile_store import ProfileStore
from superpaper.profiles import Profile
from superpaper.settings import Settings

PATHS = AppPaths(config=Path("/config"), profiles=Path("/config/profiles"), cache=Path("/cache"))
LAYOUT = SimpleNamespace(name="the detected display layout")


class FakeStore:
    """The saved profiles; reloading finds what ``on_disk`` holds then."""

    def __init__(self, profiles, active=None):
        self.profiles = list(profiles)
        self.on_disk = list(profiles)
        self.last_running = active

    def get(self, profile_id):
        return next((stored for stored in self.profiles if stored.profile_id == profile_id), None)

    def reload(self):
        self.profiles = list(self.on_disk)
        return ()

    def active(self):
        return self.last_running


class FakeSession:
    """The session, recording what it is asked to do."""

    def __init__(self, running=None):
        self.running = running
        self.paused = False
        self.display_system = LAYOUT
        self.requests = []

    def __getattr__(self, request):
        return lambda *args, **kwargs: self.requests.append((request, *args, *kwargs.values()))


def controller(tray, running=None, profiles=(), active=None):
    icon = object.__new__(tray.TaskBarIcon)
    icon.paths = PATHS
    icon.store = FakeStore(profiles, active)
    icon.g_settings = Settings()
    icon.session = FakeSession(running)
    icon.hk2 = None
    icon.seen_binding = set()
    return icon


def profile(name):
    """A saved slideshow profile, as the tray holds it."""
    return SimpleNamespace(profile=Profile(name=name, slideshow=True, delay=30.0), profile_id=ProfileId(name))


def test_the_menus_ask_the_session(headless_tray_module):
    tray = headless_tray_module
    work = profile("Work")
    icon = controller(tray)
    done = object()

    icon.start_profile(None, work)
    icon.next_wallpaper(None)
    icon.pause_timer(None)
    icon.refresh_displays()
    icon.apply_draft(work.profile, ["/image.png"], display_system="unsaved", on_done=done)

    assert icon.session.requests == [
        ("activate", work),
        ("next",),
        ("toggle_pause",),
        ("refresh_displays",),
        ("apply_draft", work.profile, ["/image.png"], "unsaved", done),
    ]


def test_starting_no_profile_asks_nothing(headless_tray_module):
    icon = controller(headless_tray_module)

    icon.start_profile(None, None)

    assert icon.session.requests == []


def test_the_tray_shows_what_the_session_runs(headless_tray_module):
    work = profile("Work")
    icon = controller(headless_tray_module, running=work)
    icon.session.paused = True

    assert icon.active_profile is work
    assert icon.is_paused is True
    assert icon.display_system is LAYOUT


def test_quitting_stops_the_session(headless_tray_module):
    icon = controller(headless_tray_module)
    icon._sni_tray = None
    icon.frame = SimpleNamespace(Close=lambda: None)
    icon.Destroy = lambda: None

    icon.on_exit(None)

    assert icon.session.requests == [("shutdown",)]


def test_a_normal_start_carries_on_with_the_last_profile(headless_tray_module):
    work = profile("Work")
    icon = controller(headless_tray_module, profiles=[work], active=work)

    icon._run_at_startup(None)

    assert icon.session.requests == [("restore", work)]


def test_a_start_with_a_profile_runs_it(headless_tray_module):
    work, home = profile("Work"), profile("Home")
    icon = controller(headless_tray_module, profiles=[work, home], active=work)

    icon._run_at_startup(ProfileId("Home"))

    assert icon.session.requests == [("activate", home)]


@pytest.mark.parametrize("startup", [None, ProfileId("Missing")])
def test_a_start_with_nothing_to_run_runs_nothing(headless_tray_module, startup):
    icon = controller(headless_tray_module, profiles=[profile("Work")])

    icon._run_at_startup(startup)

    assert icon.session.requests == []


@pytest.mark.parametrize(
    "raw",
    [ProfileId("Work"), "Work", "/outside/profiles/Work.profile", r"C:\outside\Work.profile"],
)
def test_startup_profile_compatibility_extracts_identity_only(headless_tray_module, raw):
    assert headless_tray_module._startup_profile_id(raw) == ProfileId("Work")


def test_startup_outside_path_cannot_select_by_path(headless_tray_module):
    tray = headless_tray_module
    managed = profile("Work")
    icon = controller(tray, profiles=[managed])

    startup_id = tray._startup_profile_id("/outside/not-the-managed-file/Work.profile")

    assert icon.get_profile_by_id(startup_id) is managed
    assert tray._startup_profile_id("/outside/Other.profile") == ProfileId("Other")
    assert icon.get_profile_by_id(ProfileId("Other")) is None


@pytest.mark.parametrize("still_saved", [True, False])
def test_reloading_tells_the_session_what_became_of_the_running_profile(headless_tray_module, still_saved):
    running = profile("Work")
    edited_elsewhere = profile("Work")
    icon = controller(headless_tray_module, running=running, profiles=[running])
    icon.store.on_disk = [edited_elsewhere] if still_saved else [profile("Other")]

    icon.reload_profiles(None)

    assert icon.session.requests == [("update", ProfileId("Work"), edited_elsewhere if still_saved else None)]


def test_reloading_while_nothing_runs_tells_the_session_nothing(headless_tray_module):
    icon = controller(headless_tray_module, profiles=[profile("Work")])

    icon.reload_profiles(None)

    assert icon.session.requests == []


def broken_profile(tmp_path):
    """A profiles directory holding a profile that loads and one that can't."""
    paths = AppPaths(config=tmp_path, profiles=tmp_path / "profiles", cache=tmp_path / "cache")
    paths.profiles.mkdir()
    (paths.profiles / "fine.profile").write_text("name=fine\n", encoding="utf-8")
    broken = paths.profiles / "broken.profile"
    broken.write_text("name=broken\ndelay=not-a-number\n", encoding="utf-8")
    return paths, broken


@pytest.mark.parametrize("answer", [True, False])
def test_a_profile_that_cant_be_loaded_is_deleted_if_the_user_agrees(
    headless_tray_module, monkeypatch, tmp_path, answer
):
    tray = headless_tray_module
    paths, broken = broken_profile(tmp_path)
    questions = []
    monkeypatch.setattr(
        tray, "show_message_dialog", lambda message, *_args, **_kwargs: questions.append(message) or answer
    )
    icon = controller(tray)
    icon.store = ProfileStore(paths)

    icon.reload_profiles(None)

    assert len(questions) == 1
    assert "'broken.profile'" in questions[0]
    assert broken.exists() is not answer
    assert [stored.profile.name for stored in icon.list_of_profiles] == ["fine"]


def test_a_profile_fixed_while_the_question_is_open_is_kept(headless_tray_module, monkeypatch, tmp_path):
    tray = headless_tray_module
    paths, broken = broken_profile(tmp_path)
    fixed = "name=broken\ndelay=60\n"

    def fix_then_agree(*_args, **_kwargs):
        broken.write_text(fixed, encoding="utf-8")
        return True

    monkeypatch.setattr(tray, "show_message_dialog", fix_then_agree)
    icon = controller(tray)
    icon.store = ProfileStore(paths)

    icon.reload_profiles(None)

    assert broken.read_text(encoding="utf-8") == fixed


def test_only_profiles_that_cant_be_read_as_profiles_are_offered_for_deletion(
    headless_tray_module, monkeypatch, tmp_path
):
    tray = headless_tray_module
    paths = AppPaths(config=tmp_path, profiles=tmp_path / "profiles", cache=tmp_path / "cache")
    paths.profiles.mkdir()
    (paths.profiles / "cli.profile").write_text("name=cli\n", encoding="utf-8")
    (paths.profiles / "gone.profile").symlink_to(tmp_path / "missing")
    (paths.profiles / "folder.profile").mkdir()
    monkeypatch.setattr(tray, "show_message_dialog", lambda *_args, **_kwargs: pytest.fail("asked to delete"))
    icon = controller(tray)
    icon.store = ProfileStore(paths)

    icon.reload_profiles(None)

    assert icon.list_of_profiles == []
    assert sorted(path.name for path in paths.profiles.iterdir()) == ["cli.profile", "folder.profile", "gone.profile"]


def test_profile_hotkey_starts_the_currently_loaded_profile(headless_tray_module):
    tray = headless_tray_module
    stale = profile("Work")
    current = profile("Work")
    icon = controller(tray, profiles=[current])

    # system_hotkey hands the consumer the arguments the binding was registered with.
    icon.profile_consumer(None, ("control", "w"), [(stale.profile_id,)])

    assert icon.session.requests == [("activate", current)]


def test_hotkey_for_a_deleted_profile_does_nothing(headless_tray_module):
    icon = controller(headless_tray_module)

    icon.profile_consumer(None, ("control", "w"), [(ProfileId("Deleted"),)])

    assert icon.session.requests == []


def test_profile_hotkey_changes_are_ignored_while_hotkeys_are_disabled(headless_tray_module):
    icon = controller(headless_tray_module)

    icon.update_hotkey("Work", ("control", "x"), ("control", "y"))

    assert icon.seen_binding == set()


def test_profile_hotkey_change_rebinds_by_identity(headless_tray_module):
    icon = controller(headless_tray_module)
    icon.hk2 = Mock()
    icon.seen_binding = {("control", "x")}

    icon.update_hotkey("Work", ("control", "x"), ("control", "y"))

    icon.hk2.unregister.assert_called_once_with(("control", "x"))
    icon.hk2.register.assert_called_once_with(("control", "y"), ProfileId("Work"), overwrite=False)
    assert icon.seen_binding == {("control", "y")}


def test_removing_a_profile_hotkey_unbinds_it(headless_tray_module):
    icon = controller(headless_tray_module)
    icon.hk2 = Mock()
    icon.seen_binding = {("control", "x")}

    icon.update_hotkey("Work", ("control", "x"), None)

    icon.hk2.unregister.assert_called_once_with(("control", "x"))
    icon.hk2.register.assert_not_called()
    assert icon.seen_binding == set()
