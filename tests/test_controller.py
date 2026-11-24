"""The tray application: what starting, reloading and quitting do, what runs at startup,
and how the session, the saved profiles and the settings are kept together.

The UI (windows, dialogs, tray icon) is a stand-in; the store is a fake
unless a test is about the profiles directory itself.
"""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from superpaper import controller
from superpaper.controller import Shell
from superpaper.geometry import display_detection
from superpaper.geometry.display_store import LoadedLayout
from superpaper.paths import AppPaths
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId
from superpaper.profiles.profile_store import ProfileStore
from superpaper.settings import Settings, read_settings
from tests.desktop.fake import FakeDesktop

PATHS = AppPaths(config=Path("/config"), profiles=Path("/config/profiles"), cache=Path("/cache"))
LAYOUT = SimpleNamespace(name="the detected display layout")
FRESH = SimpleNamespace(name="the displays as detected again", size_hint=lambda: None)


class Detection:
    """Display detection, as the application runs it: records where layouts were loaded
    from; with ``error`` set, detection fails."""

    def __init__(self):
        self.config_dirs = []
        self.error = None
        self.problem = None

    def __call__(self, config_dir, desktop):
        self.config_dirs.append(config_dir)
        if self.error is not None:
            raise self.error
        return LoadedLayout(FRESH, self.problem)


@pytest.fixture(autouse=True)
def detection(monkeypatch):
    detect = Detection()
    monkeypatch.setattr(display_detection, "detect_layout_or_default", detect)
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
        "settle_unsaved_changes": lambda: True,
        "watch_displays": lambda refresh: True,
    }
    superpaper._shell = Shell(**{**actions, **shell_actions})
    superpaper.paths = PATHS
    superpaper.desktop = FakeDesktop()
    superpaper.settings_path = PATHS.config / "general_settings"
    superpaper.settings = settings or Settings()
    superpaper.store = FakeStore(profiles, active)
    superpaper.session = FakeSession(running)
    superpaper.last_failure = None
    superpaper._profile_watchers = []
    superpaper._layout_watchers = []
    superpaper._layout = LAYOUT
    superpaper._watching_displays = True
    superpaper._reported_layout_problem = None
    superpaper.tray = SimpleNamespace(
        clickable=True, remove=lambda: superpaper.session.requests.append(("tray removed",))
    )
    return superpaper


def profile(name):
    """A saved slideshow profile, as the application holds it."""
    return SimpleNamespace(
        profile=Profile(name=name, slideshow=True, delay=30.0), profile_id=ProfileId.parse(name, windows_names=False)
    )


def test_the_last_failed_change_is_kept_until_a_change_succeeds():
    superpaper = application(call_soon=lambda action: action())

    superpaper._report_change("Image missing")
    failed = superpaper.last_failure
    superpaper._report_change(None)

    assert failed == "Image missing"
    assert superpaper.last_failure is None


def test_a_change_reported_from_the_worker_is_handed_to_the_ui_thread():
    superpaper = application()

    superpaper._report_change("Image missing")

    assert superpaper.last_failure is None
    (_, remember) = superpaper.ui_events[0]
    remember()
    assert superpaper.last_failure == "Image missing"


def test_a_profile_starts_on_freshly_detected_displays(detection):
    superpaper = application()
    work = profile("Work")

    superpaper.start_profile(work)
    superpaper.refresh_displays()

    # Detected here, on the main thread; the session only gets the layout, once.
    assert superpaper.session.requests == [("use_displays", FRESH), ("activate", work)]
    assert detection.config_dirs == [PATHS.config, PATHS.config]


def test_a_layout_in_use_is_not_handed_to_the_session_again(detection):
    superpaper = application()

    superpaper.refresh_displays()
    superpaper.refresh_displays()
    superpaper.refresh_displays(redraw=True)

    assert superpaper.session.requests == [("use_displays", FRESH), ("redraw",)]


def test_a_new_layout_is_told_to_the_layout_watchers_on_the_ui_thread():
    superpaper = application()
    told = []
    stop = superpaper.watch_layout(told.append)

    superpaper.refresh_displays()
    assert told == []
    (_, notify) = superpaper.ui_events[-1]
    notify()
    stop()
    superpaper._layout = LAYOUT
    superpaper.refresh_displays()
    superpaper.ui_events[-1][1]()

    assert told == [FRESH]
    assert superpaper.layout is FRESH


def test_layout_watchers_are_told_after_every_detection_even_when_the_layout_is_the_same():
    superpaper = application()
    told = []
    superpaper.watch_layout(told.append)
    superpaper._layout = FRESH

    superpaper.refresh_displays()
    superpaper.ui_events[-1][1]()

    assert told == [FRESH]
    assert superpaper.session.requests == []


def test_displays_are_detected_again_when_the_editor_opens():
    superpaper = application()

    superpaper.open_editor()

    assert superpaper.session.requests == [("use_displays", FRESH)]
    assert superpaper.ui_events[-1] == "editor"


def test_next_detects_the_displays_again_only_where_the_os_cannot_report_changes(detection):
    watching = application()
    not_watching = application()
    not_watching._watching_displays = False

    watching.next_wallpaper()
    not_watching.next_wallpaper()

    assert watching.session.requests == [("next",)]
    assert not_watching.session.requests == [("use_displays", FRESH), ("next",)]
    assert len(detection.config_dirs) == 1


@pytest.mark.parametrize("error", [display_detection.DisplayDetectionError(3), OSError("no access to the config")])
def test_a_failed_display_detection_keeps_the_previous_layout(detection, caplog, error):
    superpaper = application()
    detection.error = error

    superpaper.refresh_displays()

    assert superpaper.session.requests == []
    assert "Keeping the previous display layout" in caplog.text


def test_a_saved_layout_that_cant_be_used_is_reported_once_and_the_default_is_used(detection):
    superpaper = application()
    superpaper._layout = FRESH
    detection.problem = "The saved display layout can't be used."

    superpaper.refresh_displays()
    superpaper.refresh_displays()

    assert superpaper.session.requests == []
    reported = [event for event in superpaper.ui_events if event[0] == "call_soon"]
    assert len(reported) == 1
    reported[0][1]()
    assert superpaper.ui_events[-1] == ("notify", "The saved display layout can't be used.", "Error")


def test_a_layout_problem_is_reported_again_after_the_layout_was_fine_in_between(detection):
    superpaper = application()
    superpaper._layout = FRESH
    detection.problem = "can't be used"
    superpaper.refresh_displays()
    detection.problem = None
    superpaper.refresh_displays()
    detection.problem = "can't be used"
    superpaper.refresh_displays()

    assert len([event for event in superpaper.ui_events if event[0] == "call_soon"]) == 2


def test_refreshing_the_displays_can_show_the_running_profile_again_with_them():
    superpaper = application()

    superpaper.refresh_displays(redraw=True)

    assert superpaper.session.requests == [("use_displays", FRESH), ("redraw",)]


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

    assert "Could not open the wallpaper configuration: no window" in caplog.text


def test_quitting_stops_the_session_before_the_icon_goes():
    superpaper = application()

    superpaper.quit()

    assert superpaper.session.requests == [("shutdown",), ("tray removed",), ("closed",)]


def test_quitting_is_aborted_when_the_user_keeps_unsaved_changes_open():
    superpaper = application(settle_unsaved_changes=lambda: False)

    superpaper.quit()

    assert superpaper.session.requests == []


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
def test_the_help_and_the_configuration_open_at_start_when_they_should(show_help, clickable, expected):
    opened = []
    superpaper = application(
        settings=Settings(show_help=show_help),
        open_editor=lambda app: opened.append("editor"),
        open_help=lambda app: opened.append("help"),
        call_soon=lambda action: opened.append("editor later") if action == superpaper.open_editor else None,
    )
    superpaper.tray.clickable = clickable
    superpaper.session.layout = FRESH

    superpaper._show_at_start()

    assert opened == expected


def test_problems_with_this_desktop_are_said_once_at_start():
    shown = []
    superpaper = application(
        settings=Settings(show_help=False),
        notify=lambda message, title: shown.append((message, title)),
        call_soon=lambda action: action(),
    )
    superpaper.desktop.problem = "no setter here"
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

    superpaper._run_at_startup(ProfileId.parse("Home", windows_names=False))

    assert superpaper.session.requests == [("activate", home)]


def start(monkeypatch, paths):
    """Run Superpaper's real start on ``paths``, without the session and windows."""
    monkeypatch.setattr(controller, "Session", lambda *args, **kwargs: FakeSession())
    for step in ("_run_at_startup", "_show_at_start"):
        monkeypatch.setattr(controller.Superpaper, step, lambda *args: None)
    shell = application()._shell
    return controller.Superpaper(shell, paths, FakeDesktop(), Settings(), None)


def test_a_start_sweeps_the_renders_of_profiles_that_are_gone(tmp_path, monkeypatch):
    paths = AppPaths(config=tmp_path, profiles=tmp_path / "profiles", cache=tmp_path / "cache")
    paths.profiles.mkdir()
    paths.cache.mkdir()
    (paths.profiles / "Work.profile").write_text("name=Work\n", encoding="utf-8")
    for name in ("Work-a.png", "Gone-a.png"):
        (paths.cache / name).touch()

    start(monkeypatch, paths)

    assert sorted(path.name for path in paths.cache.iterdir()) == ["Work-a.png"]


def test_a_start_that_cant_list_the_profiles_keeps_every_render(tmp_path, monkeypatch):
    paths = AppPaths(config=tmp_path, profiles=tmp_path / "profiles", cache=tmp_path / "cache")
    paths.cache.mkdir()
    (paths.cache / "Work-a.png").touch()

    start(monkeypatch, paths)

    assert [path.name for path in paths.cache.iterdir()] == ["Work-a.png"]


@pytest.mark.parametrize("startup", [None, ProfileId.parse("Missing", windows_names=False)])
def test_a_start_with_nothing_to_run_runs_nothing(startup):
    superpaper = application(profiles=[profile("Work")])

    superpaper._run_at_startup(startup)

    assert superpaper.session.requests == []


@pytest.mark.parametrize("still_saved", [True, False])
def test_reloading_tells_the_session_what_became_of_the_running_profile(still_saved):
    running = profile("Work")
    edited_elsewhere = profile("Work")
    superpaper = application(running=running, profiles=[running])
    superpaper.store.on_disk = [edited_elsewhere] if still_saved else [profile("Other")]

    superpaper.reload_profiles()

    assert superpaper.session.requests == [
        ("update", ProfileId.parse("Work", windows_names=False), edited_elsewhere if still_saved else None)
    ]


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
    superpaper.store = ProfileStore(paths, windows_names=False)

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
    superpaper.store = ProfileStore(paths, windows_names=False)

    superpaper.reload_profiles()

    assert broken.read_text(encoding="utf-8") == fixed


def test_only_profiles_that_cant_be_read_as_profiles_are_offered_for_deletion(tmp_path):
    paths = AppPaths(config=tmp_path, profiles=tmp_path / "profiles", cache=tmp_path / "cache")
    paths.profiles.mkdir()
    (paths.profiles / "cli.profile").write_text("name=cli\n", encoding="utf-8")
    (paths.profiles / "gone.profile").symlink_to(tmp_path / "missing")
    (paths.profiles / "folder.profile").mkdir()
    superpaper = application(confirm=lambda message: pytest.fail("asked to delete"))
    superpaper.store = ProfileStore(paths, windows_names=False)

    superpaper.reload_profiles()

    assert superpaper.store.profiles == []
    assert sorted(path.name for path in paths.profiles.iterdir()) == ["cli.profile", "folder.profile", "gone.profile"]


def test_saved_general_settings_apply_from_now_on(tmp_path):
    shown = []
    superpaper = application(notify=lambda message, title: shown.append((message, title)))
    superpaper.settings_path = tmp_path / "general_settings"
    saved = Settings(logging=True, set_command="setter {image}")

    superpaper.apply_settings(saved)

    assert superpaper.settings == saved
    assert read_settings(superpaper.settings_path) == saved
    assert shown == [("Logging is enabled after an application restart.", "Info")]


def test_settings_that_cant_be_written_are_reported_and_not_applied(tmp_path):
    shown = []
    superpaper = application(settings=Settings(show_help=True), notify=lambda message, title: shown.append(title))
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    superpaper.settings_path = blocker / "general_settings"

    saved = superpaper.apply_settings(Settings(show_help=False))

    assert saved is False
    assert superpaper.settings == Settings(show_help=True)
    assert shown == ["Error"]


def test_a_dialog_setting_is_written_and_kept_for_the_next_window(tmp_path):
    superpaper = application(settings=Settings(show_help=True))
    superpaper.settings_path = tmp_path / "general_settings"

    superpaper.update_settings(replace(superpaper.settings, browse_default_dir="/pictures"))
    superpaper.update_settings(replace(superpaper.settings, show_help=False))

    expected = Settings(browse_default_dir="/pictures", show_help=False)
    assert superpaper.settings == expected
    assert read_settings(superpaper.settings_path) == expected
