"""The perspectives of a layout and the choice between them."""

from dataclasses import replace

import pytest

from superpaper.geometry.perspective import (
    Default,
    Disabled,
    Named,
    Perspective,
    Swivel,
    SwivelAxis,
    Tilt,
    choice_label,
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


def test_a_perspective_can_be_cut_down_to_some_displays():
    swivels = tuple(Swivel(SwivelAxis(i), float(i), 0.0, 0.0) for i in range(3))
    tilts = tuple(Tilt(float(i), 0.0, 0.0) for i in range(3))
    perspective = Perspective("desk", 0, (0.0, 0.0, 1.0), swivels, tilts)

    cut = perspective.of_displays([2, 0])

    assert (cut.swivels, cut.tilts) == ((swivels[2], swivels[0]), (tilts[2], tilts[0]))
    assert (cut.name, cut.central_display, cut.viewer_pos) == ("desk", 0, (0.0, 0.0, 1.0))


def test_perspective_choices_pick_the_perspective_they_mean(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)

    assert layout.perspective_for(Default()) is layout.perspective("desk")
    assert layout.perspective_for(Named("couch")) is layout.perspective("couch")
    assert layout.perspective_for(Disabled()) is None
    assert layout.perspective_for(Named("gone")) is None
    assert layout.without_perspective("desk").perspective_for(Default()) is None


def test_adding_a_perspective_keeps_the_order_and_replaces_one_of_the_same_name(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)
    renamed_viewer = replace(SAVED_DESK, viewer_pos=(0.0, 0.0, 1.0))
    new = replace(SAVED_DESK, name="new")

    replaced = layout.with_perspective(renamed_viewer, use_perspective=True, is_default=False)
    added = layout.with_perspective(new, use_perspective=True, is_default=True)

    assert replaced.perspectives == (renamed_viewer, SAVED_COUCH)
    assert replaced.default_perspective is None
    assert added.perspective_names() == ["desk", "couch", "new"]
    assert added.default_perspective == "new"
