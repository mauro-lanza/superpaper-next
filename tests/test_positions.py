"""The rules of the position entry, the layout editor and the display settings band."""

import pytest

from superpaper.geometry import canvas, positions, units
from superpaper.geometry.canvas import DisplayArea
from superpaper.geometry.layout_edit import parse_bezel, parse_diagonals


def test_units_convert_between_millimetres_and_pixels(layout):
    ppi = layout.max_ppi()
    assert units.mm_to_pixels(25.4, ppi) == pytest.approx(ppi)
    assert units.pixels_to_mm(ppi, ppi) == pytest.approx(25.4)


def test_the_edges_of_each_display_include_the_bezels_at_right_and_bottom(layout):
    bezeled = layout.with_bezels([(0.0, 0.0), (0.0, 0.0)]).with_offsets([(0, 0), (1920, 0)])

    edges = positions.edges_in_unit(bezeled, use_px=True)

    assert edges == pytest.approx([(0, 0, 1920, 1080), (1920, 0, 3840, 1080)], abs=1)


def test_edges_in_millimetres_scale_by_the_densest_display(layout):
    px = positions.edges_in_unit(layout, use_px=True)
    mm = positions.edges_in_unit(layout, use_px=False)

    assert mm[1] == pytest.approx([edge * 25.4 / layout.max_ppi() for edge in px[1]])


def test_a_typed_unit_conversion_keeps_an_empty_field_empty(layout):
    ppi = layout.max_ppi()
    assert positions.convert_unit("", ppi, to_px=True) == ""
    assert float(positions.convert_unit("25.4", ppi, to_px=True)) == pytest.approx(ppi)
    assert float(positions.convert_unit(str(ppi), ppi, to_px=False)) == pytest.approx(25.4)


def test_a_typed_unit_conversion_of_a_non_number_raises(layout):
    with pytest.raises(ValueError, match="could not convert"):
        positions.convert_unit("abc", layout.max_ppi(), to_px=True)


def test_new_offsets_are_moved_to_the_origin_in_pixels():
    assert positions.parse_new_offsets([("10", "20"), ("110", "5")], 100.0, use_px=True) == [(0, 15), (100, 0)]


def test_new_offsets_in_millimetres_are_converted_at_the_densest_ppi():
    offsets = positions.parse_new_offsets([("0", "0"), ("25.4", "0")], 100.0, use_px=False)

    assert offsets == pytest.approx([(0, 0), (100, 0)])


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ([("1", "x")], "Entered value 'x' is not valid."),
        ([("1", "nan")], "Entered value 'nan' is not valid."),
        ([("1", "2"), ("", "3")], "Please enter a position for every display. Some value is empty."),
    ],
)
def test_new_offsets_that_cannot_be_read_say_which_value(fields, message):
    with pytest.raises(ValueError, match=message):
        positions.parse_new_offsets(fields, 100.0, use_px=True)


AREAS = [DisplayArea((1000, 500), (0, 0), (0, 0)), DisplayArea((1000, 500), (1000, 0), (0, 0))]


def test_dragged_displays_scale_up_to_the_true_canvas_and_anchor_at_the_origin():
    offsets = canvas.dragged_offsets([(110, 60), (210, 60)], AREAS, 200)

    assert offsets == [(0, 0), (1000, 0)]


def test_resetting_places_the_displays_as_they_are_drawn_in_the_panel():
    _, canvas_pos, scale = canvas.fit_to_panel(canvas.desktop_extent_with_bezels(AREAS), (500, 400))
    expected = [display.position for display in canvas.place_displays_with_bezels(AREAS, canvas_pos, scale)]

    assert canvas.initial_shape_positions(AREAS, (500, 400)) == expected


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
