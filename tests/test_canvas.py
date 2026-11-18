"""The pixel geometry of the desktop canvas and of its fit into the preview panel."""

import pytest

from superpaper.geometry import canvas
from superpaper.geometry.canvas import DisplayArea, PlacedDisplay
from superpaper.geometry.perspective import Perspective, Swivel, SwivelAxis, Tilt

TWO_AREAS = [
    DisplayArea((1920, 1080), (0, 0), (0, 0)),
    DisplayArea((1280, 1024), (1920, 0), (12, 70)),
]


def test_canvas_size_is_the_far_edges_of_the_crops():
    assert canvas.canvas_size([(0, 0, 100, 80), (100, 10, 200, 90)]) == (200, 90)


def test_canvas_size_includes_the_outer_bezels_when_given():
    crops = [(0, 0, 100, 80), (100, 10, 200, 90)]

    assert canvas.canvas_size_with_bezels(crops, [(5, 4), (12, 8)]) == (212, 98)


def test_the_canvas_of_ppi_normalised_crops_is_rounded_with_their_bezels():
    assert canvas.canvas_size_with_bezels([(0, 0, 100, 80)], [(0.4, 0.6)]) == (100, 81)


def test_points_are_moved_so_the_leftmost_and_topmost_are_at_zero():
    assert canvas.translate_to_origin([(5, 7), (3, 9)]) == [(2, 0), (0, 2)]


def test_points_already_at_the_origin_stay():
    assert canvas.translate_to_origin([(0, 0), (4.5, 2)]) == [(0, 0), (4.5, 2)]


def test_the_desktop_extent_has_the_bezels_only_when_asked_for():
    assert canvas.desktop_extent(TWO_AREAS) == (3200, 1080)
    assert canvas.desktop_extent_with_bezels(TWO_AREAS) == (3212, 1094)


def test_a_wide_canvas_fills_the_panel_width():
    size, position, scale = canvas.fit_to_panel((3840, 1080), (1080, 400))

    assert (size, position, scale) == ((972, 273), (54, 63), 0.253125)


def test_a_tall_canvas_fills_the_panel_height():
    size, position, scale = canvas.fit_to_panel((1000, 2000), (1080, 400))

    assert (size, position, scale) == ((180, 360), (450, 20), 0.18)


def test_displays_are_placed_on_the_canvas_at_the_scale_of_the_fit():
    placed = canvas.place_displays(TWO_AREAS, (54, 63), 0.25)

    assert placed == [((480, 270), (54, 63)), ((320, 256), (534, 63))]


def test_displays_with_bezels_are_placed_with_their_image_and_bezel_rectangles():
    areas = [DisplayArea((100, 50), (0, 0), (10, 0))]

    placed = canvas.place_displays_with_bezels(areas, (5, 5), 2)

    assert placed == [PlacedDisplay((220, 100), (5, 5), (200, 100), ((20, 100), (0, 0)))]


def test_a_group_of_displays_has_a_canvas_that_holds_them():
    group = [((100, 50), (10, 20)), ((100, 50), (110, 30))]

    assert canvas.group_canvas(group, (5, 5)) == ((195, 55), (15, 25))


def test_the_source_image_of_displays_without_perspective_is_their_canvas():
    assert canvas.source_size([(0, 0, 100, 80), (100, 10, 200, 90)], None) == (200, 90)


def test_a_swivelled_display_needs_a_larger_source_image_with_perspective():
    crops = [(0, 0, 100, 80), (100, 0, 200, 80)]
    flat = Perspective(
        "flat", 0, (0.0, 0.0, 400.0), (Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0),) * 2, (Tilt(0.0, 0.0, 0.0),) * 2
    )
    turned = Perspective(
        "turned",
        0,
        (0.0, 0.0, 400.0),
        (Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0), Swivel(SwivelAxis.LEFT, -40.0, 0.0, 0.0)),
        (Tilt(0.0, 0.0, 0.0),) * 2,
    )

    assert canvas.source_size(crops, flat) == (200, 80)
    assert canvas.source_size(crops, turned)[0] > 200


@pytest.mark.parametrize(
    ("size", "too_large"),
    [
        ((12000, 12000), False),
        ((12001, 10), True),
        ((10, 12001), True),
    ],
)
def test_a_perspective_canvas_over_12000_pixels_on_a_side_is_too_large(size, too_large):
    assert canvas.MAX_PERSPECTIVE_CANVAS == 12000
    assert canvas.exceeds_perspective_limit(size) is too_large
