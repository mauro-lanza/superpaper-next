"""Staging a perspective from the dialog's fields."""

from dataclasses import astuple

import pytest

from superpaper.geometry import canvas
from superpaper.geometry.perspective import Perspective, Swivel, SwivelAxis, Tilt
from superpaper.geometry.perspective_form import (
    NeedsConfirm,
    PerspectiveForm,
    Staged,
    blank_form,
    form_from,
    stage_perspective,
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


def stage(layout, form_=None, *, warn_large=True, confirmed=False):
    return stage_perspective(
        form_ or form(),
        layout=layout,
        offsets=((0, 0), (0, 0)),
        warn_large=warn_large,
        confirmed=confirmed,
    )


def test_a_valid_form_is_staged_into_the_layout(layout):
    result = stage(layout)

    assert isinstance(result, Staged)
    assert result.layout.default_perspective == "desk"
    assert result.layout.perspective("desk").central_display == 0
    assert result.layout.perspective("desk").viewer_pos[2] == pytest.approx(600 * layout.max_ppi() / 25.4)
    assert layout.perspective("desk") is None


def test_a_form_without_a_name_is_a_problem(layout):
    assert stage(layout, form(name="")) == Problems(("Profile name is required.",))


@pytest.mark.parametrize(
    ("name", "reserved"),
    [
        *((name, True) for name in ["default", "DEFAULT", "Default", "disabled", "Disabled", "None", "none", "NONE"]),
        *((name, False) for name in ["desk", "defaults", "none of them", "My default"]),
    ],
)
def test_a_new_perspective_cannot_take_a_reserved_name(layout, name, reserved):
    result = stage(layout, form(name=name))

    if reserved:
        assert result == Problems((f"'{name}' is reserved; choose another perspective name.",))
    else:
        assert isinstance(result, Staged)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"viewer_offsets": ("0", "x", "600")}, "Viewer offsets should be lengths in millimetres"),
        ({"viewer_offsets": ("0", "0", "0")}, "Viewer distance must be entered and positive"),
        ({"viewer_offsets": ("0", "0", "-1")}, "Viewer distance must be entered and positive"),
        *(
            (
                {"rotation_cells": (ZEROS, tuple("1,5" if cell == column else "0" for cell in range(6)))},
                f"Display 1, '{name}': '1,5' is not a number; separate decimals with a point.",
            )
            for column, name in enumerate(
                [
                    "Swivel angle",
                    "Sw. ax. lat. off.",
                    "Sw. ax. dep. off.",
                    "Tilt angle",
                    "Ti. ax. ver. off.",
                    "Ti. ax. dep. off.",
                ]
            )
        ),
    ],
)
def test_fields_that_are_not_numbers_are_a_problem(layout, changes, message):
    result = stage(layout, form(**changes))

    assert isinstance(result, Problems)
    assert message in result.messages[0]


@pytest.mark.parametrize(
    "rotations",
    [
        ("0", "0", "0", "90", "0", "0"),
        ("0", "0", "0", "270", "0", "0"),
    ],
)
def test_a_display_turned_edge_on_is_a_problem_not_an_error(layout, rotations):
    result = stage(layout, form(rotation_cells=(ZEROS, rotations)))

    assert isinstance(result, Problems)
    assert "edge-on" in result.messages[0]


def test_a_large_intermediate_image_needs_confirming_before_it_is_staged(layout, monkeypatch):
    monkeypatch.setattr(canvas, "MAX_PERSPECTIVE_CANVAS", 10)

    result = stage(layout)

    assert isinstance(result, NeedsConfirm)
    assert "Intermediate resolution with these settings is" in result.message


def test_a_confirmed_large_image_is_staged(layout, monkeypatch):
    monkeypatch.setattr(canvas, "MAX_PERSPECTIVE_CANVAS", 10)

    assert isinstance(stage(layout, confirmed=True), Staged)


def test_the_size_warning_can_be_turned_off(layout, monkeypatch):
    monkeypatch.setattr(canvas, "MAX_PERSPECTIVE_CANVAS", 10)

    assert isinstance(stage(layout, warn_large=False), Staged)


def test_a_blank_form_is_neutral_for_every_display(layout):
    blank = blank_form(layout)

    assert blank.name == "" and not blank.is_default
    assert blank.swivel_axes == (0, 0)
    assert blank.rotation_cells == (("0.0",) * 6, ("0.0",) * 6)
    assert blank.viewer_offsets == ("0", "0", "0")
    assert blank.use_perspective == layout.use_perspective


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


def test_showing_a_perspective_and_staging_it_again_gives_the_same_perspective(layout):
    ppm = layout.max_ppi() / 25.4
    stored = Perspective(
        "desk",
        1,
        (12.5 * ppm, -3.0 * ppm, 600 * ppm),
        (Swivel(SwivelAxis.RIGHT, 10.5, 20.5 * ppm, 30.0 * ppm), Swivel(SwivelAxis.LEFT, -4.0, 0.0, 1.5 * ppm)),
        (Tilt(5.0, 40.0 * ppm, 50.0 * ppm), Tilt(-2.5, 0.0, 0.0)),
    )
    with_it = layout.with_perspective(stored, use_perspective=True, is_default=True)

    result = stage(with_it, form_from(stored, with_it))

    assert isinstance(result, Staged)
    assert flatten(result.layout.perspective("desk")) == pytest.approx(flatten(stored))


def test_lengths_are_staged_from_millimetres_to_pixels_and_angles_are_kept(layout):
    ppm = layout.max_ppi() / 25.4

    result = stage(
        layout,
        form(
            central_display=1,
            viewer_offsets=("0", "-30.5", "500"),
            swivel_axes=(1, 0),
            rotation_cells=(("10", "1.5", "-2", "-4.5", "12", "40"), ZEROS),
        ),
    )

    expected_display_0 = [1, 10.0, 1.5 * ppm, -2 * ppm, -4.5, 12 * ppm, 40 * ppm]
    expected_display_1 = [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert isinstance(result, Staged)
    assert flatten(result.layout.perspective("desk")) == pytest.approx(
        [1, 0.0, -30.5 * ppm, 500 * ppm, *expected_display_0, *expected_display_1]
    )
