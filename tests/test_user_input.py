import pytest

from superpaper.user_input import OffsetError, parse_float, parse_offset_args, parse_offsets


def test_offsets_are_read_from_x_comma_y_fields():
    assert parse_offsets(["10,-20", " 3 , 4 ", "0,0"]) == ((10, -20), (3, 4), (0, 0))


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_offset_field_means_no_offset(empty):
    assert parse_offsets(["1,2", empty]) == ((1, 2), (0, 0))


def test_no_fields_give_no_offsets():
    assert parse_offsets([]) == ()


@pytest.mark.parametrize("text", ["1", "1,2,3", "1;2", "1,x", "1.5,2", ",2", "1,"])
def test_a_field_that_is_not_a_pair_of_whole_numbers_is_an_error_naming_the_display(text):
    with pytest.raises(OffsetError, match=rf"display 1: .*'{text}'"):
        parse_offsets(["0,0", text])


def test_every_unreadable_field_is_named():
    with pytest.raises(OffsetError) as error:
        parse_offsets(["a,b", "1,2", "3"])

    assert str(error.value).splitlines() == [
        "Manual offset of display 0: expected whole pixel numbers as x,y, not 'a,b'.",
        "Manual offset of display 2: expected whole pixel numbers as x,y, not '3'.",
    ]


def test_command_line_offsets_pair_up_x_and_y_for_each_display():
    assert parse_offset_args(["1", "2", "-3", "4"]) == ((1, 2), (-3, 4))
    assert parse_offset_args([]) == ()


def test_command_line_offsets_must_come_in_pairs():
    with pytest.raises(OffsetError, match="not even"):
        parse_offset_args(["1", "2", "3"])


def test_command_line_offsets_must_be_whole_numbers():
    with pytest.raises(OffsetError, match="whole numbers of pixels: 1 x"):
        parse_offset_args(["1", "x"])


@pytest.mark.parametrize(("text", "value"), [("1.5", 1.5), (" -2 ", -2.0), ("0", 0.0), ("1e3", 1000.0)])
def test_a_number_is_parsed(text, value):
    assert parse_float(text) == value


@pytest.mark.parametrize("text", ["", "x", "1,5", "nan", "inf", "-inf"])
def test_something_that_is_not_a_finite_number_is_none(text):
    assert parse_float(text) is None
