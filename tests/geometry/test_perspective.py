"""The perspectives of a layout and the choice between them."""

from dataclasses import replace

import pytest

from superpaper.geometry.perspective import (
    Default,
    DegeneratePerspective,
    Disabled,
    Named,
    Perspective,
    Swivel,
    SwivelAxis,
    Tilt,
    choice_label,
    get_backprojected_display_system,
    parse_choice,
)
from tests.geometry.conftest import DUAL_MONITORS, SAVED_COUCH, SAVED_DESK, detect


@pytest.mark.parametrize(
    ("text", "choice"),
    [("default", Default()), ("disabled", Disabled()), ("desk", Named("desk")), ("Default", Named("Default"))],
)
def test_a_perspective_choice_is_parsed_from_its_text_and_spelled_the_same_again(text, choice):
    assert parse_choice(text) == choice
    assert choice_label(choice) == text


@pytest.mark.parametrize(("axis", "angle"), [(SwivelAxis.LEFT, 99.5), (SwivelAxis.RIGHT, 80.5)])
def test_a_display_swiveled_edge_on_is_degenerate(axis, angle):
    perspective = Perspective("edge", 0, (0.0, 0.0, 300.0), (Swivel(axis, angle, 0.0, 0.0),), (Tilt(0.0, 0.0, 0.0),))

    with pytest.raises(DegeneratePerspective, match="edge-on"):
        get_backprojected_display_system([(0, 0, 100, 60)], perspective)


def test_a_flat_perspective_maps_each_display_onto_itself():
    crops = [(0, 0, 100, 80), (100, 10, 200, 90)]
    flat = Perspective(
        "flat", 0, (0.0, 0.0, 400.0), (Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0),) * 2, (Tilt(0.0, 0.0, 0.0),) * 2
    )

    plane_crops, coefficients = get_backprojected_display_system(crops, flat)

    assert plane_crops == crops
    for (left, top, right, bottom), (a, b, c, d, e, f, g, h) in zip(crops, coefficients, strict=True):
        for x, y in [(left, top), (right, top), (right, bottom), (left, bottom)]:
            w = g * x + h * y + 1
            assert ((a * x + b * y + c) / w, (d * x + e * y + f) / w) == pytest.approx((x, y))


def test_perspective_choices_pick_the_perspective_they_mean(saved_layouts):
    layout = detect(saved_layouts, DUAL_MONITORS)

    assert layout.perspective_for(Default()) is layout.perspective("desk")
    assert layout.perspective_for(Named("couch")) is layout.perspective("couch")
    assert layout.perspective_for(Disabled()) is None
    assert layout.perspective_for(Named("gone")) is None
    assert layout.without_perspective("desk").perspective_for(Default()) is None


def test_adding_a_perspective_keeps_the_order_and_replaces_one_of_the_same_name(saved_layouts):
    layout = detect(saved_layouts, DUAL_MONITORS)
    renamed_viewer = replace(SAVED_DESK, viewer_pos=(0.0, 0.0, 1.0))
    new = replace(SAVED_DESK, name="new")

    replaced = layout.with_perspective(renamed_viewer, use_perspective=True, is_default=False)
    added = layout.with_perspective(new, use_perspective=True, is_default=True)

    assert replaced.perspectives == (renamed_viewer, SAVED_COUCH)
    assert replaced.default_perspective is None
    assert added.perspective_names() == ["desk", "couch", "new"]
    assert added.default_perspective == "new"
