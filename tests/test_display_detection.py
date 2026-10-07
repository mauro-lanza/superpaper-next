from threading import Event
from types import SimpleNamespace

import pytest

from tests.conftest import monitor


def test_display_detection_retries_empty_results(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    results = iter([[], [], [monitor(0, 0, 1920, 1080)]])
    sleeps = []
    monkeypatch.setattr(wpproc, "get_monitors", lambda: next(results))
    monkeypatch.setattr(wpproc.time, "sleep", sleeps.append)

    displays = wpproc.get_display_data(max_attempts=3, retry_delay=0.1)

    assert [display.resolution for display in displays] == [(1920, 1080)]
    assert sleeps == [0.1, 0.1]


def test_display_detection_retries_exceptions(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    error = RuntimeError("backend unavailable")
    results = iter([error, [monitor(0, 0, 1920, 1080)]])

    def get_result():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(wpproc, "get_monitors", get_result)
    monkeypatch.setattr(wpproc.time, "sleep", lambda _delay: None)

    assert len(wpproc.get_display_data(max_attempts=2, retry_delay=0)) == 1


def test_a_layout_needs_at_least_one_display(profile_modules, monkeypatch, tmp_path):
    _, wpproc = profile_modules
    monkeypatch.setattr(wpproc, "get_monitors", list)
    monkeypatch.setattr(wpproc.time, "sleep", lambda _delay: None)

    with pytest.raises(wpproc.DisplayDetectionError):
        wpproc.DisplaySystem(tmp_path, max_attempts=2, retry_delay=0)


def test_an_unreadable_saved_layout_is_an_error(profile_modules, monkeypatch, tmp_path):
    _, wpproc = profile_modules
    monkeypatch.setattr(wpproc, "get_monitors", lambda: [monitor(0, 0, 2560, 1440)])
    monkeypatch.setattr(
        wpproc.DisplaySystem, "load_system", lambda _self: (_ for _ in ()).throw(ValueError("bad config"))
    )

    with pytest.raises(ValueError, match="bad config"):
        wpproc.DisplaySystem(tmp_path, retry_delay=0)


def test_a_layout_lists_displays_in_desktop_order(profile_modules, display_layout):
    _, wpproc = profile_modules

    # A display to the left of the primary one has a negative position.
    layout = display_layout([monitor(0, 0, 1280, 1024), monitor(-1920, 0, 1920, 1080)])

    assert layout.resolutions() == [(1920, 1080), (1280, 1024)]
    assert layout.digital_offsets() == [(0, 0), (1920, 0)]


class SingleImageProfile:
    name = "test"
    spanmode = "single"

    @staticmethod
    def has_valid_selection():
        return True

    @staticmethod
    def display_corrections(_resolutions):
        return SimpleNamespace(ppimode=False)


def blocking_render(monkeypatch, wpproc):
    """Make the simple renderer wait until released; return (started, release)."""
    started = Event()
    release = Event()

    def render(_profile, _force, **_kwargs):
        started.set()
        release.wait(timeout=1)

    monkeypatch.setattr(wpproc, "span_single_image_simple", render)
    return started, release


def test_detecting_displays_does_not_wait_for_a_render(profile_modules, monkeypatch, app_paths, display_layout):
    _, wpproc = profile_modules
    started, release = blocking_render(monkeypatch, wpproc)
    render = wpproc.change_wallpaper_job(SingleImageProfile(), app_paths, display_system=display_layout())
    assert started.wait(timeout=1)

    # A render keeps the layout it was given, so a new one can be made meanwhile.
    refreshed = display_layout([monitor(0, 0, 2560, 1440)])

    assert render.is_alive()
    assert refreshed.resolutions() == [(2560, 1440)]
    release.set()
    render.join(timeout=1)


def test_wallpaper_changes_do_not_queue(profile_modules, monkeypatch, app_paths, display_layout):
    _, wpproc = profile_modules
    started, release = blocking_render(monkeypatch, wpproc)
    layout = display_layout()
    first = wpproc.change_wallpaper_job(SingleImageProfile(), app_paths, display_system=layout)
    assert started.wait(timeout=1)

    skipped = wpproc.change_wallpaper_job(
        SingleImageProfile(), app_paths, display_system=layout, advance=True, skip_if_busy=True
    )

    assert skipped is None
    release.set()
    first.join(timeout=1)


@pytest.mark.parametrize("kwargs", [{"max_attempts": 0}, {"retry_delay": -1}])
def test_display_detection_rejects_invalid_retry_options(profile_modules, kwargs):
    _, wpproc = profile_modules

    with pytest.raises(ValueError):
        wpproc.get_display_data(**kwargs)
