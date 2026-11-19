import pytest

from superpaper.user_input import parse_float


@pytest.mark.parametrize(("text", "value"), [("1.5", 1.5), (" -2 ", -2.0), ("0", 0.0), ("1e3", 1000.0)])
def test_a_number_is_parsed(text, value):
    assert parse_float(text) == value


@pytest.mark.parametrize("text", ["", "x", "1,5", "nan", "inf", "-inf"])
def test_something_that_is_not_a_finite_number_is_none(text):
    assert parse_float(text) is None
