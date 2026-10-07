import configparser
from threading import Event
from types import SimpleNamespace

import pytest

from superpaper import display_store, displays
from superpaper.profile_id import ProfileId
from tests.conftest import monitor


def test_display_detection_retries_empty_results(monkeypatch):
    results = iter([[], [], [monitor(0, 0, 1920, 1080)]])
    sleeps = []
    monkeypatch.setattr(displays, "get_monitors", lambda: next(results))
    monkeypatch.setattr(displays.time, "sleep", sleeps.append)

    detected = displays.get_display_data(max_attempts=3, retry_delay=0.1)

    assert [display.resolution for display in detected] == [(1920, 1080)]
    assert sleeps == [0.1, 0.1]


def test_display_detection_retries_exceptions(monkeypatch):
    error = RuntimeError("backend unavailable")
    results = iter([error, [monitor(0, 0, 1920, 1080)]])

    def get_result():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(displays, "get_monitors", get_result)
    monkeypatch.setattr(displays.time, "sleep", lambda _delay: None)

    assert len(displays.get_display_data(max_attempts=2, retry_delay=0)) == 1


def test_a_layout_needs_at_least_one_display(monkeypatch, tmp_path):
    monkeypatch.setattr(displays, "get_monitors", list)
    monkeypatch.setattr(displays.time, "sleep", lambda _delay: None)

    with pytest.raises(displays.DisplayDetectionError):
        displays.DisplaySystem(tmp_path, max_attempts=2, retry_delay=0)


def test_an_unreadable_saved_layout_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(displays, "get_monitors", lambda: [monitor(0, 0, 2560, 1440)])
    (tmp_path / "display_systems.dat").write_text("not a layout\n", encoding="utf-8")

    with pytest.raises(configparser.Error):
        displays.DisplaySystem(tmp_path, retry_delay=0)


def test_a_layout_lists_displays_in_desktop_order(display_layout):
    # A display to the left of the primary one has a negative position.
    layout = display_layout([monitor(0, 0, 1280, 1024), monitor(-1920, 0, 1920, 1080)])

    assert layout.resolutions() == [(1920, 1080), (1280, 1024)]
    assert layout.digital_offsets() == [(0, 0), (1920, 0)]


def test_an_undetected_display_size_is_hinted_until_a_diagonal_is_entered(display_layout):
    layout = display_layout([monitor(0, 0, 1920, 1080, None, None)])

    assert layout.size_hint() == displays.SIZE_HINT
    layout.update_display_diags([15.6])
    assert layout.size_hint() is None
    assert display_layout().size_hint() is None


def test_bezels_cant_be_negative(display_layout):
    with pytest.raises(ValueError, match="negative"):
        display_layout().update_bezels([(-1.0, 0.0), (0.0, 0.0)])


def test_negative_saved_bezels_are_ignored(display_layout, tmp_path, caplog):
    key = display_layout(config_dir=tmp_path).key
    saved = display_store.SavedLayout([(0, 0), (2000, 0)], [(-3.0, 0.0), (0.0, 0.0)], None, True, None)
    display_store.write_layout(tmp_path, key, saved)

    layout = display_layout(config_dir=tmp_path)

    assert layout.bezels_in_mm() == [(0.0, 0.0), (0.0, 0.0)]
    assert layout.get_ppinorm_offsets() == [(0, 0), (2000, 0)]
    assert "Ignoring the saved bezels" in caplog.text


class SingleImageProfile:
    name = "test"
    profile_id = ProfileId("test")
    spanmode = "single"
    zoom = 1.0
    offsets = (0.0, 0.0)

    @staticmethod
    def has_valid_selection():
        return True

    @staticmethod
    def next_wallpaper_files():
        return ["image.png"]

    @staticmethod
    def display_corrections(_resolutions):
        return SimpleNamespace(ppimode=False)


def blocking_render(monkeypatch, wpproc):
    """Make the running profile's render wait until released; return (started, release)."""
    started = Event()
    release = Event()

    def render(_source, _layout, **_options):
        started.set()
        release.wait(timeout=1)

    monkeypatch.setattr(wpproc, "G_ACTIVE_PROFILE", SingleImageProfile.name)
    monkeypatch.setattr(wpproc.render, "simple", render)
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
def test_display_detection_rejects_invalid_retry_options(kwargs):
    with pytest.raises(ValueError):
        displays.get_display_data(**kwargs)
