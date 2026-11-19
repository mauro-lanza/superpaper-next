"""Saving a perspective from the dialog's fields."""

import re
from dataclasses import astuple

import pytest

from superpaper.geometry import canvas, display_store
from superpaper.geometry.display_store import SaveFailed
from superpaper.geometry.perspective import Perspective, Swivel, SwivelAxis, Tilt
from superpaper.geometry.perspective_form import (
    NeedsConfirm,
    PerspectiveForm,
    Saved,
    blank_form,
    check_new_perspective_name,
    form_from,
    parse_rotations_mm,
    parse_viewer_offsets_mm,
    perspective_from_mm,
    save_choice,
    save_perspective,
)
from superpaper.user_input import Problems

ZEROS = ("0", "0", "0", "0", "0", "0")


def flatten(perspective):
    """Every number of ``perspective`` in one list, the swivel axes as their values."""
    numbers = [perspective.central_display, *perspective.viewer_pos]
    for swivel, tilt in zip(perspective.swivels, perspective.tilts, strict=True):
        numbers += [swivel.axis.value, swivel.angle, swivel.lateral_offset, swivel.depth_offset, *astuple(tilt)]
    return numbers


def form(**changes):
    fields = {
        "name": "desk",
        "use_perspective": True,
        "is_default": True,
        "central_display": 0,
        "viewer_offsets": ("0", "0", "600"),
        "swivel_axes": (0, 0),
        "rotation_cells": (ZEROS, ZEROS),
    }
    return PerspectiveForm(**(fields | changes))


def save(layout, tmp_path, form_=None, *, warn_large=True, confirmed=False):
    return save_perspective(
        form_ or form(),
        layout=layout,
        offsets=((0, 0), (0, 0)),
        warn_large=warn_large,
        confirmed=confirmed,
        config_dir=tmp_path,
    )


def test_a_valid_form_is_saved_into_the_layout_and_its_file(layout, tmp_path):
    result = save(layout, tmp_path)

    assert isinstance(result, Saved)
    assert result.layout.default_perspective == "desk"
    assert result.layout.perspective("desk").central_display == 0
    assert result.layout.perspective("desk").viewer_pos[2] == pytest.approx(600 * layout.max_ppi() / 25.4)
    assert display_store.load(tmp_path, layout.displays).perspectives[0].name == "desk"


def test_a_form_without_a_name_is_a_problem_and_saves_nothing(layout, tmp_path):
    assert save(layout, tmp_path, form(name="")) == Problems(("Profile name is required.",))
    assert not list(tmp_path.iterdir())


def test_a_new_perspective_cannot_take_a_reserved_name(layout, tmp_path):
    result = save(layout, tmp_path, form(name="Default"))

    assert isinstance(result, Problems)
    assert "reserved" in result.messages[0]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"viewer_offsets": ("0", "x", "600")}, "Viewer offsets"),
        ({"viewer_offsets": ("0", "0", "0")}, "Viewer distance"),
        ({"rotation_cells": (ZEROS, ("0", "0", "0", "oops", "0", "0"))}, "Display 1, 'Tilt angle'"),
    ],
)
def test_fields_that_are_not_numbers_are_a_problem(layout, tmp_path, changes, message):
    result = save(layout, tmp_path, form(**changes))

    assert isinstance(result, Problems)
    assert message in result.messages[0]


def test_a_large_intermediate_image_needs_confirming_before_anything_is_saved(layout, tmp_path, monkeypatch):
    monkeypatch.setattr(canvas, "MAX_PERSPECTIVE_CANVAS", 10)

    result = save(layout, tmp_path)

    assert isinstance(result, NeedsConfirm)
    assert "Intermediate resolution with these settings is" in result.message
    assert not list(tmp_path.iterdir())


def test_a_confirmed_large_image_is_saved(layout, tmp_path, monkeypatch):
    monkeypatch.setattr(canvas, "MAX_PERSPECTIVE_CANVAS", 10)

    assert isinstance(save(layout, tmp_path, confirmed=True), Saved)


def test_the_size_warning_can_be_turned_off(layout, tmp_path, monkeypatch):
    monkeypatch.setattr(canvas, "MAX_PERSPECTIVE_CANVAS", 10)

    assert isinstance(save(layout, tmp_path, warn_large=False), Saved)


def test_a_file_that_cannot_be_written_is_a_failure_with_the_layout_unchanged(layout, tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("")

    result = save_perspective(
        form(),
        layout=layout,
        offsets=((0, 0), (0, 0)),
        warn_large=False,
        confirmed=False,
        config_dir=blocked,
    )

    assert isinstance(result, SaveFailed)
    assert result.message.startswith("The perspective settings could not be saved: ")
    assert layout.perspective("desk") is None


def test_the_choice_alone_can_be_saved(layout, tmp_path):
    assert save_choice(tmp_path, layout.with_use_perspective(False)) is None


def test_a_blank_form_is_neutral_for_every_display(layout):
    blank = blank_form(layout)

    assert blank.name == "" and not blank.is_default
    assert blank.swivel_axes == (0, 0)
    assert blank.rotation_cells == (("0.0",) * 6, ("0.0",) * 6)
    assert blank.viewer_offsets == ("0", "0", "0")
    assert blank.use_perspective == layout.use_perspective


def test_a_blank_form_is_not_a_saveable_perspective_until_named_and_given_a_distance(layout, tmp_path):
    assert isinstance(save(layout, tmp_path, blank_form(layout)), Problems)


def test_a_stored_perspective_is_shown_in_millimetres(layout):
    ppm = layout.max_ppi() / 25.4
    stored = Perspective(
        "desk",
        1,
        (0.0, 0.0, 600 * ppm),
        (Swivel(SwivelAxis.LEFT, 10.0, 20 * ppm, 30 * ppm), Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0)),
        (Tilt(5.0, 40 * ppm, 50 * ppm), Tilt(0.0, 0.0, 0.0)),
    )
    shown = form_from(stored, layout.with_perspective(stored, use_perspective=False, is_default=True))

    assert shown.name == "desk" and shown.is_default and not shown.use_perspective
    assert shown.central_display == 1
    assert float(shown.viewer_offsets[2]) == pytest.approx(600)
    assert shown.swivel_axes == (1, 0)
    assert shown.rotation_cells[0] == ("10.0", "20.0", "30.0", "5.0", "40.0", "50.0")


def test_a_perspective_that_is_not_the_default_is_not_shown_as_default(layout):
    stored = Perspective("desk", 0, (0.0, 0.0, 1.0), (), ())

    assert not form_from(stored, layout).is_default


def test_showing_a_perspective_and_saving_it_again_gives_the_same_perspective(layout, tmp_path):
    ppm = layout.max_ppi() / 25.4
    stored = Perspective(
        "desk",
        1,
        (12.5 * ppm, -3.0 * ppm, 600 * ppm),
        (Swivel(SwivelAxis.RIGHT, 10.5, 20.5 * ppm, 30.0 * ppm), Swivel(SwivelAxis.LEFT, -4.0, 0.0, 1.5 * ppm)),
        (Tilt(5.0, 40.0 * ppm, 50.0 * ppm), Tilt(-2.5, 0.0, 0.0)),
    )
    with_it = layout.with_perspective(stored, use_perspective=True, is_default=True)

    result = save(with_it, tmp_path, form_from(stored, with_it))

    assert isinstance(result, Saved)
    assert flatten(result.layout.perspective("desk")) == pytest.approx(flatten(stored))


@pytest.mark.parametrize("name", ["default", "DEFAULT", "Default", "disabled", "Disabled", "None", "none", "NONE"])
def test_reserved_perspective_names_are_rejected(name):
    with pytest.raises(ValueError, match="reserved"):
        check_new_perspective_name(name)


@pytest.mark.parametrize("name", ["desk", "defaults", "none of them", "My default"])
def test_other_perspective_names_are_accepted(name):
    check_new_perspective_name(name)


def test_lengths_convert_millimetres_to_pixels_and_keep_angles():
    perspective = perspective_from_mm(
        "desk",
        163.0,
        1,
        [0.0, -30.5, 500.0],
        [(SwivelAxis.LEFT, 12.0, 7.25, -3.0)],
        [(-4.5, 12.0, 40.0)],
    )

    assert perspective.viewer_pos == pytest.approx((0.0, -195.72834645669292, 3208.6614173228345))
    assert perspective == Perspective(
        "desk",
        1,
        perspective.viewer_pos,
        (Swivel(SwivelAxis.LEFT, 12.0, 46.525590551181104, -19.251968503937007),),
        (Tilt(-4.5, 77.00787401574803, 256.6929133858268),),
    )


def test_no_displays_rows_give_empty_swivels_and_tilts():
    perspective = perspective_from_mm("desk", 96.0, 0, [0.0, 0.0, 1.0], [], [])

    assert (perspective.swivels, perspective.tilts) == ((), ())


def test_the_grid_cells_become_swivels_and_tilts_per_display():
    swivels, tilts = parse_rotations_mm(
        [1, 0],
        [["10", "1.5", "-2", "-4.5", "12", "40"], ["0", "0", "0", "0", "0", "0"]],
    )

    assert swivels == [(SwivelAxis.LEFT, 10.0, 1.5, -2.0), (SwivelAxis.NONE, 0.0, 0.0, 0.0)]
    assert tilts == [(-4.5, 12.0, 40.0), (0.0, 0.0, 0.0)]


def test_a_grid_without_displays_gives_nothing():
    assert parse_rotations_mm([], []) == ([], [])


@pytest.mark.parametrize(
    ("column", "name"),
    [
        (0, "Swivel angle"),
        (1, "Sw. ax. lat. off."),
        (2, "Sw. ax. dep. off."),
        (3, "Tilt angle"),
        (4, "Ti. ax. ver. off."),
        (5, "Ti. ax. dep. off."),
    ],
)
def test_a_grid_cell_that_is_not_a_number_is_named_by_display_and_column(column, name):
    row = ["0"] * 6
    row[column] = "1,5"

    with pytest.raises(ValueError, match=rf"Display 1, '{re.escape(name)}': '1,5' is not a number") as error:
        parse_rotations_mm([0, 0], [["0"] * 6, row])

    assert "separate decimals with a point" in str(error.value)


def test_viewer_offsets_are_read_in_millimetres():
    assert parse_viewer_offsets_mm(["0", "-30.5", "500"]) == [0.0, -30.5, 500.0]


def test_a_viewer_offset_that_is_not_a_number_is_an_error():
    with pytest.raises(ValueError, match="lengths in millimetres"):
        parse_viewer_offsets_mm(["0", "x", "500"])


@pytest.mark.parametrize("distance", ["0", "-1"])
def test_the_viewer_distance_must_be_positive(distance):
    with pytest.raises(ValueError, match="Viewer distance must be entered and positive"):
        parse_viewer_offsets_mm(["0", "0", distance])
