"""The ``key+key`` text of a hotkey, as the settings and profile files and the dialogs write it."""

from collections.abc import Iterable

# The modifiers system_hotkey accepts, in the order it registers them.
_MODIFIERS = ("control", "shift", "alt", "super")


def parse_hotkey(text: str) -> tuple[str, ...] | None:
    """The keys of a ``key+key`` hotkey text, lower-cased and trimmed, with the modifiers in
    system_hotkey's order, or None if it is blank. Hotkeys that press the same keys parse alike."""
    text = text.strip()
    if not text:
        return None
    *modifiers, key = (part.strip().lower() for part in text.split("+"))
    modifiers.sort(key=lambda modifier: _MODIFIERS.index(modifier) if modifier in _MODIFIERS else len(_MODIFIERS))
    return (*modifiers, key)


def format_hotkey(keys: tuple[str, ...] | None) -> str:
    """The ``key+key`` text of a hotkey; empty if there is none."""
    return "+".join(keys or ())


def unparsable_problem(text: str) -> str | None:
    """Why the hotkey ``text`` can't be read as keys joined by ``+``; None if it can, or is blank."""
    keys = parse_hotkey(text)
    if keys is not None and not all(keys):
        return f"The hotkey '{text.strip()}' is not valid: write keys joined by '+', such as control+super+x."
    return None


def clash_problem(keys: tuple[str, ...] | None, others: Iterable[tuple[str, tuple[str, ...] | None]]) -> str | None:
    """The message naming every one of the ``others`` (what uses it, its keys) that has the
    same ``keys``; None if none does."""
    if keys is None:
        return None
    users = [user for user, other in others if other == keys]
    if not users:
        return None
    return f"The hotkey '{format_hotkey(keys)}' is already used by {' and '.join(users)}."
