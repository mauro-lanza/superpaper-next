"""Saving a perspective from the dialog's fields."""

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
    form_from,
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
