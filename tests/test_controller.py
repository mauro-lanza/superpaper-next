"""The tray application: what starting, reloading and quitting do, what runs at startup,
and how the session, the saved profiles, the hotkeys and the settings are kept together.

The UI (windows, dialogs, tray icon) and the hotkeys are stand-ins; the store is a fake
unless a test is about the profiles directory itself.
"""

import configparser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superpaper import controller
from superpaper.controller import Shell
from superpaper.geometry import display_detection
from superpaper.paths import AppPaths
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId
from superpaper.profiles.profile_store import ProfileStore
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
    monkeypatch.setattr(display_detection, "detect_layout", detect)
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
        self.layout = LAYOUT
        self.requests = []

    def __getattr__(self, request):
        return lambda *args, **kwargs: self.requests.append((request, *args, *kwargs.values()))


def application(running=None, profiles=(), active=None, settings=None, **shell_actions):
    """A running application, without its windows and icon. ``shell_actions`` replace the
    UI actions, which otherwise record into ``superpaper.ui_events`` and answer yes."""
    superpaper = object.__new__(controller.Superpaper)
    events = []
    superpaper.ui_events = events
    actions = {
        "notify": lambda message, title: events.append(("notify", message, title)),
        "confirm": lambda message: events.append(("confirm", message)) or True,
        "call_soon": lambda action: events.append(("call_soon", action)),
        "open_editor": lambda app: events.append("editor"),
        "open_settings": lambda app: events.append("settings"),
        "open_help": lambda app: events.append("help"),
        "make_tray": lambda app: None,
        "close": lambda: superpaper.session.requests.append(("closed",)),
    }
    superpaper._shell = Shell(**{**actions, **shell_actions})
    superpaper.paths = PATHS
    superpaper.settings_path = PATHS.config / "general_settings"
    superpaper.settings = settings or Settings()
    superpaper.store = FakeStore(profiles, active)
    superpaper.session = FakeSession(running)
    superpaper.hotkeys = None
    superpaper.tray = SimpleNamespace(
        clickable=True, remove=lambda: superpaper.session.requests.append(("tray removed",))
    )
    return superpaper


def profile(name):
    """A saved slideshow profile, as the application holds it."""
    return SimpleNamespace(profile=Profile(name=name, slideshow=True, delay=30.0), profile_id=ProfileId(name))


def test_a_profile_starts_on_freshly_detected_displays(detection):
    superpaper = application()
    work = profile("Work")

    superpaper.start_profile(work)
    superpaper.refresh_displays()

    # Detected here, on the main thread; the session only gets the layout.
    assert superpaper.session.requests == [("use_displays", FRESH), ("activate", work), ("use_displays", FRESH)]
    assert detection.config_dirs == [PATHS.config, PATHS.config]


@pytest.mark.parametrize(
    "error",
    [display_detection.DisplayDetectionError(3), configparser.Error("an unreadable display_systems.dat")],
)
def test_a_failed_display_detection_keeps_the_previous_layout(detection, caplog, error):
    superpaper = application()
    detection.error = error

    superpaper.refresh_displays()

    assert superpaper.session.requests == []
    assert "Keeping the previous display layout" in caplog.text


def test_a_profile_hotkey_starts_the_currently_loaded_profile():
    current = profile("Work")
    superpaper = application(profiles=[current])

    # The hotkey is bound to the profile's identity; it starts the record loaded now.
    superpaper.start_profile_by_id(ProfileId("Work"))

    assert superpaper.session.requests == [("use_displays", FRESH), ("activate", current)]


def test_a_hotkey_for_a_deleted_profile_does_nothing():
    superpaper = application()

    superpaper.start_profile_by_id(ProfileId("Deleted"))

    assert superpaper.session.requests == []


def test_the_windows_are_opened_by_the_ui_with_the_application():
    opened = []
    superpaper = application(
        open_editor=lambda app: opened.append(("editor", app)),
        open_settings=lambda app: opened.append(("settings", app)),
    )

    superpaper.open_editor()
    superpaper.open_settings()

    assert opened == [("editor", superpaper), ("settings", superpaper)]


def test_an_editor_that_fails_to_open_is_logged(caplog):
    def broken(app):
        message = "no window"
        raise RuntimeError(message)

    application(open_editor=broken).open_editor()

    assert "configure_wallpapers error: no window" in caplog.text


def test_quitting_stops_the_session_before_the_icon_goes():
    superpaper = application()

    superpaper.quit()

    assert superpaper.session.requests == [("shutdown",), ("tray removed",), ("closed",)]


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
def test_the_help_and_the_configuration_open_at_start_when_they_should(monkeypatch, show_help, clickable, expected):
    opened = []
    superpaper = application(
        settings=Settings(show_help=show_help),
        open_editor=lambda app: opened.append("editor"),
        open_help=lambda app: opened.append("help"),
        call_soon=lambda action: opened.append("editor later") if action == superpaper.open_editor else None,
    )
    monkeypatch.setattr(controller.desktop, "setter_problem", lambda set_command: None)
    superpaper.tray.clickable = clickable
    superpaper.session.layout = FRESH

    superpaper._show_at_start()

    assert opened == expected


def test_problems_with_this_desktop_are_said_once_at_start(monkeypatch):
    shown = []
    superpaper = application(
        settings=Settings(show_help=False),
        notify=lambda message, title: shown.append((message, title)),
        call_soon=lambda action: action(),
    )
    monkeypatch.setattr(controller.desktop, "setter_problem", lambda set_command: "no setter here")
    superpaper.session.layout = SimpleNamespace(size_hint=lambda: "enter the sizes")

    superpaper._show_at_start()

    assert shown == [("no setter here", "Error"), ("enter the sizes", "Info")]


def test_a_normal_start_carries_on_with_the_last_profile():
    work = profile("Work")
    superpaper = application(profiles=[work], active=work)

    superpaper._run_at_startup(None)

    assert superpaper.session.requests == [("restore", work)]


def test_a_start_with_a_profile_runs_it():
    work, home = profile("Work"), profile("Home")
    superpaper = application(profiles=[work, home], active=work)

    superpaper._run_at_startup(ProfileId("Home"))

    assert superpaper.session.requests == [("activate", home)]


@pytest.mark.parametrize("startup", [None, ProfileId("Missing")])
def test_a_start_with_nothing_to_run_runs_nothing(startup):
    superpaper = application(profiles=[profile("Work")])

    superpaper._run_at_startup(startup)

    assert superpaper.session.requests == []


def test_startup_outside_path_cannot_select_by_path():
    managed = profile("Work")
    superpaper = application(profiles=[managed])

    startup_id = ProfileId.from_path("/outside/not-the-managed-file/Work.profile")

    assert superpaper.store.get(startup_id) is managed
    assert ProfileId.from_path("/outside/Other.profile") == ProfileId("Other")
    assert superpaper.store.get(ProfileId("Other")) is None


@pytest.mark.parametrize("still_saved", [True, False])
def test_reloading_tells_the_session_what_became_of_the_running_profile(still_saved):
    running = profile("Work")
    edited_elsewhere = profile("Work")
    superpaper = application(running=running, profiles=[running])
    superpaper.store.on_disk = [edited_elsewhere] if still_saved else [profile("Other")]

    superpaper.reload_profiles()

    assert superpaper.session.requests == [("update", ProfileId("Work"), edited_elsewhere if still_saved else None)]


def test_reloading_while_nothing_runs_tells_the_session_nothing():
    superpaper = application(profiles=[profile("Work")])

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
def test_a_profile_that_cant_be_loaded_is_deleted_if_the_user_agrees(tmp_path, answer):
    paths, broken = broken_profile(tmp_path)
    questions = []
    superpaper = application(confirm=lambda message: questions.append(message) or answer)
    superpaper.store = ProfileStore(paths)

    superpaper.reload_profiles()

    assert len(questions) == 1
    assert "'broken.profile'" in questions[0]
    assert broken.exists() is not answer
    assert [stored.profile.name for stored in superpaper.store.profiles] == ["fine"]


def test_a_profile_fixed_while_the_question_is_open_is_kept(tmp_path):
    paths, broken = broken_profile(tmp_path)
    fixed = "name=broken\ndelay=60\n"

    def fix_then_agree(message):
        broken.write_text(fixed, encoding="utf-8")
        return True

    superpaper = application(confirm=fix_then_agree)
    superpaper.store = ProfileStore(paths)

    superpaper.reload_profiles()

    assert broken.read_text(encoding="utf-8") == fixed


def test_only_profiles_that_cant_be_read_as_profiles_are_offered_for_deletion(tmp_path):
    paths = AppPaths(config=tmp_path, profiles=tmp_path / "profiles", cache=tmp_path / "cache")
    paths.profiles.mkdir()
    (paths.profiles / "cli.profile").write_text("name=cli\n", encoding="utf-8")
    (paths.profiles / "gone.profile").symlink_to(tmp_path / "missing")
    (paths.profiles / "folder.profile").mkdir()
    superpaper = application(confirm=lambda message: pytest.fail("asked to delete"))
    superpaper.store = ProfileStore(paths)

    superpaper.reload_profiles()

    assert superpaper.store.profiles == []
    assert sorted(path.name for path in paths.profiles.iterdir()) == ["cli.profile", "folder.profile", "gone.profile"]


def test_saved_profiles_take_their_hotkeys_along_while_hotkeys_are_on():
    superpaper = application()
    before, after = profile("Work"), profile("Office")

    superpaper.rebind_hotkey(before, after)  # hotkeys off: nothing to do

    superpaper.hotkeys = Mock()
    superpaper.rebind_hotkey(before, after)
    superpaper.hotkeys.profile_changed.assert_called_once_with(before, after)


@pytest.mark.parametrize(("use_hotkeys", "registered"), [(True, True), (False, False)])
def test_saved_general_settings_apply_from_now_on(tmp_path, use_hotkeys, registered):
    shown = []
    superpaper = application(notify=lambda message, title: shown.append((message, title)))
    superpaper.settings_path = tmp_path / "general_settings"
    superpaper.hotkeys = Mock()
    saved = Settings(use_hotkeys=use_hotkeys, logging=True, set_command="setter {image}")

    superpaper.apply_settings(use_hotkeys=use_hotkeys, logging=True, set_command="setter {image}")

    # Hotkeys turned off apply after a restart; nothing new is bound meanwhile.
    assert superpaper.hotkeys.register_general.called is registered
    assert superpaper.settings == saved
    assert read_settings(superpaper.settings_path, "linux") == saved
    assert shown == [("Logging is enabled after an application restart.", "Info")]


def test_a_dialog_setting_is_written_and_kept_for_the_next_window(tmp_path):
    superpaper = application(settings=Settings(show_help=True))
    superpaper.settings_path = tmp_path / "general_settings"

    superpaper.update_settings(browse_default_dir="/pictures")
    superpaper.update_settings(show_help=False)

    expected = Settings(browse_default_dir="/pictures", show_help=False)
    assert superpaper.settings == expected
    assert read_settings(superpaper.settings_path, "linux") == expected


def test_hotkeys_are_bound_at_start_when_they_are_on(monkeypatch):
    made = []

    class RecordingHotkeys:
        def __init__(self, **actions):
            made.append(sorted(actions))
            self.registered = []

        def register_general(self, settings):
            self.registered.append(("general", settings))

        def register_profiles(self, profiles):
            self.registered.append(("profiles", profiles))

    monkeypatch.setattr(controller, "Hotkeys", RecordingHotkeys)
    work = profile("Work")
    settings = Settings(use_hotkeys=True)
    superpaper = application(profiles=[work], settings=settings)

    hotkeys = superpaper._start_hotkeys()

    assert made == [["call_soon", "next_wallpaper", "pause", "report", "start_profile"]]
    assert hotkeys.registered == [("general", settings), ("profiles", [work])]


def test_hotkey_problems_are_reported_as_errors(monkeypatch):
    reports = []

    class RecordingHotkeys:
        def __init__(self, *, report, **actions):
            report("taken")

        def register_general(self, settings):
            pass

        def register_profiles(self, profiles):
            pass

    monkeypatch.setattr(controller, "Hotkeys", RecordingHotkeys)
    superpaper = application(notify=lambda message, title: reports.append((message, title)))

    superpaper.settings = Settings(use_hotkeys=True)
    superpaper._start_hotkeys()

    assert reports == [("taken", "Error")]


def test_no_hotkeys_when_they_are_off_or_unavailable(monkeypatch):
    def unavailable(**actions):
        message = "No module named 'system_hotkey'"
        raise ImportError(message)

    monkeypatch.setattr(controller, "Hotkeys", unavailable)

    assert application(settings=Settings(use_hotkeys=False))._start_hotkeys() is None
    assert application(settings=Settings(use_hotkeys=True))._start_hotkeys() is None
