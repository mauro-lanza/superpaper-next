from threading import Event, Thread
from types import SimpleNamespace

import pytest


def monitor(width, height, x=0, y=0, width_mm=500, height_mm=300, name="display"):
    return SimpleNamespace(
        width=width,
        height=height,
        x=x,
        y=y,
        width_mm=width_mm,
        height_mm=height_mm,
        name=name,
    )


def test_display_detection_retries_empty_results(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    results = iter([[], [], [monitor(1920, 1080)]])
    sleeps = []
    monkeypatch.setattr(wpproc, "get_monitors", lambda: next(results))
    monkeypatch.setattr(wpproc.time, "sleep", sleeps.append)

    displays = wpproc.get_display_data(max_attempts=3, retry_delay=0.1, update_globals=True)

    assert len(displays) == 1
    assert sleeps == [0.1, 0.1]
    assert wpproc.RESOLUTION_ARRAY == [(1920, 1080)]


def test_display_detection_retries_exceptions(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    error = RuntimeError("backend unavailable")
    results = iter([error, [monitor(1920, 1080)]])

    def get_result():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(wpproc, "get_monitors", get_result)
    monkeypatch.setattr(wpproc.time, "sleep", lambda _delay: None)

    assert len(wpproc.get_display_data(max_attempts=2, retry_delay=0)) == 1


def test_detection_failure_preserves_globals(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    resolutions = wpproc.RESOLUTION_ARRAY
    offsets = wpproc.DISPLAY_OFFSET_ARRAY
    active = object()
    monkeypatch.setattr(wpproc, "G_ACTIVE_DISPLAYSYSTEM", active)
    monkeypatch.setattr(wpproc, "get_monitors", list)
    monkeypatch.setattr(wpproc.time, "sleep", lambda _delay: None)

    with pytest.raises(wpproc.DisplayDetectionError):
        wpproc.refresh_display_data(max_attempts=2, retry_delay=0)

    assert wpproc.NUM_DISPLAYS == 2
    assert wpproc.RESOLUTION_ARRAY is resolutions
    assert wpproc.DISPLAY_OFFSET_ARRAY is offsets
    assert wpproc.G_ACTIVE_DISPLAYSYSTEM is active


def test_late_refresh_failure_preserves_globals(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    resolutions = wpproc.RESOLUTION_ARRAY
    offsets = wpproc.DISPLAY_OFFSET_ARRAY
    active = object()
    monkeypatch.setattr(wpproc, "G_ACTIVE_DISPLAYSYSTEM", active)
    monkeypatch.setattr(wpproc, "get_monitors", lambda: [monitor(2560, 1440)])
    monkeypatch.setattr(
        wpproc.DisplaySystem, "load_system", lambda _self: (_ for _ in ()).throw(ValueError("bad config"))
    )

    with pytest.raises(ValueError, match="bad config"):
        wpproc.refresh_display_data(retry_delay=0)

    assert wpproc.NUM_DISPLAYS == 2
    assert wpproc.RESOLUTION_ARRAY is resolutions
    assert wpproc.DISPLAY_OFFSET_ARRAY is offsets
    assert wpproc.G_ACTIVE_DISPLAYSYSTEM is active


def test_direct_display_system_failure_preserves_globals(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    resolutions = wpproc.RESOLUTION_ARRAY
    offsets = wpproc.DISPLAY_OFFSET_ARRAY
    monkeypatch.setattr(wpproc, "get_monitors", lambda: [monitor(2560, 1440)])
    monkeypatch.setattr(
        wpproc.DisplaySystem, "load_system", lambda _self: (_ for _ in ()).throw(ValueError("bad config"))
    )

    with pytest.raises(ValueError, match="bad config"):
        wpproc.DisplaySystem(retry_delay=0)

    assert wpproc.NUM_DISPLAYS == 2
    assert wpproc.RESOLUTION_ARRAY is resolutions
    assert wpproc.DISPLAY_OFFSET_ARRAY is offsets


def test_direct_display_system_success_publishes_active_generation(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    monkeypatch.setattr(wpproc, "get_monitors", lambda: [monitor(2560, 1440)])
    monkeypatch.setattr(wpproc.DisplaySystem, "load_system", lambda _self: None)
    monkeypatch.setattr(wpproc.DisplaySystem, "load_perspectives", lambda _self: None)

    display_system = wpproc.DisplaySystem(retry_delay=0)

    assert display_system is wpproc.G_ACTIVE_DISPLAYSYSTEM
    assert wpproc.NUM_DISPLAYS == 1
    assert wpproc.RESOLUTION_ARRAY == [(2560, 1440)]


def test_successful_refresh_commits_coherent_state(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    monitors = [monitor(1280, 1024, x=0), monitor(1920, 1080, x=-1920)]
    monkeypatch.setattr(wpproc, "get_monitors", lambda: monitors)
    monkeypatch.setattr(wpproc.DisplaySystem, "load_system", lambda _self: None)
    monkeypatch.setattr(wpproc.DisplaySystem, "load_perspectives", lambda _self: None)

    display_system = wpproc.refresh_display_data(retry_delay=0)

    assert display_system is wpproc.G_ACTIVE_DISPLAYSYSTEM
    assert wpproc.NUM_DISPLAYS == 2
    assert wpproc.RESOLUTION_ARRAY == [(1920, 1080), (1280, 1024)]
    assert wpproc.DISPLAY_OFFSET_ARRAY == [(0, 0), (1920, 0)]


def test_refresh_waits_for_active_render(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    render_started = Event()
    release_render = Event()

    class Profile:
        name = "test"
        spanmode = "single"
        ppimode = False

        @staticmethod
        def has_valid_selection():
            return True

    def render(_profile, _force):
        render_started.set()
        release_render.wait(timeout=1)

    monkeypatch.setattr(wpproc, "span_single_image_simple", render)
    render_thread = wpproc.change_wallpaper_job(Profile())
    assert render_started.wait(timeout=1)

    publish_finished = Event()

    def publish():
        wpproc.update_display_globals([])
        publish_finished.set()

    publish_thread = Thread(target=publish)
    publish_thread.start()
    assert not publish_finished.wait(timeout=0.05)
    release_render.set()
    render_thread.join(timeout=1)
    publish_thread.join(timeout=1)

    assert publish_finished.is_set()


def test_wallpaper_changes_do_not_queue(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    render_started = Event()
    release_render = Event()

    class Profile:
        name = "test"
        spanmode = "single"
        ppimode = False

        @staticmethod
        def has_valid_selection():
            return True

    def render(_profile, _force):
        render_started.set()
        release_render.wait(timeout=1)

    monkeypatch.setattr(wpproc, "span_single_image_simple", render)
    first = wpproc.change_wallpaper_job(Profile())
    assert render_started.wait(timeout=1)

    assert wpproc.change_wallpaper_job(Profile(), advance=True, skip_if_busy=True) is None
    release_render.set()
    first.join(timeout=1)


@pytest.mark.parametrize("kwargs", [{"max_attempts": 0}, {"retry_delay": -1}])
def test_display_detection_rejects_invalid_retry_options(profile_modules, kwargs):
    _, wpproc = profile_modules

    with pytest.raises(ValueError):
        wpproc.get_display_data(**kwargs)
