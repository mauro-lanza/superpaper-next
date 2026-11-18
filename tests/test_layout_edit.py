"""The positions and bezel tools' save and cancel, and the display settings band's changes."""

from types import SimpleNamespace

import pytest

from superpaper.files import SaveFailed
from superpaper.geometry import display_detection, display_store, layout_edit
from superpaper.geometry.layout_edit import ConfiguringBezels, ConfiguringPositions, Idle
from superpaper.user_input import Problems

MONITORS = [
    SimpleNamespace(x=0, y=0, width=1920, height=1080, width_mm=527, height_mm=296, name="A"),
    SimpleNamespace(x=1920, y=0, width=1920, height=1080, width_mm=527, height_mm=296, name="B"),
]


@pytest.fixture
def layout(monkeypatch, tmp_path):
    monkeypatch.setattr(display_detection, "get_monitors", lambda: MONITORS)
    return display_detection.detect_layout(tmp_path)


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


@pytest.mark.parametrize("state", [Idle(), ConfiguringBezels((), ())])
def test_positions_cannot_be_ended_unless_positioning(layout, state):
    with pytest.raises(ValueError, match="Expected ConfiguringPositions"):
        layout_edit.save_positions(state, layout, None)
    with pytest.raises(ValueError, match="Expected ConfiguringPositions"):
        layout_edit.cancel_positions(state, layout)


@pytest.mark.parametrize("state", [Idle(), ConfiguringPositions(())])
def test_bezels_cannot_be_ended_unless_setting_them(layout, state):
    with pytest.raises(ValueError, match="Expected ConfiguringBezels"):
        layout_edit.save_bezels(state, layout)
    with pytest.raises(ValueError, match="Expected ConfiguringBezels"):
        layout_edit.cancel_bezels(state, layout)


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


def test_valid_entered_diagonals_are_applied(layout):
    entered = layout_edit.with_entered_diagonals(layout, ["24", "27.5"])

    assert entered is not None
    assert entered.user_diagonal_inches == (24.0, 27.5)


@pytest.mark.parametrize("texts", [["24", ""], ["24", "x"], ["24", "0"]])
def test_invalid_entered_diagonals_change_nothing(layout, texts):
    assert layout_edit.with_entered_diagonals(layout, texts) is None


def test_returning_to_detected_sizes_arranges_the_displays_afresh(layout):
    manual = layout.with_diagonals([20.0, 20.0]).with_offsets([(0, 500), (7, 0)])

    back = manual.with_detected_sizes().with_initial_offsets()

    assert back == layout.with_offsets(back.ppi_norm_offsets)
    assert back.user_diagonal_inches is None
    assert back.ppi_norm_offsets == layout.ppi_norm_offsets


def test_reverting_restores_the_saved_settings(layout):
    saved = layout.settings()
    edited = layout.with_diagonals([20.0, 20.0]).with_bezels([(3.0, 0.0), (0.0, 0.0)])

    assert edited.settings() != saved
    assert edited.with_settings(saved).settings() == saved


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


def test_cancelling_the_position_entry_restores_the_offsets_it_opened_with(layout):
    opened_with = layout_edit.start_positions(Idle(), layout)
    entered = layout.with_offsets([(0, 0), (40, 0)])

    _, restored = layout_edit.cancel_positions(opened_with, entered)

    assert restored == layout


def test_saving_display_settings_writes_them_to_the_config_directory(layout, tmp_path):
    assert layout_edit.save_display_settings(tmp_path, layout) is None
    assert display_store.read_layout(tmp_path, layout.key) is not None


def test_display_settings_that_cant_be_written_come_back_as_a_failure(layout, tmp_path):
    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("", encoding="utf-8")

    failure = layout_edit.save_display_settings(not_a_directory, layout)

    assert isinstance(failure, SaveFailed)
    assert failure.message.startswith("The display settings could not be saved: ")
