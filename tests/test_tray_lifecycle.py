from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from superpaper.profile_id import ProfileId


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


def controller(tray, active_profile=None, timer=None):
    icon = object.__new__(tray.TaskBarIcon)
    icon.job_lock = Lock()
    icon.active_profile = active_profile
    icon.repeating_timer = timer
    icon.list_of_profiles = []
    icon.is_paused = False
    return icon


def profile(name):
    return SimpleNamespace(name=name, profile_id=ProfileId(name), slideshow=True, delay_list=[30])


def test_start_profile_activates_and_persists(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    active = profile("active")
    replacement_timer = object()
    worker = object()
    writes = []
    monkeypatch.setattr(tray, "run_profile_job", lambda selected: (replacement_timer, worker))
    monkeypatch.setattr(tray, "write_active_profile", writes.append)
    icon = controller(tray)

    assert icon.start_profile(None, active) is worker
    assert icon.active_profile is active
    assert icon.repeating_timer is replacement_timer
    assert tray.wpproc.G_ACTIVE_PROFILE == "active"
    assert writes == [ProfileId("active")]


def test_switch_profile_stops_old_timer_first(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    events = []
    old_timer = RecordingTimer(events)
    old_profile = profile("old")
    new_profile = profile("new")

    def run(selected):
        events.append(("run", selected.name))
        return (object(), "worker")

    monkeypatch.setattr(tray, "run_profile_job", run)
    monkeypatch.setattr(tray, "write_active_profile", lambda name: events.append(("write", name)))
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
    monkeypatch.setattr(tray, "quick_profile_job", lambda selected: calls.append(("quick", selected)))
    monkeypatch.setattr(
        tray,
        "run_profile_job",
        lambda selected, startup: calls.append(("run", selected, startup)) or (timer, object()),
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
        tray, "change_wallpaper_job", lambda selected, advance: events.append(("change", selected, advance))
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
    assert run.call_args == call(active, startup=True)


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
    monkeypatch.setattr(tray, "list_profiles", lambda: [profile("other")])

    icon.reload_profiles(None)

    assert icon.active_profile is None
    assert icon.repeating_timer is None
    assert tray.wpproc.G_ACTIVE_PROFILE is None
    assert events == (["stop"] if timer_running else [])


@pytest.mark.xfail(strict=True, reason="Known timer bug: rearming an active profile does not preserve pause state")
def test_rearm_preserves_paused_state(headless_tray_module, monkeypatch):
    tray = headless_tray_module
    active = profile("active")
    replacement = RecordingTimer([])
    monkeypatch.setattr(tray, "run_profile_job", lambda selected, startup: (replacement, None))
    icon = controller(tray, active, RecordingTimer([], running=False))
    icon.is_paused = True

    icon.rearm_active_timer()

    assert icon.is_paused is True
    assert replacement.is_running is False
