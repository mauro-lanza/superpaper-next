"""The tray application: what starting, reloading and quitting do, what runs at startup,
and how the session, the saved profiles, the hotkeys and the settings are kept together.

The windows, the tray icon and the hotkeys are stand-ins; the store is a fake unless a
test is about the profiles directory itself.
"""

import configparser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superpaper import displays
from superpaper.paths import AppPaths
from superpaper.profile_id import ProfileId
from superpaper.profile_store import ProfileStore
from superpaper.profiles import Profile
from superpaper.settings import Settings, read_settings

PATHS = AppPaths(config=Path("/config"), profiles=Path("/config/profiles"), cache=Path("/cache"))
LAYOUT = SimpleNamespace(name="the detected display layout")
FRESH = SimpleNamespace(name="the displays as detected again", size_hint=lambda: None)


class Detection:
    """Display detection, as the application runs it: records where layouts were loaded
    from; with ``error`` set, detection fails."""

    def __init__(self):
        self.config_dirs = []
        self.error = None

    def __call__(self, config_dir):
        self.config_dirs.append(config_dir)
        if self.error is not None:
            raise self.error
        return FRESH


@pytest.fixture(autouse=True)
def detection(monkeypatch):
    detect = Detection()
    monkeypatch.setattr(displays, "DisplaySystem", detect)
    return detect


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


def application(app, running=None, profiles=(), active=None, settings=None):
    """A running application, without its windows and icon."""
    superpaper = object.__new__(app.Superpaper)
    superpaper.paths = PATHS
    superpaper.settings_path = PATHS.config / "general_settings"
    superpaper.settings = settings or Settings()
    superpaper.store = FakeStore(profiles, active)
    superpaper.session = FakeSession(running)
    superpaper.hotkeys = None
    superpaper.tray = SimpleNamespace(
        clickable=True, remove=lambda: superpaper.session.requests.append(("tray removed",))
    )
    superpaper._frame = SimpleNamespace(Close=lambda: superpaper.session.requests.append(("frame closed",)))
    return superpaper


def profile(name):
    """A saved slideshow profile, as the application holds it."""
    return SimpleNamespace(profile=Profile(name=name, slideshow=True, delay=30.0), profile_id=ProfileId(name))


def test_a_profile_starts_on_freshly_detected_displays(headless_app_module, detection):
    superpaper = application(headless_app_module)
    work = profile("Work")

    superpaper.start_profile(work)
    superpaper.refresh_displays()

    # Detected here, on the main thread; the session only gets the layout.
    assert superpaper.session.requests == [("use_displays", FRESH), ("activate", work), ("use_displays", FRESH)]
    assert detection.config_dirs == [PATHS.config, PATHS.config]


@pytest.mark.parametrize(
    "error",
    [displays.DisplayDetectionError(3), configparser.Error("an unreadable display_systems.dat")],
)
def test_a_failed_display_detection_keeps_the_previous_layout(headless_app_module, detection, caplog, error):
    superpaper = application(headless_app_module)
    detection.error = error

    superpaper.refresh_displays()

    assert superpaper.session.requests == []
    assert "Keeping the previous display layout" in caplog.text


def test_a_profile_hotkey_starts_the_currently_loaded_profile(headless_app_module):
    current = profile("Work")
    superpaper = application(headless_app_module, profiles=[current])

    # The hotkey is bound to the profile's identity; it starts the record loaded now.
    superpaper.start_profile_by_id(ProfileId("Work"))

    assert superpaper.session.requests == [("use_displays", FRESH), ("activate", current)]


def test_a_hotkey_for_a_deleted_profile_does_nothing(headless_app_module):
    superpaper = application(headless_app_module)

    superpaper.start_profile_by_id(ProfileId("Deleted"))

    assert superpaper.session.requests == []


def test_the_windows_get_what_they_work_with(headless_app_module, monkeypatch, tmp_path):
    app = headless_app_module
    opened = []
    monkeypatch.setattr(app, "ConfigFrame", lambda *args, **kwargs: opened.append(("editor", args, kwargs)))
    monkeypatch.setattr(app, "SettingsFrame", lambda *args, **kwargs: opened.append(("settings", args, kwargs)))
    superpaper = application(app)
    superpaper.settings_path = tmp_path / "general_settings"

    superpaper.open_editor()
    superpaper.open_settings()

    (_, editor_args, editor_kwargs), settings_window = opened
    get_settings = editor_args[1]
    assert editor_args == (PATHS, get_settings, superpaper.store, superpaper.session)
    assert editor_kwargs == {
        "update_settings": superpaper.update_settings,
        "refresh_displays": superpaper.refresh_displays,
        "rebind_hotkey": superpaper.rebind_hotkey,
    }
    assert settings_window == ("settings", (superpaper.settings,), {"save_settings": superpaper.apply_settings})
    # A setting saved from the settings window after the editor opened is what the editor sees.
    superpaper.apply_settings(warn_large_img=False)
    assert get_settings() is superpaper.settings
    assert get_settings().warn_large_img is False


def test_quitting_stops_the_session_before_the_icon_goes(headless_app_module):
    superpaper = application(headless_app_module)

    superpaper.quit()

    assert superpaper.session.requests == [("shutdown",), ("tray removed",), ("frame closed",)]


@pytest.mark.parametrize(
    ("show_help", "clickable", "expected"),
    [
        (True, True, ["editor", "help"]),
        (True, False, ["editor", "help"]),
        (False, True, []),
        # Clicks on the wx icon don't work on KDE Plasma, so the configuration opens.
        (False, False, ["editor later"]),
    ],
)
def test_the_help_and_the_configuration_open_at_start_when_they_should(
    headless_app_module, monkeypatch, show_help, clickable, expected
):
    app = headless_app_module
    opened = []
    monkeypatch.setattr(app, "ConfigFrame", lambda *args, **kwargs: opened.append("editor"))
    monkeypatch.setattr(app, "HelpFrame", lambda get_settings, update_settings: opened.append("help"))
    monkeypatch.setattr(app.wx, "CallAfter", lambda function, *args: opened.append("editor later"))
    monkeypatch.setattr(app.desktop, "setter_problem", lambda set_command: None)
    superpaper = application(app, settings=Settings(show_help=show_help))
    superpaper.tray.clickable = clickable
    superpaper.session.display_system = FRESH

    superpaper._show_at_start()

    assert opened == expected


def test_problems_with_this_desktop_are_said_once_at_start(headless_app_module, monkeypatch):
    app = headless_app_module
    shown = []
    monkeypatch.setattr(app, "show_message_dialog", lambda message, *args: shown.append(message))
    monkeypatch.setattr(app.desktop, "setter_problem", lambda set_command: "no setter here")
    superpaper = application(app, settings=Settings(show_help=False))
    superpaper.session.display_system = SimpleNamespace(size_hint=lambda: "enter the sizes")

    superpaper._show_at_start()

    assert shown == ["no setter here", "enter the sizes"]


def test_a_normal_start_carries_on_with_the_last_profile(headless_app_module):
    work = profile("Work")
    superpaper = application(headless_app_module, profiles=[work], active=work)

    superpaper._run_at_startup(None)

    assert superpaper.session.requests == [("restore", work)]


def test_a_start_with_a_profile_runs_it(headless_app_module):
    work, home = profile("Work"), profile("Home")
    superpaper = application(headless_app_module, profiles=[work, home], active=work)

    superpaper._run_at_startup(ProfileId("Home"))

    assert superpaper.session.requests == [("activate", home)]


@pytest.mark.parametrize("startup", [None, ProfileId("Missing")])
def test_a_start_with_nothing_to_run_runs_nothing(headless_app_module, startup):
    superpaper = application(headless_app_module, profiles=[profile("Work")])

    superpaper._run_at_startup(startup)

    assert superpaper.session.requests == []


@pytest.mark.parametrize(
    "raw",
    [ProfileId("Work"), "Work", "/outside/profiles/Work.profile", r"C:\outside\Work.profile"],
)
def test_startup_profile_compatibility_extracts_identity_only(headless_app_module, raw):
    assert headless_app_module._startup_profile_id(raw) == ProfileId("Work")


def test_startup_outside_path_cannot_select_by_path(headless_app_module):
    app = headless_app_module
    managed = profile("Work")
    superpaper = application(app, profiles=[managed])

    startup_id = app._startup_profile_id("/outside/not-the-managed-file/Work.profile")

    assert superpaper.store.get(startup_id) is managed
    assert app._startup_profile_id("/outside/Other.profile") == ProfileId("Other")
    assert superpaper.store.get(ProfileId("Other")) is None


@pytest.mark.parametrize("still_saved", [True, False])
def test_reloading_tells_the_session_what_became_of_the_running_profile(headless_app_module, still_saved):
    running = profile("Work")
    edited_elsewhere = profile("Work")
    superpaper = application(headless_app_module, running=running, profiles=[running])
    superpaper.store.on_disk = [edited_elsewhere] if still_saved else [profile("Other")]

    superpaper.reload_profiles()

    assert superpaper.session.requests == [("update", ProfileId("Work"), edited_elsewhere if still_saved else None)]


def test_reloading_while_nothing_runs_tells_the_session_nothing(headless_app_module):
    superpaper = application(headless_app_module, profiles=[profile("Work")])

    superpaper.reload_profiles()

    assert superpaper.session.requests == []


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
    headless_app_module, monkeypatch, tmp_path, answer
):
    app = headless_app_module
    paths, broken = broken_profile(tmp_path)
    questions = []
    monkeypatch.setattr(
        app, "show_message_dialog", lambda message, *_args, **_kwargs: questions.append(message) or answer
    )
    superpaper = application(app)
    superpaper.store = ProfileStore(paths)

    superpaper.reload_profiles()

    assert len(questions) == 1
    assert "'broken.profile'" in questions[0]
    assert broken.exists() is not answer
    assert [stored.profile.name for stored in superpaper.store.profiles] == ["fine"]


def test_a_profile_fixed_while_the_question_is_open_is_kept(headless_app_module, monkeypatch, tmp_path):
    app = headless_app_module
    paths, broken = broken_profile(tmp_path)
    fixed = "name=broken\ndelay=60\n"

    def fix_then_agree(*_args, **_kwargs):
        broken.write_text(fixed, encoding="utf-8")
        return True

    monkeypatch.setattr(app, "show_message_dialog", fix_then_agree)
    superpaper = application(app)
    superpaper.store = ProfileStore(paths)

    superpaper.reload_profiles()

    assert broken.read_text(encoding="utf-8") == fixed


def test_only_profiles_that_cant_be_read_as_profiles_are_offered_for_deletion(
    headless_app_module, monkeypatch, tmp_path
):
    app = headless_app_module
    paths = AppPaths(config=tmp_path, profiles=tmp_path / "profiles", cache=tmp_path / "cache")
    paths.profiles.mkdir()
    (paths.profiles / "cli.profile").write_text("name=cli\n", encoding="utf-8")
    (paths.profiles / "gone.profile").symlink_to(tmp_path / "missing")
    (paths.profiles / "folder.profile").mkdir()
    monkeypatch.setattr(app, "show_message_dialog", lambda *_args, **_kwargs: pytest.fail("asked to delete"))
    superpaper = application(app)
    superpaper.store = ProfileStore(paths)

    superpaper.reload_profiles()

    assert superpaper.store.profiles == []
    assert sorted(path.name for path in paths.profiles.iterdir()) == ["cli.profile", "folder.profile", "gone.profile"]


def test_saved_profiles_take_their_hotkeys_along_while_hotkeys_are_on(headless_app_module):
    superpaper = application(headless_app_module)
    before, after = profile("Work"), profile("Office")

    superpaper.rebind_hotkey(before, after)  # hotkeys off: nothing to do

    superpaper.hotkeys = Mock()
    superpaper.rebind_hotkey(before, after)
    superpaper.hotkeys.profile_changed.assert_called_once_with(before, after)


@pytest.mark.parametrize(("use_hotkeys", "registered"), [(True, True), (False, False)])
def test_saved_general_settings_apply_from_now_on(headless_app_module, monkeypatch, tmp_path, use_hotkeys, registered):
    app = headless_app_module
    shown = []
    monkeypatch.setattr(app, "show_message_dialog", lambda message, kind: shown.append(message))
    superpaper = application(app)
    superpaper.settings_path = tmp_path / "general_settings"
    superpaper.hotkeys = Mock()
    saved = Settings(use_hotkeys=use_hotkeys, logging=True, set_command="setter {image}")

    superpaper.apply_settings(use_hotkeys=use_hotkeys, logging=True, set_command="setter {image}")

    # Hotkeys turned off apply after a restart; nothing new is bound meanwhile.
    assert superpaper.hotkeys.register_general.called is registered
    assert superpaper.settings == saved
    assert read_settings(superpaper.settings_path, "linux") == saved
    assert shown == ["Logging is enabled after an application restart."]


def test_a_dialog_setting_is_written_and_kept_for_the_next_window(headless_app_module, tmp_path):
    superpaper = application(headless_app_module, settings=Settings(show_help=True))
    superpaper.settings_path = tmp_path / "general_settings"

    superpaper.update_settings(browse_default_dir="/pictures")
    superpaper.update_settings(show_help=False)

    expected = Settings(browse_default_dir="/pictures", show_help=False)
    assert superpaper.settings == expected
    assert read_settings(superpaper.settings_path, "linux") == expected


def test_hotkeys_are_bound_at_start_when_they_are_on(headless_app_module, monkeypatch):
    app = headless_app_module
    made = []

    class RecordingHotkeys:
        def __init__(self, **actions):
            made.append(sorted(actions))
            self.registered = []

        def register_general(self, settings):
            self.registered.append(("general", settings))

        def register_profiles(self, profiles):
            self.registered.append(("profiles", profiles))

    monkeypatch.setattr(app, "Hotkeys", RecordingHotkeys)
    work = profile("Work")
    settings = Settings(use_hotkeys=True)
    superpaper = application(app, profiles=[work], settings=settings)

    hotkeys = superpaper._start_hotkeys()

    assert made == [["next_wallpaper", "pause", "start_profile"]]
    assert hotkeys.registered == [("general", settings), ("profiles", [work])]


def test_no_hotkeys_when_they_are_off_or_unavailable(headless_app_module, monkeypatch):
    app = headless_app_module

    def unavailable(**actions):
        message = "No module named 'system_hotkey'"
        raise ImportError(message)

    monkeypatch.setattr(app, "Hotkeys", unavailable)

    assert application(app, settings=Settings(use_hotkeys=False))._start_hotkeys() is None
    assert application(app, settings=Settings(use_hotkeys=True))._start_hotkeys() is None
