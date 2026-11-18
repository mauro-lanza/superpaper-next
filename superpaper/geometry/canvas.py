"""Pixel geometry of the desktop canvas: its size, how it is fitted into the preview panel,
and where the displays sit on it. Pure functions of numbers, so the UI only draws.

A crop is (left, top, right, bottom) of one display on a canvas.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from superpaper.geometry.perspective import Perspective, get_backprojected_display_system

MAX_PERSPECTIVE_CANVAS = 12000
"""The largest side, in pixels, of the intermediate image of a perspective correction that is
accepted without asking: a larger one can use enough memory to crash the system."""

PANEL_FILL = 0.9
"""How much of the preview panel the longer edge of the canvas fills."""

Point = tuple[float, float]
PixelPoint = tuple[int, int]
"""A size or position in panel pixels, which are whole."""
Crop = tuple[float, float, float, float]
"""(left, top, right, bottom). Values are pixels, whole or fractional; ints satisfy float."""


@dataclass(frozen=True, slots=True)
class DisplayArea:
    """A display on a canvas: its size and position, and the (right, bottom) bezel it carries."""

    resolution: Point
    offset: Point
    bezels: Point


def canvas_size(crops: Sequence[Crop]) -> tuple[int, int]:
    """The size of the canvas that holds ``crops``, anchored at (0, 0)."""
    return canvas_size_with_bezels(crops, [(0, 0)] * len(crops))


def canvas_size_with_bezels(crops: Sequence[Crop], bezels: Sequence[Point]) -> tuple[int, int]:
    """The size of the canvas that holds ``crops`` and their outer bezels (one (right, bottom)
    per crop), so that a render is as large as the preview shows it."""
    right = max(round(crop[2] + bezel[0]) for crop, bezel in zip(crops, bezels))
    bottom = max(round(crop[3] + bezel[1]) for crop, bezel in zip(crops, bezels))
    return (right, bottom)


def source_size(crops: Sequence[Crop], perspective: Perspective | None) -> tuple[int, int]:
    """The size of the image that fills ``crops`` exactly, which with a ``perspective`` is the
    canvas of the displays back-projected onto the image plane."""
    if perspective is None:
        return canvas_size(crops)
    projected_crops, _ = get_backprojected_display_system(crops, perspective)
    return canvas_size(projected_crops)


def exceeds_perspective_limit(size: tuple[int, int]) -> bool:
    return size[0] > MAX_PERSPECTIVE_CANVAS or size[1] > MAX_PERSPECTIVE_CANVAS


def translate_to_origin(points: Sequence[Point]) -> list[Point]:
    """``points`` moved so that the leftmost is at x = 0 and the topmost at y = 0."""
    leftmost = min(point[0] for point in points)
    topmost = min(point[1] for point in points)
    return [(point[0] - leftmost, point[1] - topmost) for point in points]


def desktop_extent(areas: Sequence[DisplayArea]) -> Point:
    """The right and bottom edges of the displays, without bezels."""
    return (
        max(area.resolution[0] + area.offset[0] for area in areas),
        max(area.resolution[1] + area.offset[1] for area in areas),
    )


def desktop_extent_with_bezels(areas: Sequence[DisplayArea]) -> Point:
    """The right and bottom edges of the displays, with their bezels."""
    return (
        max(area.resolution[0] + area.offset[0] + area.bezels[0] for area in areas),
        max(area.resolution[1] + area.offset[1] + area.bezels[1] for area in areas),
    )


def fit_to_panel(canvas: Point, panel_size: Sequence[float]) -> tuple[PixelPoint, PixelPoint, float]:
    """Where a canvas of size ``canvas`` goes in a panel: (its size, its top left corner, the
    scale from canvas to panel pixels). The longer edge fills PANEL_FILL of the panel."""
    gap = (1 - PANEL_FILL) / 2
    panel_width, panel_height = panel_size[0], panel_size[1]
    if canvas[0] / canvas[1] > panel_width / panel_height:
        new_width = PANEL_FILL * panel_width
        scale = new_width / canvas[0]
        new_height = scale * canvas[1]
        left = gap * panel_width
        top = (panel_height - new_height) / 2
    else:
        new_height = PANEL_FILL * panel_height
        scale = new_height / canvas[1]
        new_width = scale * canvas[0]
        left = (panel_width - new_width) / 2
        top = gap * panel_height
    return ((round(new_width), round(new_height)), (round(left), round(top)), scale)


def place_displays(
    areas: Sequence[DisplayArea], canvas_pos: PixelPoint, scale: float
) -> list[tuple[PixelPoint, PixelPoint]]:
    """Each display's (size, position) in the panel, for a canvas at ``canvas_pos`` drawn at ``scale``."""
    return [
        (
            (round(area.resolution[0] * scale), round(area.resolution[1] * scale)),
            (round(area.offset[0] * scale) + canvas_pos[0], round(area.offset[1] * scale) + canvas_pos[1]),
        )
        for area in areas
    ]


@dataclass(frozen=True, slots=True)
class PlacedDisplay:
    """A display in the panel: its size with bezels and position, its image's size alone, and
    its (right, bottom) bezel rectangles, (0, 0) where there is no bezel."""

    size: PixelPoint
    position: PixelPoint
    image_size: PixelPoint
    bezel_rects: tuple[PixelPoint, PixelPoint]


def place_displays_with_bezels(
    areas: Sequence[DisplayArea], canvas_pos: PixelPoint, scale: float
) -> list[PlacedDisplay]:
    """Like place_displays, with each size including the bezels."""
    placed = []
    for area in areas:
        res = area.resolution
        bez = area.bezels
        right_bezel = (round(scale * bez[0]), round(scale * (res[1] + bez[1]))) if bez[0] != 0 else (0, 0)
        bottom_bezel = (round(scale * res[0]), round(scale * bez[1])) if bez[1] != 0 else (0, 0)
        placed.append(
            PlacedDisplay(
                size=(round(scale * (res[0] + bez[0])), round(scale * (res[1] + bez[1]))),
                position=(round(scale * area.offset[0]) + canvas_pos[0], round(scale * area.offset[1]) + canvas_pos[1]),
                image_size=(round(scale * res[0]), round(scale * res[1])),
                bezel_rects=(right_bezel, bottom_bezel),
            )
        )
    return placed


def group_canvas(
    sizes_positions: Sequence[tuple[PixelPoint, PixelPoint]], major_canvas_pos: PixelPoint
) -> tuple[PixelPoint, PixelPoint]:
    """The (size, position) of the canvas that holds a group of displays given as (size, position)."""
    pos = (
        round(min(position[0] for _, position in sizes_positions) + major_canvas_pos[0]),
        round(min(position[1] for _, position in sizes_positions) + major_canvas_pos[1]),
    )
    size = (
        round(max(size[0] + position[0] for size, position in sizes_positions) - pos[0]),
        round(max(size[1] + position[1] for size, position in sizes_positions) - pos[1]),
    )
    return size, pos
