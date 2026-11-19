import re

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
from superpaper.geometry.perspective_form import (
    check_new_perspective_name,
    parse_rotations_mm,
    parse_viewer_offsets_mm,
    perspective_from_mm,
)
from superpaper.profiles import profile_file


@pytest.mark.parametrize("name", ["default", "DEFAULT", "Default", "disabled", "Disabled", "None", "none", "NONE"])
def test_reserved_perspective_names_are_rejected(name):
    with pytest.raises(ValueError, match="reserved"):
        check_new_perspective_name(name)


@pytest.mark.parametrize("name", ["desk", "defaults", "none of them", "My default"])
def test_other_perspective_names_are_accepted(name):
    check_new_perspective_name(name)


@pytest.mark.parametrize(
    ("text", "choice"),
    [("default", Default()), ("disabled", Disabled()), ("desk", Named("desk")), ("Default", Named("Default"))],
)
def test_a_perspective_choice_is_parsed_from_its_text_and_spelled_the_same_again(text, choice):
    assert parse_choice(text) == choice
    assert choice_label(choice) == text


@pytest.mark.parametrize("text", ["default", "disabled", "desk"])
def test_a_profile_file_keeps_its_perspective_choice(text):
    profile = profile_file.parse(f"name=p\nperspective={text}\ndisplay0paths=/a.png\n")

    assert profile.perspective == parse_choice(text)
    assert f"perspective={text}\n" in profile_file.serialize(profile)


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


def test_a_perspective_can_be_cut_down_to_some_displays():
    swivels = tuple(Swivel(SwivelAxis(i), float(i), 0.0, 0.0) for i in range(3))
    tilts = tuple(Tilt(float(i), 0.0, 0.0) for i in range(3))
    perspective = Perspective("desk", 0, (0.0, 0.0, 1.0), swivels, tilts)

    cut = perspective.of_displays([2, 0])

    assert (cut.swivels, cut.tilts) == ((swivels[2], swivels[0]), (tilts[2], tilts[0]))
    assert (cut.name, cut.central_display, cut.viewer_pos) == ("desk", 0, (0.0, 0.0, 1.0))


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
@pytest.mark.parametrize("text", ["", "1,5", "ten", "nan"])
def test_a_grid_cell_that_is_not_a_number_is_named_by_display_and_column(column, name, text):
    row = ["0"] * 6
    row[column] = text

    with pytest.raises(ValueError, match=rf"Display 1, '{re.escape(name)}': '{text}' is not a number") as error:
        parse_rotations_mm([0, 0], [["0"] * 6, row])

    assert "separate decimals with a point" in str(error.value)


def test_viewer_offsets_are_read_in_millimetres():
    assert parse_viewer_offsets_mm(["0", "-30.5", "500"]) == [0.0, -30.5, 500.0]


@pytest.mark.parametrize("texts", [["", "0", "500"], ["0", "x", "500"], ["0", "0", "1,5"]])
def test_a_viewer_offset_that_is_not_a_number_is_an_error(texts):
    with pytest.raises(ValueError, match="lengths in millimetres"):
        parse_viewer_offsets_mm(texts)


@pytest.mark.parametrize("distance", ["0", "-1"])
def test_the_viewer_distance_must_be_positive(distance):
    with pytest.raises(ValueError, match="Viewer distance must be entered and positive"):
        parse_viewer_offsets_mm(["0", "0", distance])
