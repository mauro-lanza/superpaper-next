import configparser
import threading

import pytest

from superpaper.geometry import display_detection, display_store, displays
from tests.conftest import monitor


def test_display_detection_retries_empty_results(monkeypatch):
    results = iter([[], [], [monitor(0, 0, 1920, 1080)]])
    sleeps = []
    monkeypatch.setattr(display_detection, "get_monitors", lambda: next(results))
    monkeypatch.setattr(display_detection.time, "sleep", sleeps.append)

    detected = display_detection.detect_displays()

    assert [display.resolution for display in detected] == [(1920, 1080)]
    assert sleeps == [display_detection.RETRY_DELAY_SECONDS] * 2


def test_display_detection_retries_exceptions(monkeypatch):
    error = RuntimeError("backend unavailable")
    results = iter([error, [monitor(0, 0, 1920, 1080)]])

    def get_result():
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(display_detection, "get_monitors", get_result)
    monkeypatch.setattr(display_detection.time, "sleep", lambda _delay: None)

    assert len(display_detection.detect_displays()) == 1


def test_a_layout_needs_at_least_one_display(monkeypatch, tmp_path):
    monkeypatch.setattr(display_detection, "get_monitors", list)
    monkeypatch.setattr(display_detection.time, "sleep", lambda _delay: None)

    with pytest.raises(display_detection.DisplayDetectionError):
        display_detection.detect_layout(tmp_path)


def test_an_unreadable_saved_layout_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(display_detection, "get_monitors", lambda: [monitor(0, 0, 2560, 1440)])
    monkeypatch.setattr(display_detection.time, "sleep", lambda _delay: None)
    (tmp_path / "display_systems.dat").write_text("not a layout\n", encoding="utf-8")

    with pytest.raises(configparser.Error):
        display_detection.detect_layout(tmp_path)


def test_a_layout_lists_displays_in_desktop_order(display_layout):
    # A display to the left of the primary one has a negative position.
    layout = display_layout([monitor(0, 0, 1280, 1024), monitor(-1920, 0, 1920, 1080)])

    assert layout.resolutions() == [(1920, 1080), (1280, 1024)]
    assert layout.digital_offsets() == [(0, 0), (1920, 0)]


def test_an_undetected_display_size_is_hinted_until_a_diagonal_is_entered(display_layout):
    layout = display_layout([monitor(0, 0, 1920, 1080, None, None)])

    assert layout.size_hint() == displays.SIZE_HINT
    assert layout.with_diagonals([15.6]).size_hint() is None
    assert display_layout().size_hint() is None


def test_bezels_cant_be_negative(display_layout):
    with pytest.raises(ValueError, match="negative"):
        display_layout().with_bezels([(-1.0, 0.0), (0.0, 0.0)])


def test_a_layout_needs_a_value_for_every_display(display_layout):
    with pytest.raises(ValueError, match="same number of values"):
        display_layout().with_offsets([(0, 0)])


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


def test_displays_are_detected_only_on_the_main_thread(monkeypatch):
    # libXrandr, behind screeninfo, corrupts memory when two threads use it at once.
    monkeypatch.setattr(display_detection, "get_monitors", lambda: pytest.fail("detected off the main thread"))
    errors = []

    def detect():
        try:
            display_detection.detect_displays()
        except RuntimeError as error:
            errors.append(str(error))

    worker = threading.Thread(target=detect)
    worker.start()
    worker.join(10)

    assert errors == ["Displays can only be detected on the main thread."]
