from types import SimpleNamespace

import pytest

from superpaper.geometry import display_detection

MONITORS = [
    SimpleNamespace(x=0, y=0, width=1920, height=1080, width_mm=527, height_mm=296, name="A"),
    SimpleNamespace(x=1920, y=0, width=1920, height=1080, width_mm=527, height_mm=296, name="B"),
]


@pytest.fixture
def layout(monkeypatch, tmp_path):
    monkeypatch.setattr(display_detection, "get_monitors", lambda: MONITORS)
    return display_detection.detect_layout(tmp_path)


def bezel_px(layout, mm):
    return mm * layout.max_ppi() / 25.4


def overlap(layout):
    areas = layout.ppi_norm_areas()
    cells = [
        (
            a.offset[0],
            a.offset[1],
            a.offset[0] + a.resolution[0] + a.bezels[0],
            a.offset[1] + a.resolution[1] + a.bezels[1],
        )
        for a in areas
    ]
    return any(
        min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1
        for i, a in enumerate(cells)
        for b in cells[i + 1 :]
    )


def test_a_diagonal_change_keeps_the_bezels_in_millimetres(layout):
    layout = layout.with_diagonals([27.0, 27.0]).with_bezels([(8.5, 0.0), (0.0, 3.3)])
    px_before = layout.ppi_norm_bezels()

    resized = layout.with_diagonals([28.0, 28.0])
    assert resized.bezels_in_mm() == [(8.5, 0.0), (0.0, 3.3)]
    assert resized.ppi_norm_bezels() != px_before

    restored = resized.with_diagonals([27.0, 27.0])
    assert restored.bezels_in_mm() == [(8.5, 0.0), (0.0, 3.3)]
    assert restored.ppi_norm_bezels() == pytest.approx(px_before)


def test_a_fresh_layout_gets_the_initial_layout_when_bezels_are_set(layout):
    bezeled = layout.with_bezels([(10.0, 0.0), (0.0, 0.0)])

    assert bezeled.ppi_norm_offsets == pytest.approx([(0, 0), (1920 + bezel_px(layout, 10.0), 0)], abs=1)


def test_an_overlapping_layout_gets_the_initial_layout_when_bezels_are_set(layout):
    bezeled = layout.with_offsets([(0, 0), (100, 0)]).with_bezels([(10.0, 0.0), (0.0, 0.0)])

    assert bezeled.ppi_norm_offsets == pytest.approx([(0, 0), (1920 + bezel_px(layout, 10.0), 0)], abs=1)


def test_dragged_positions_survive_setting_bezels(layout):
    dragged = layout.with_offsets([(0.5, 300.25), (2400.0, 0.0)])

    assert dragged.with_bezels([(0.0, 0.0), (0.0, 5.0)]).ppi_norm_offsets == ((0.5, 300.25), (2400.0, 0.0))


def test_displays_after_a_bezel_move_by_exactly_its_growth(layout):
    dragged = layout.with_offsets([(0, 300), (2400.0, 0)])

    left, right = dragged.with_bezels([(10.0, 0.0), (0.0, 0.0)]).ppi_norm_offsets

    assert left == (0, 300)
    assert right == pytest.approx((2400.0 + bezel_px(layout, 10.0), 0))


def test_corner_touching_displays_do_not_overlap_after_setting_bezels(layout):
    touching = layout.with_offsets([(0, 0), (1920, 1080)])

    assert not overlap(touching.with_bezels([(10.0, 10.0), (10.0, 10.0)]))


def test_a_gap_between_dragged_displays_is_kept_when_a_bezel_changes_back(layout):
    bezeled = layout.with_offsets([(0, 0), (2400.0, 0)]).with_bezels([(10.0, 0.0), (0.0, 0.0)])

    back = bezeled.with_bezels([(0.0, 0.0), (0.0, 0.0)])

    assert back.ppi_norm_offsets == ((0, 0), pytest.approx((2400.0, 0)))


def test_displays_in_a_column_are_centred_in_it_and_the_columns_in_each_other(monkeypatch, tmp_path):
    # A 1920x1080 display with a narrower one below it, and a taller one to the right.
    monitors = [
        SimpleNamespace(x=0, y=0, width=1920, height=1080, width_mm=527, height_mm=296, name="top"),
        SimpleNamespace(x=480, y=1080, width=960, height=540, width_mm=264, height_mm=148, name="below"),
        SimpleNamespace(x=1920, y=0, width=1080, height=1920, width_mm=296, height_mm=527, name="tall"),
    ]
    monkeypatch.setattr(display_detection, "get_monitors", lambda: monitors)

    layout = display_detection.detect_layout(tmp_path)

    # The first column is 1923 wide and 1624 high at the common density, the tall display 1920 high.
    assert layout.ppi_norm_resolutions() == [(1923, 1082), (963, 542), (1080, 1920)]
    assert layout.ppi_norm_offsets == ((0, 148), (480, 1230), (1923, 0))
