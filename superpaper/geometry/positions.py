"""Display positions as entered exactly, in millimetres or in pixels of the densest display."""

from collections.abc import Sequence

from superpaper.geometry import canvas
from superpaper.geometry.canvas import Point
from superpaper.geometry.displays import Layout
from superpaper.geometry.perspective import MM_PER_INCH
from superpaper.user_input import parse_float

Edges = tuple[float, float, float, float]
"""(left, top, right, bottom) of a display, bezels included at right and bottom."""


def mm_to_pixels(value: float, max_ppi: float) -> float:
    return value * (max_ppi / MM_PER_INCH)


def pixels_to_mm(value: float, max_ppi: float) -> float:
    return value * (1 / (max_ppi / MM_PER_INCH))


def edges_in_unit(layout: Layout, *, use_px: bool) -> list[Edges]:
    """The edges of each display measured from the top left of the displays' area, in the entry unit."""
    max_ppi = layout.max_ppi()

    def unit(pixels: float) -> float:
        return pixels if use_px else pixels_to_mm(pixels, max_ppi)

    crops = layout.ppi_norm_crops(len(layout.displays) * [(0, 0)])
    bezels = layout.ppi_norm_bezels()
    return [
        (unit(crop[0]), unit(crop[1]), unit(crop[2] + bezel[0]), unit(crop[3] + bezel[1]))
        for crop, bezel in zip(crops, bezels)
    ]


def convert_unit(text: str, max_ppi: float, *, to_px: bool) -> str:
    """The number ``text`` spells, converted between millimetres and pixels; empty stays empty.

    Raises ValueError if ``text`` is not a number.
    """
    if not text:
        return text
    value = float(text)
    return str(mm_to_pixels(value, max_ppi) if to_px else pixels_to_mm(value, max_ppi))


def parse_new_offsets(fields: Sequence[tuple[str, str]], max_ppi: float, *, use_px: bool) -> list[Point]:
    """The offsets in pixels that the (left, top) texts of each display give, with the
    leftmost display at x = 0 and the topmost at y = 0.

    Raises ValueError saying which value is wrong.
    """
    offsets = []
    for texts in fields:
        pixels = []
        for text in texts:
            value = parse_float(text)
            if value is None:
                if text:
                    message = f"Entered value '{text}' is not valid."
                else:
                    message = "Please enter a position for every display. Some value is empty."
                raise ValueError(message)
            pixels.append(value if use_px else mm_to_pixels(value, max_ppi))
        offsets.append((pixels[0], pixels[1]))
    return canvas.translate_to_origin(offsets)
