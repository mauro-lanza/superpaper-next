from dataclasses import FrozenInstanceError

import pytest

from superpaper.geometry import displays
from tests.conftest import monitor
from tests.geometry.conftest import DUAL_MONITORS, detect, edit_the_layout


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


def test_displays_in_a_column_are_centred_in_it_and_the_columns_in_each_other(display_layout):
    # A 1920x1080 display with a narrower one below it, and a taller one to the right.
    layout = display_layout(
        [
            monitor(0, 0, 1920, 1080, 527, 296, "top"),
            monitor(480, 1080, 960, 540, 264, 148, "below"),
            monitor(1920, 0, 1080, 1920, 296, 527, "tall"),
        ]
    )

    # The first column is 1923 wide and 1624 high at the common density, the tall display 1920 high.
    assert layout.ppi_norm_resolutions() == [(1923, 1082), (963, 542), (1080, 1920)]
    assert layout.ppi_norm_offsets == ((0, 148), (480, 1230), (1923, 0))


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


def test_a_layout_is_never_changed_an_edit_is_a_new_layout(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)
    offsets = layout.ppi_norm_offsets

    edited = edit_the_layout(layout)

    with pytest.raises(FrozenInstanceError):
        layout.use_perspective = False  # ty: ignore[invalid-assignment]
    assert edited.ppi_norm_offsets == ((5, 6), (4005, 6))
    assert layout.ppi_norm_offsets == offsets
    assert layout.uses_user_diagonals and layout.bezels_in_mm() == [(10.5, 0.0), (0.0, 0.0)]


def test_changes_are_unsaved_only_when_the_settings_differ_from_the_saved_ones(layout):
    saved = layout.settings()

    assert layout.settings() == saved
    assert layout.with_diagonals([20.0, 20.0]).settings() != saved
    assert layout.with_offsets([(0, 0), (1, 1)]).settings() != saved
    assert layout.with_bezels([(1.0, 0.0), (0.0, 0.0)]).settings() != saved


def test_changing_something_and_back_is_not_a_change(layout):
    saved = layout.settings()

    changed_back = layout.with_diagonals([20.0, 20.0]).with_detected_sizes()

    assert changed_back.settings() == saved


def test_the_display_settings_restore_what_they_captured(layout):
    saved = layout.with_diagonals([27.0, 24.0]).with_bezels([(8.5, 0.0), (0.0, 3.3)]).with_offsets([(0, 0), (2000, 10)])
    settings = saved.settings()

    changed = saved.with_detected_sizes().with_bezels([(1.0, 1.0), (1.0, 1.0)])
    assert changed.settings() != settings
    assert changed.with_settings(settings).settings() == settings


def test_the_display_settings_round_to_two_decimals_and_restore_detected_sizes(layout):
    settings = layout.with_bezels([(1.234, 0.0), (0.0, 0.0)]).settings()

    assert settings.bezels_mm[0] == (1.23, 0.0)
    assert not settings.use_user_diagonals
    assert not layout.with_diagonals([27.0, 27.0]).with_settings(settings).uses_user_diagonals
