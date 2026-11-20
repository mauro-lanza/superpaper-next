import configparser
import threading

import pytest

from superpaper.geometry import display_detection, display_store
from tests.conftest import monitor
from tests.geometry.conftest import (
    DUAL_KEY,
    DUAL_MONITORS,
    LAPTOP_KEY,
    LAPTOP_MONITORS,
    SAVED_COUCH,
    SAVED_DESK,
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


def test_a_layout_needs_at_least_one_display(monkeypatch, tmp_path, desktop):
    monkeypatch.setattr(display_detection.time, "sleep", lambda _delay: None)

    with pytest.raises(display_detection.DisplayDetectionError):
        display_detection.detect_layout(tmp_path, desktop)


def test_an_unreadable_saved_layout_is_an_error(monkeypatch, tmp_path, desktop):
    desktop.monitors = [monitor(0, 0, 2560, 1440)]
    monkeypatch.setattr(display_detection.time, "sleep", lambda _delay: None)
    (tmp_path / "display_systems.dat").write_text("not a layout\n", encoding="utf-8")

    with pytest.raises(configparser.Error):
        display_detection.detect_layout(tmp_path, desktop)


def test_negative_saved_bezels_are_ignored(display_layout, tmp_path, caplog):
    key = display_layout(config_dir=tmp_path).key
    (tmp_path / display_store.LAYOUTS_FILE).write_text(
        f"[{key}]\n"
        "ppi_norm_offsets = 0,0;2000,0\n"
        "bezel_mms = -3.0,0.0;0.0,0.0\n"
        "user_diagonal_inches = None\n"
        "use_perspective = 1\n"
        "def_perspective = None\n",
        encoding="utf-8",
    )

    layout = display_layout(config_dir=tmp_path)

    assert layout.bezels_in_mm() == [(0.0, 0.0), (0.0, 0.0)]
    assert layout.ppi_norm_offsets == ((0, 0), (2000, 0))
    assert "Ignoring the saved bezels" in caplog.text


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
def test_the_key_of_a_monitor_set_never_changes(monkeypatch, tmp_path, monitors, key):
    layout = detect(monkeypatch, tmp_path, monitors)

    assert str(hash(layout.displays)) == key
    assert layout.key == key


def test_the_key_ignores_monitor_names_and_order(monkeypatch, tmp_path):
    renamed = [monitor(m.x, m.y, m.width, m.height, m.width_mm, m.height_mm, "renamed") for m in DUAL_MONITORS]

    assert detect(monkeypatch, tmp_path, renamed[::-1]).key == DUAL_KEY


def test_a_saved_layout_loads(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)

    assert layout.ppi_norm_offsets == ((0, 0), (2605.7204000891693, 98.49418762870297))
    assert layout.bezels_in_mm() == [(10.5, 0.0), (0.0, 0.0)]
    assert layout.uses_user_diagonals is True
    assert layout.diagonal_inches() == [27.0, 23.8]
    assert [display.detected_phys_size_mm for display in layout.displays] == [(597, 336), (527, 296)]
    assert layout.ppi_norm_resolutions() == [(2560, 1440), (2257, 1269)]
    assert layout.ppi_norm_crops([(0, 0), (0, 0)]) == [(0, 0, 2560, 1440), (2606, 98, 4863, 1367)]
    assert layout.use_perspective is True
    assert layout.default_perspective == "desk"
    assert layout.perspectives == (SAVED_DESK, SAVED_COUCH)


def test_the_laptop_layout_loads_with_its_diagonal_override(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, LAPTOP_MONITORS)

    (laptop,) = layout.displays
    assert laptop.phys_size_failed is True
    assert laptop.detected_phys_size_mm == (509, 286)
    assert layout.diagonal_inches() == [15.6]
    assert layout.default_perspective is None
    assert layout.perspectives == ()


def test_monitors_without_a_saved_layout_get_a_guessed_one(monkeypatch, saved_layouts):
    moved = [DUAL_MONITORS[0], monitor(0, 1440, 1920, 1080, 527, 296, "HDMI-A-1")]

    layout = detect(monkeypatch, saved_layouts, moved)

    assert layout.key not in {DUAL_KEY, LAPTOP_KEY}
    assert layout.uses_user_diagonals is False
    assert layout.bezels_in_mm() == [(0.0, 0.0), (0.0, 0.0)]
    assert layout.ppi_norm_offsets == ((0, 0), (150, 1440))
    assert layout.default_perspective is None
    assert layout.perspectives == ()
