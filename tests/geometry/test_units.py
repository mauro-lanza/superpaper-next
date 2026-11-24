import pytest

from superpaper.geometry import units


def test_units_convert_between_millimetres_and_pixels():
    ppi = 96.0
    assert units.mm_to_pixels(25.4, ppi) == pytest.approx(ppi)
    assert units.pixels_to_mm(ppi, ppi) == pytest.approx(25.4)
