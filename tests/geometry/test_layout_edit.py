"""The positions and bezel tools' save and cancel, and the display settings band's entry rules."""

import pytest

from superpaper.geometry import display_store, layout_edit
from superpaper.geometry.display_store import SaveFailed
from superpaper.geometry.displays import Layout
from superpaper.geometry.layout_edit import (
    ConfiguringBezels,
    ConfiguringPositions,
    Idle,
    parse_bezel,
    parse_diagonal,
    parse_diagonals,
)
from superpaper.user_input import Problems
from tests.conftest import monitor
from tests.geometry.conftest import OVERLAPPING_MONITORS


def test_positioning_remembers_the_offsets_it_began_with(layout):
    state = layout_edit.start_positions(Idle(), layout)

    assert state == ConfiguringPositions(layout.ppi_norm_offsets)


def test_saving_positions_keeps_the_layout_when_nothing_was_dragged(layout):
    state = layout_edit.start_positions(Idle(), layout)

    assert layout_edit.save_positions(state, layout, None) == (Idle(), layout)


def test_saving_positions_uses_the_dragged_offsets(layout):
    state = layout_edit.start_positions(Idle(), layout)

    new_state, saved = layout_edit.save_positions(state, layout, [(0, 0), (3000, 7)])

    assert new_state == Idle()
    assert saved == layout.with_offsets([(0, 0), (3000, 7)])


def test_positions_that_overlap_cannot_be_saved(layout):
    state = layout_edit.start_positions(Idle(), layout)

    assert layout_edit.save_positions(state, layout, [(0, 0), (5, 7)]) == Problems((layout_edit.OVERLAP_MESSAGE,))


def test_positions_that_overlap_cannot_be_kept_by_leaving_them_undragged(layout):
    state = layout_edit.start_positions(Idle(), layout)
    overlapping = layout.with_offsets([(0, 0), (5, 7)])

    assert layout_edit.save_positions(state, overlapping, None) == Problems((layout_edit.OVERLAP_MESSAGE,))


def test_cancelling_positions_restores_the_offsets_even_after_changes(layout):
    state = layout_edit.start_positions(Idle(), layout)
    moved = layout.with_offsets([(3, 3), (9, 9)])

    assert layout_edit.cancel_positions(state, moved) == (Idle(), layout)


def test_setting_bezels_remembers_the_bezels_and_offsets_it_began_with(layout):
    bezeled = layout.with_bezels([(2.0, 1.0), (0.0, 0.0)])

    state = layout_edit.start_bezels(Idle(), bezeled)

    assert state == ConfiguringBezels(((2.0, 1.0), (0.0, 0.0)), bezeled.ppi_norm_offsets)


def test_saving_bezels_keeps_the_layout(layout):
    state = layout_edit.start_bezels(Idle(), layout)
    bezeled = layout.with_bezels([(4.0, 0.0), (0.0, 0.0)])

    assert layout_edit.save_bezels(state, bezeled) == (Idle(), bezeled)


def test_cancelling_bezels_restores_bezels_and_offsets(layout):
    state = layout_edit.start_bezels(Idle(), layout)
    bezeled = layout.with_bezels([(4.0, 0.0), (0.0, 0.0)])

    new_state, restored = layout_edit.cancel_bezels(state, bezeled)

    assert new_state == Idle()
    assert restored.bezels_in_mm() == layout.bezels_in_mm()
    assert restored.ppi_norm_offsets == layout.ppi_norm_offsets


@pytest.mark.parametrize("busy", [ConfiguringPositions(()), ConfiguringBezels((), ())])
def test_a_tool_cannot_start_while_another_is_active(layout, busy):
    with pytest.raises(ValueError, match="Expected Idle"):
        layout_edit.start_positions(busy, layout)
    with pytest.raises(ValueError, match="Expected Idle"):
        layout_edit.start_bezels(busy, layout)


ENDINGS = {
    "ConfiguringPositions": (
        lambda state, layout: layout_edit.save_positions(state, layout, None),
        layout_edit.cancel_positions,
    ),
    "ConfiguringBezels": (layout_edit.save_bezels, layout_edit.cancel_bezels),
}


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (Idle(), "ConfiguringPositions"),
        (ConfiguringBezels((), ()), "ConfiguringPositions"),
        (Idle(), "ConfiguringBezels"),
        (ConfiguringPositions(()), "ConfiguringBezels"),
    ],
)
def test_a_tool_cannot_be_ended_unless_it_is_active(layout, state, expected):
    for end in ENDINGS[expected]:
        with pytest.raises(ValueError, match=f"Expected {expected}"):
            end(state, layout)


def test_valid_entered_diagonals_are_applied(layout):
    entered = layout_edit.with_entered_diagonals(layout, ["24", "27.5"])

    assert entered is not None
    assert entered.layout.user_diagonal_inches == (24.0, 27.5)


@pytest.mark.parametrize(
    ("texts", "inches"),
    [
        (["27", "24.5"], [27.0, 24.5]),
        (["27", "24,5"], [27.0, 24.5]),
        ([" 27 ", "1"], [27.0, 1.0]),
        (["1000"], [1000.0]),
        (["27", ""], None),
        (["27", "0"], None),
        (["0.9"], None),
        (["1000.1"], None),
        (["-1"], None),
        (["x"], None),
        (["15."], None),
        (["1_5"], None),
        (["1e3"], None),
        (["1,000.5"], None),
        (["+15"], None),
        (["-15"], None),
        (["15.6.1"], None),
        (["inf"], None),
        (["\u0661\u0665"], None),
        (["1e999"], None),
        ([], None),
    ],
)
def test_diagonals_apply_only_when_every_field_is_a_size_from_1_to_1000_inches(texts, inches):
    assert parse_diagonals(texts) == inches


@pytest.mark.parametrize(
    ("text", "value"), [("0", 0.0), ("3.5", 3.5), ("-1", None), ("", None), ("nan", None), ("x", None)]
)
def test_a_bezel_is_a_non_negative_number(text, value):
    assert parse_bezel(text) == value


def test_a_diagonal_may_be_any_size_from_1_to_1000_inches():
    assert [parse_diagonal(text) for text in ("1", "1000", "15.6")] == [1.0, 1000.0, 15.6]


def test_invalid_entered_diagonals_change_nothing(layout):
    assert layout_edit.with_entered_diagonals(layout, ["24", "x"]) is None


@pytest.fixture
def grown_by_diagonals(layout):
    """``layout`` with display 0 entered as much bigger than display 1: it grows over display 1."""
    return layout.with_diagonals([40.0, 24.0])


def test_a_resize_that_overlaps_shifts_only_the_overlapping_display(layout, grown_by_diagonals):
    assert not grown_by_diagonals.is_valid()

    resized = layout_edit.fit_resized(grown_by_diagonals)

    assert resized.layout.is_valid()
    assert resized.rearranged_all is False
    assert resized.layout.ppi_norm_offsets[0] == layout.ppi_norm_offsets[0]
    assert resized.layout.ppi_norm_offsets[1][0] > layout.ppi_norm_offsets[1][0]
    assert resized.layout.ppi_norm_offsets[1][1] == layout.ppi_norm_offsets[1][1]


def test_a_resize_that_overlaps_nothing_changes_no_position(layout):
    resized = layout_edit.fit_resized(layout.with_diagonals([24.0, 40.0]))

    assert resized == layout_edit.Resized(layout.with_diagonals([24.0, 40.0]), rearranged_all=False)


def test_all_displays_are_arranged_afresh_when_shifting_cannot_resolve_the_overlap(
    monkeypatch, layout, grown_by_diagonals
):
    monkeypatch.setattr(Layout, "with_overlaps_shifted", lambda self: None)

    resized = layout_edit.fit_resized(grown_by_diagonals)

    assert resized.rearranged_all is True
    assert resized.layout.is_valid()
    assert resized.layout.ppi_norm_offsets == grown_by_diagonals.with_initial_offsets().ppi_norm_offsets


def test_typing_15_6_inches_for_the_portable_leaves_the_displays_apart(display_layout):
    layout = display_layout(OVERLAPPING_MONITORS).with_offsets([(0, 361), (2560, 0)])

    resized = layout_edit.with_entered_diagonals(layout, ["27.2", "15.6"])

    assert resized is not None
    assert resized.layout.is_valid()
    assert resized.rearranged_all is False
    assert resized.layout.ppi_norm_offsets[0] == (0, 361)
    assert resized.layout.ppi_norm_offsets[1] != (2560, 0)


def test_the_overlap_of_the_saved_layout_of_the_portable_is_resolved_by_moving_only_the_portable(display_layout):
    overlapping = display_layout(OVERLAPPING_MONITORS).with_offsets([(0, 361), (2560, 0)]).with_diagonals([27.2, 15.6])
    assert not overlapping.is_valid()

    shifted = overlapping.with_overlaps_shifted()

    assert shifted is not None
    assert shifted.is_valid()
    assert shifted.ppi_norm_offsets[0] == (0, 361)
    assert shifted.ppi_norm_offsets[1][1] == 0
    assert shifted.ppi_norm_offsets[1][0] > 2560


def test_displays_that_do_not_overlap_are_not_shifted(layout):
    assert layout.with_overlaps_shifted() == layout


def test_a_display_that_overlaps_a_display_before_it_is_moved_down_when_that_is_the_least(display_layout):
    stacked = display_layout([monitor(0, 0, 2560, 1440, 602, 339), monitor(0, 1440, 2560, 1440, 602, 339)])
    overlapping = stacked.with_offsets([(0, 0), (0, 100)])

    shifted = overlapping.with_overlaps_shifted()

    assert shifted is not None
    assert shifted.is_valid()
    assert shifted.ppi_norm_offsets[0] == (0, 0)
    assert shifted.ppi_norm_offsets[1][0] == 0
    assert shifted.ppi_norm_offsets[1][1] > 100


def test_valid_entered_bezels_are_applied(layout):
    result = layout_edit.with_entered_bezels(layout, [("2.0", "0.0"), ("0.0", "1.5")])

    assert result == layout.with_bezels([(2.0, 0.0), (0.0, 1.5)])


def test_invalid_entered_bezels_are_reported_with_the_text_entered(layout):
    result = layout_edit.with_entered_bezels(layout, [("x", "0.0"), ("1.0", "-1")])

    assert result == Problems(
        (
            "Bezel thickness must be a non-negative number, 'x' was entered.",
            "Bezel thickness must be a non-negative number, '-1' was entered.",
        )
    )


def test_saving_display_settings_writes_them_to_the_config_directory(layout, tmp_path):
    assert layout_edit.save_display_settings(tmp_path, layout) is None
    assert display_store.load(tmp_path, layout.displays).ppi_norm_offsets == layout.ppi_norm_offsets


def test_display_settings_that_overlap_come_back_as_a_failure_and_write_nothing(layout, tmp_path):
    failure = layout_edit.save_display_settings(tmp_path, layout.with_offsets([(0, 0), (5, 5)]))

    assert isinstance(failure, SaveFailed)
    assert "overlap" in failure.message
    assert not list(tmp_path.iterdir())


def test_display_settings_that_cant_be_written_come_back_as_a_failure(layout, tmp_path):
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("", encoding="utf-8")

    failure = layout_edit.save_display_settings(not_a_directory, layout)

    assert isinstance(failure, SaveFailed)
    assert failure.message.startswith("The display settings could not be saved: ")
