"""Display positions as entered exactly, in millimetres or in pixels of the densest display."""

from collections.abc import Sequence

from superpaper.geometry import canvas
from superpaper.geometry.canvas import Point
from superpaper.geometry.displays import MM_PER_INCH, Layout
from superpaper.user_input import parse_float

Edges = tuple[float, float, float, float]
"""(left, top, right, bottom) of a display, bezels included at right and bottom."""


def to_pixels(value: float, max_ppi: float, *, use_px: bool) -> float:
    """``value`` in the entry unit (pixels if ``use_px``, else millimetres) as pixels."""
    return value * (1 if use_px else max_ppi / MM_PER_INCH)


def from_pixels(value: float, max_ppi: float, *, use_px: bool) -> float:
    """Pixels ``value`` in the entry unit (pixels if ``use_px``, else millimetres)."""
    return value * (1 if use_px else 1 / (max_ppi / MM_PER_INCH))


def edges_in_unit(layout: Layout, *, use_px: bool) -> list[Edges]:
    """The edges of each display measured from the top left of the displays' area, in the entry unit."""
    max_ppi = layout.max_ppi()

    def unit(pixels: float) -> float:
        return from_pixels(pixels, max_ppi, use_px=use_px)

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
    return str(to_pixels(value, max_ppi, use_px=False) if to_px else from_pixels(value, max_ppi, use_px=False))


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
            pixels.append(to_pixels(value, max_ppi, use_px=use_px))
        offsets.append((pixels[0], pixels[1]))
    return canvas.translate_to_origin(offsets)
