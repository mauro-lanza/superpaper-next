from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from superpaper.paths import AppPaths
from superpaper.profile_id import ProfileId
from superpaper.settings import Settings


class RecordingTimer:
    def __init__(self, events, running=True):
        self.events = events
        self.is_running = running

    def start(self):
        self.events.append("start")
        self.is_running = True

    def stop(self):
        self.events.append("stop")
        self.is_running = False


PATHS = AppPaths(config=Path("/config"), profiles=Path("/config/profiles"), cache=Path("/cache"))


def controller(tray, active_profile=None, timer=None):
    icon = object.__new__(tray.TaskBarIcon)
    icon.paths = PATHS
    icon.g_settings = Settings()
    icon.refresh_displays = lambda: None
    icon.job_lock = Lock()
    icon.active_profile = active_profile
    icon.repeating_timer = timer
    icon.list_of_profiles = []
    icon.is_paused = False
    icon.hk2 = None
    icon.seen_binding = set()
    return icon


def profile(name):
    return SimpleNamespace(name=name, profile_id=ProfileId(name), slideshow=True, delay_list=[30])


def test_start_profile_activates_and_persists(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    active = profile("active")
    replacement_timer = object()
    worker = object()
    writes = []
    monkeypatch.setattr(tray, "run_profile_job", lambda selected, change, startup: (replacement_timer, worker))
    monkeypatch.setattr(
        tray, "write_active_profile", lambda cache_dir, profile_id: writes.append((cache_dir, profile_id))
    )
    icon = controller(tray)

    assert icon.start_profile(None, active) is worker
    assert icon.active_profile is active
    assert icon.repeating_timer is replacement_timer
    assert tray.wpproc.G_ACTIVE_PROFILE == "active"
    assert writes == [(PATHS.cache, ProfileId("active"))]


def test_switch_profile_stops_old_timer_first(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    events = []
    old_timer = RecordingTimer(events)
    old_profile = profile("old")
    new_profile = profile("new")

    def run(selected, change, startup):
        events.append(("run", selected.name))
        return (object(), "worker")

    monkeypatch.setattr(tray, "run_profile_job", run)
    monkeypatch.setattr(tray, "write_active_profile", lambda cache_dir, name: events.append(("write", name)))
    icon = controller(tray, old_profile, old_timer)

    assert icon.start_profile(None, new_profile) == "worker"
    assert events == ["stop", ("run", "new"), ("write", ProfileId("new"))]


def test_selecting_active_profile_means_next(headless_tray_module):
    tray = headless_tray_module
    active = profile("active")
    icon = controller(tray, active)
    icon.next_wallpaper = Mock()
    event = object()

    assert icon.start_profile(event, active) == 0
    icon.next_wallpaper.assert_called_once_with(event)


def test_start_previous_profile_restore_and_explicit_apply(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    active = profile("active")
    calls = []
    timer = object()
    monkeypatch.setattr(tray, "quick_profile_job", lambda selected, **kwargs: calls.append(("quick", selected)))
    monkeypatch.setattr(
        tray,
        "run_profile_job",
        lambda selected, change, startup: calls.append(("run", selected, startup)) or (timer, object()),
    )
    icon = controller(tray)

    icon.start_prev_profile(active, apply_now=False)
    assert calls == [("quick", active), ("run", active, True)]
    assert icon.repeating_timer is timer

    calls.clear()
    icon.start_prev_profile(active, apply_now=True)
    assert calls == [("run", active, False)]


def test_manual_next_stops_and_restarts_running_timer(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    events = []
    timer = RecordingTimer(events)
    active = profile("active")
    monkeypatch.setattr(
        tray,
        "change_wallpaper_job",
        lambda selected, paths, **options: events.append(("change", selected, options["advance"])),
    )
    icon = controller(tray, active, timer)

    icon.next_wallpaper(None)

    assert events == ["stop", ("change", active, True), "start"]


def test_pause_and_resume_timer(headless_tray_module):
    tray = headless_tray_module
    events = []
    timer = RecordingTimer(events)
    icon = controller(tray, profile("active"), timer)

    icon.pause_timer(None)
    assert events == ["stop"]
    assert icon.is_paused is True

    icon.pause_timer(None)
    assert events == ["stop", "start"]
    assert icon.is_paused is False


def test_rearm_replaces_running_timer_without_rendering(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    events = []
    active = profile("renamed")
    old_timer = RecordingTimer(events)
    new_timer = object()
    run = Mock(return_value=(new_timer, None))
    monkeypatch.setattr(tray, "run_profile_job", run)
    icon = controller(tray, active, old_timer)

    icon.rearm_active_timer()

    assert events == ["stop"]
    assert icon.repeating_timer is new_timer
    assert tray.wpproc.G_ACTIVE_PROFILE == "renamed"
    assert run.call_args == call(active, icon.change_wallpaper, startup=True)


@pytest.mark.parametrize(
    "raw",
    [ProfileId("Work"), "Work", "/outside/profiles/Work.profile", r"C:\outside\Work.profile"],
)
def test_startup_profile_compatibility_extracts_identity_only(headless_tray_module, raw):
    assert headless_tray_module._startup_profile_id(raw) == ProfileId("Work")


def test_startup_outside_path_cannot_select_by_path(headless_tray_module):
    tray = headless_tray_module
    managed = profile("Work")
    icon = controller(tray)
    icon.list_of_profiles = [managed]

    startup_id = tray._startup_profile_id("/outside/not-the-managed-file/Work.profile")

    assert icon.get_profile_by_id(startup_id) is managed
    assert tray._startup_profile_id("/outside/Other.profile") == ProfileId("Other")
    assert icon.get_profile_by_id(ProfileId("Other")) is None


@pytest.mark.parametrize("timer_running", [True, False])
def test_reload_clears_active_profile_missing_from_inventory(headless_tray_module, monkeypatch, timer_running):
    tray = headless_tray_module
    events = []
    timer = RecordingTimer(events, running=timer_running)
    icon = controller(tray, profile("removed"), timer)
    tray.wpproc.G_ACTIVE_PROFILE = "removed"
    monkeypatch.setattr(tray, "list_profiles", lambda paths: [profile("other")])

    icon.reload_profiles(None)

    assert icon.active_profile is None
    assert icon.repeating_timer is None
    assert tray.wpproc.G_ACTIVE_PROFILE is None
    assert events == (["stop"] if timer_running else [])


def test_rearm_preserves_paused_state(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    active = profile("active")
    replacement = RecordingTimer([])
    monkeypatch.setattr(tray, "run_profile_job", lambda selected, change, startup: (replacement, None))
    icon = controller(tray, active, RecordingTimer([], running=False))
    icon.is_paused = True

    icon.rearm_active_timer()

    assert icon.is_paused is True
    assert replacement.is_running is False


def test_profile_hotkey_starts_the_currently_loaded_profile(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    stale = profile("Work")
    current = profile("Work")
    started = []
    icon = controller(tray)
    icon.list_of_profiles = [current]
    monkeypatch.setattr(icon, "start_profile", lambda event, selected: started.append(selected))

    # system_hotkey hands the consumer the arguments the binding was registered with.
    icon.profile_consumer(None, ("control", "w"), [(stale.profile_id,)])

    assert started == [current]


def test_hotkey_for_a_deleted_profile_does_nothing(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    started = []
    icon = controller(tray)
    monkeypatch.setattr(icon, "start_profile", lambda event, selected: started.append(selected))

    icon.profile_consumer(None, ("control", "w"), [(ProfileId("Deleted"),)])

    assert started == []


def test_profile_hotkey_changes_are_ignored_while_hotkeys_are_disabled(headless_tray_module):
    icon = controller(headless_tray_module)

    icon.update_hotkey("Work", ("control", "x"), "control+y")

    assert icon.seen_binding == set()


def test_profile_hotkey_change_rebinds_by_identity(headless_tray_module):
    icon = controller(headless_tray_module)
    icon.hk2 = Mock()
    icon.seen_binding = {("control", "x")}

    icon.update_hotkey("Work", ("control", "x"), "control+y")

    icon.hk2.unregister.assert_called_once_with(("control", "x"))
    icon.hk2.register.assert_called_once_with(("control", "y"), ProfileId("Work"), overwrite=False)
    assert icon.seen_binding == {("control", "y")}


def test_removing_a_profile_hotkey_unbinds_it(headless_tray_module):
    icon = controller(headless_tray_module)
    icon.hk2 = Mock()
    icon.seen_binding = {("control", "x")}

    icon.update_hotkey("Work", ("control", "x"), "")

    icon.hk2.unregister.assert_called_once_with(("control", "x"))
    icon.hk2.register.assert_not_called()
    assert icon.seen_binding == set()


def test_profiles_start_on_freshly_detected_displays(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    events = []
    monkeypatch.setattr(tray, "run_profile_job", lambda selected, change, startup: events.append("run") or (None, None))
    monkeypatch.setattr(tray, "write_active_profile", lambda cache_dir, profile_id: None)
    icon = controller(tray)
    icon.refresh_displays = lambda: events.append("refresh")

    icon.start_profile(None, profile("active"))

    assert events == ["refresh", "run"]


def test_wallpaper_changes_use_the_settings_current_at_the_time(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    changes = []
    monkeypatch.setattr(
        tray, "change_wallpaper_job", lambda selected, paths, **options: changes.append((paths, options["set_command"]))
    )
    icon = controller(tray)
    icon.g_settings = Settings(set_command="first {image}")
    icon.change_wallpaper(profile("active"), advance=True, skip_if_busy=True)

    # A slideshow tick after the custom command was changed in Settings uses the new one.
    icon.g_settings = Settings(set_command="second {image}")
    icon.change_wallpaper(profile("active"), advance=True, skip_if_busy=True)

    assert changes == [(PATHS, "first {image}"), (PATHS, "second {image}")]
