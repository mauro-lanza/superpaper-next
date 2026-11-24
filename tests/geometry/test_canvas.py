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


@pytest.mark.parametrize(
    ("crops", "bezels", "size"),
    [
        ([(0, 0, 100, 80), (100, 10, 200, 90)], [(5, 4), (12, 8)], (212, 98)),
        ([(0, 0, 100, 80)], [(0.4, 0.6)], (100, 81)),
    ],
)
def test_canvas_size_includes_the_outer_bezels_rounded(crops, bezels, size):
    assert canvas.canvas_size_with_bezels(crops, bezels) == size


def test_points_are_moved_so_the_leftmost_and_topmost_are_at_zero():
    assert canvas.translate_to_origin([(5, 7), (3, 9)]) == [(2, 0), (0, 2)]


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

    assert canvas.group_canvas(group) == ((200, 60), (10, 20))


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

    assert canvas.source_size(crops, None) == (200, 80)
    assert canvas.source_size(crops, flat) == (200, 80)
    assert canvas.source_size(crops, turned)[0] > 200


@pytest.mark.parametrize(
    ("excess", "too_large"),
    [
        ((0, 0), False),
        ((1, -10), True),
        ((-10, 1), True),
    ],
)
def test_a_perspective_canvas_over_the_limit_on_a_side_is_too_large(excess, too_large):
    size = (canvas.MAX_PERSPECTIVE_CANVAS + excess[0], canvas.MAX_PERSPECTIVE_CANVAS + excess[1])

    assert canvas.exceeds_perspective_limit(size) is too_large


AREAS = [DisplayArea((1000, 500), (0, 0), (0, 0)), DisplayArea((1000, 500), (1000, 0), (0, 0))]


def test_dragged_displays_scale_up_to_the_true_canvas_and_anchor_at_the_origin():
    offsets = canvas.dragged_offsets([(110, 60), (210, 60)], AREAS, 200)

    assert offsets == [(0, 0), (1000, 0)]


def test_resetting_places_the_displays_as_they_are_drawn_in_the_panel():
    _, canvas_pos, scale = canvas.fit_to_panel(canvas.desktop_extent_with_bezels(AREAS), (500, 400))
    expected = [display.position for display in canvas.place_displays_with_bezels(AREAS, canvas_pos, scale)]

    assert canvas.initial_shape_positions(AREAS, (500, 400)) == expected
