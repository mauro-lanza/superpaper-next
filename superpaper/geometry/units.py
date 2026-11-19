"""Conversions between millimetres and pixels."""

MM_PER_INCH = 25.4


def mm_to_pixels(value: float, max_ppi: float) -> float:
    return value * max_ppi / MM_PER_INCH


def pixels_to_mm(value: float, max_ppi: float) -> float:
    return value * MM_PER_INCH / max_ppi
