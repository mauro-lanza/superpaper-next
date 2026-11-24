import threading

import pytest

from superpaper.geometry import display_detection, display_store
from tests.conftest import monitor
from tests.desktop.fake import FakeDesktop
from tests.geometry.conftest import (
    DUAL_KEY,
    DUAL_MONITORS,
    LAPTOP_KEY,
    LAPTOP_MONITORS,
    OVERLAPPING_DAT,
    OVERLAPPING_KEY,
    OVERLAPPING_MONITORS,
    detect,
)


def test_display_detection_retries_empty_results(monkeypatch, desktop):
    results = iter([[], [], [monitor(0, 0, 1920, 1080)]])
    sleeps = []
    desktop.detect_monitors = lambda: next(results)
    monkeypatch.setattr(display_detection.time, "sleep", sleeps.append)

    detected = display_detection.detect_displays(desktop)

    assert [display.resolution for display in detected] == [(1920, 1080)]
    assert sleeps == [display_detection.RETRY_DELAY_SECONDS] * 2


def test_display_detection_retries_exceptions(monkeypatch, desktop):
    error = RuntimeError("backend unavailable")
    results = iter([error, [monitor(0, 0, 1920, 1080)]])

    def get_result():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    desktop.detect_monitors = get_result
    monkeypatch.setattr(display_detection.time, "sleep", lambda _delay: None)

    assert len(display_detection.detect_displays(desktop)) == 1


@pytest.mark.parametrize(
    ("width", "height", "width_mm", "height_mm", "failed", "size_mm"),
    [
        (1080, 1920, 269, 290, True, (286, 509)),
        (1080, 1920, 195, 345, False, (195, 345)),
        (1920, 1080, 345, 195, False, (345, 195)),
        (1920, 1080, 195, 345, False, (345, 195)),
        (1920, 1200, 330, 190, False, (330, 190)),
        (1920, 1080, 0, 300, True, (509, 286)),
        (1920, 1080, None, None, True, (509, 286)),
    ],
)
def test_a_size_inconsistent_with_the_pixels_is_unknown(desktop, width, height, width_mm, height_mm, failed, size_mm):
    desktop.monitors = [monitor(0, 0, width, height, width_mm, height_mm)]

    (display,) = display_detection.detect_displays(desktop)

    assert display.phys_size_failed is failed
    assert display.detected_phys_size_mm == size_mm


def test_detection_gives_up_after_the_last_attempt_without_displays(monkeypatch, desktop):
    monkeypatch.setattr(display_detection.time, "sleep", lambda _delay: None)

    with pytest.raises(display_detection.DisplayDetectionError) as raised:
        display_detection.detect_displays(desktop)

    assert raised.value.__cause__ is None


def test_an_earlier_error_is_not_blamed_when_the_last_attempt_is_empty(monkeypatch, desktop):
    results = iter([RuntimeError("backend unavailable"), [], []])

    def get_result():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    desktop.detect_monitors = get_result
    monkeypatch.setattr(display_detection.time, "sleep", lambda _delay: None)

    with pytest.raises(display_detection.DisplayDetectionError) as raised:
        display_detection.detect_displays(desktop)

    assert raised.value.__cause__ is None


def test_the_error_of_the_last_attempt_is_the_cause_of_giving_up(monkeypatch, desktop):
    error = RuntimeError("backend unavailable")

    def fail():
        raise error

    desktop.detect_monitors = fail
    monkeypatch.setattr(display_detection.time, "sleep", lambda _delay: None)

    with pytest.raises(display_detection.DisplayDetectionError) as raised:
        display_detection.detect_displays(desktop)

    assert raised.value.__cause__ is error


def test_an_unreadable_saved_layout_gives_the_default_arrangement_to_the_app(monkeypatch, tmp_path, desktop):
    desktop.monitors = [monitor(0, 0, 2560, 1440)]
    monkeypatch.setattr(display_detection.time, "sleep", lambda _delay: None)
    (tmp_path / "display_systems.dat").write_text("not a layout\n", encoding="utf-8")

    loaded = display_detection.detect_layout_or_default(tmp_path, desktop)

    assert loaded.layout.ppi_norm_offsets == ((0, 0),)
    assert loaded.problem is not None
    assert (tmp_path / "display_systems.dat").read_text(encoding="utf-8") == "not a layout\n"


def test_the_saved_layout_of_a_portable_typed_as_15_inch_overlaps_and_is_not_kept(tmp_path):
    (tmp_path / "display_systems.dat").write_text(OVERLAPPING_DAT, encoding="utf-8")
    desktop = FakeDesktop()
    desktop.monitors = OVERLAPPING_MONITORS

    loaded = display_detection.detect_layout_or_default(tmp_path, desktop)

    assert loaded.layout.key == OVERLAPPING_KEY
    assert loaded.problem is not None
    assert loaded.layout.is_valid()
    assert loaded.layout.uses_user_diagonals is False
    assert (tmp_path / "display_systems.dat").read_text(encoding="utf-8") == OVERLAPPING_DAT
    with pytest.raises(ValueError, match="overlap"):
        display_store.load(tmp_path, display_detection.detect_displays(desktop))


def test_displays_are_detected_only_on_the_main_thread(desktop):
    # libXrandr corrupts memory when two threads use it at once.
    desktop.detect_monitors = lambda: pytest.fail("detected off the main thread")
    errors = []

    def detect():
        try:
            display_detection.detect_displays(desktop)
        except RuntimeError as error:
            errors.append(str(error))

    worker = threading.Thread(target=detect)
    worker.start()
    worker.join(10)

    assert errors == ["Displays can only be detected on the main thread."]


@pytest.mark.parametrize(("monitors", "key"), [(DUAL_MONITORS, DUAL_KEY), (LAPTOP_MONITORS, LAPTOP_KEY)])
def test_the_key_of_a_monitor_set_never_changes(tmp_path, monitors, key):
    layout = detect(tmp_path, monitors)

    assert layout.key == key


def test_the_key_ignores_monitor_names_and_order(tmp_path):
    renamed = [monitor(m.x, m.y, m.width, m.height, m.width_mm, m.height_mm, "renamed") for m in DUAL_MONITORS]

    assert detect(tmp_path, renamed[::-1]).key == DUAL_KEY
