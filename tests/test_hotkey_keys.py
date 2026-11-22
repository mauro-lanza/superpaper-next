"""The key+key hotkey text."""

import pytest

from superpaper.hotkey_keys import clash_problem, format_hotkey, parse_hotkey, unparsable_problem


def test_hotkey_text_round_trips():
    keys = ("control", "super", "w")
    assert format_hotkey(keys) == "control+super+w"
    assert parse_hotkey("control+super+w") == keys


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_hotkey_text_is_no_hotkey(text):
    assert parse_hotkey(text) is None
    assert format_hotkey(None) == ""
    assert format_hotkey(()) == ""


@pytest.mark.parametrize(
    "text", ["  Control+W \n", "control + w", "CONTROL+w", "Control +W"], ids=["case", "spaces", "upper", "mixed"]
)
def test_hotkey_text_is_normalised(text):
    assert parse_hotkey(text) == ("control", "w")


def test_modifier_order_does_not_matter():
    assert parse_hotkey("super+alt+shift+control+x") == ("control", "shift", "alt", "super", "x")
    assert parse_hotkey("alt+control+x") == parse_hotkey("control+ALT+x")


def test_variants_of_one_hotkey_clash():
    taken = [("profile 'A'", parse_hotkey("control+shift+x")), ("profile 'B'", parse_hotkey("Shift + Control+X"))]
    message = clash_problem(parse_hotkey("SHIFT+control+x"), taken)
    assert message == "The hotkey 'control+shift+x' is already used by profile 'A' and profile 'B'."
    assert clash_problem(parse_hotkey("control+y"), taken) is None
    assert clash_problem(None, taken) is None


def test_empty_keys_are_unparsable():
    assert unparsable_problem("control++x")
    assert unparsable_problem("control+")
    assert unparsable_problem("control + x") is None
    assert unparsable_problem("  ") is None
