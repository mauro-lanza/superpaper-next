"""The positions and bezel tools' save and cancel, and the display settings band's entry rules."""

import pytest

from superpaper.geometry import display_store, layout_edit
from superpaper.geometry.display_store import SaveFailed
from superpaper.geometry.layout_edit import ConfiguringBezels, ConfiguringPositions, Idle, parse_bezel, parse_diagonals
from superpaper.user_input import Problems
from tests.conftest import monitor


def test_positioning_remembers_the_offsets_it_began_with(layout):
    state = layout_edit.start_positions(Idle(), layout)

    assert state == ConfiguringPositions(layout.ppi_norm_offsets)


def test_saving_positions_keeps_the_layout_when_nothing_was_dragged(layout):
    state = layout_edit.start_positions(Idle(), layout)

    assert layout_edit.save_positions(state, layout, None) == (Idle(), layout)


def test_saving_positions_uses_the_dragged_offsets(layout):
    state = layout_edit.start_positions(Idle(), layout)

    new_state, saved = layout_edit.save_positions(state, layout, [(0, 0), (5, 7)])

    assert new_state == Idle()
    assert saved == layout.with_offsets([(0, 0), (5, 7)])


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
    assert entered.user_diagonal_inches == (24.0, 27.5)


@pytest.mark.parametrize(
    ("texts", "inches"),
    [
        (["27", "24.5"], [27.0, 24.5]),
        (["27", ""], None),
        (["27", "0"], None),
        (["-1"], None),
        (["x"], None),
        ([], None),
    ],
)
def test_diagonals_apply_only_when_every_field_is_a_positive_number(texts, inches):
    assert parse_diagonals(texts) == inches


@pytest.mark.parametrize(
    ("text", "value"), [("0", 0.0), ("3.5", 3.5), ("-1", None), ("", None), ("nan", None), ("x", None)]
)
def test_a_bezel_is_a_non_negative_number(text, value):
    assert parse_bezel(text) == value


def test_invalid_entered_diagonals_change_nothing(layout):
    assert layout_edit.with_entered_diagonals(layout, ["24", "x"]) is None


def test_returning_to_detected_sizes_arranges_the_displays_afresh_when_the_sizes_change(layout):
    manual = layout.with_diagonals([20.0, 30.0]).with_offsets([(0, 500), (7, 0)])

    back = layout_edit.arranged_if_resized(manual, manual.with_detected_sizes())

    assert back.user_diagonal_inches is None
    assert back.ppi_norm_offsets == layout.ppi_norm_offsets


def test_switching_between_equal_sizes_keeps_the_arrangement(layout):
    detected = layout.diagonal_inches()
    moved = layout.with_offsets([(0, 500), (7, 0)])
    manual = moved.with_diagonals(detected)

    assert (
        layout_edit.arranged_if_resized(manual, manual.with_detected_sizes()).ppi_norm_offsets == moved.ppi_norm_offsets
    )
    assert layout_edit.arranged_if_resized(moved, manual).ppi_norm_offsets == moved.ppi_norm_offsets


@pytest.fixture
def mixed_layout(display_layout):
    monitors = [monitor(0, 0, 1920, 1080, 527, 296, "A"), monitor(1920, 0, 1360, 1088, 421, 237, "B")]
    return display_layout(monitors).with_offsets([(0, 500), (7, 0)])


def test_switching_to_manual_sizes_keeps_the_arrangement_when_the_shown_sizes_are_unchanged(mixed_layout):
    before = mixed_layout
    after = layout_edit.with_entered_diagonals(before, [str(d) for d in before.diagonal_inches()])

    assert after is not None
    assert after.ppi_norm_resolutions() != before.ppi_norm_resolutions()
    assert layout_edit.arranged_if_resized(before, after).ppi_norm_offsets == before.ppi_norm_offsets


def test_entering_a_different_size_arranges_the_displays_afresh(mixed_layout):
    after = layout_edit.with_entered_diagonals(mixed_layout, ["28.0", "19.0"])

    assert after is not None
    assert layout_edit.arranged_if_resized(mixed_layout, after).ppi_norm_offsets != mixed_layout.ppi_norm_offsets


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


def test_display_settings_that_cant_be_written_come_back_as_a_failure(layout, tmp_path):
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("", encoding="utf-8")

    failure = layout_edit.save_display_settings(not_a_directory, layout)

    assert isinstance(failure, SaveFailed)
    assert failure.message.startswith("The display settings could not be saved: ")
