"""The key+key hotkey text."""

import pytest

from superpaper.hotkey_keys import format_hotkey, parse_hotkey


def test_hotkey_text_round_trips():
    keys = ("control", "super", "w")
    assert format_hotkey(keys) == "control+super+w"
    assert parse_hotkey("control+super+w") == keys


@pytest.mark.parametrize("text", ["", "   "])
def test_blank_hotkey_text_is_no_hotkey(text):
    assert parse_hotkey(text) is None
    assert format_hotkey(None) == ""
    assert format_hotkey(()) == ""


def test_hotkey_text_is_trimmed_around_but_not_within_and_keeps_case():
    assert parse_hotkey("  Control+W \n") == ("Control", "W")
    assert parse_hotkey("control + w") == ("control ", " w")
