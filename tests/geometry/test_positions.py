"""The rules of the position entry."""

import pytest

from superpaper.geometry import positions


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
