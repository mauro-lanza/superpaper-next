"""The ``key+key`` text of a hotkey, as the settings and profile files and the dialogs write it."""


def parse_hotkey(text: str) -> tuple[str, ...] | None:
    """The keys of a ``key+key`` hotkey text, or None if it is blank."""
    text = text.strip()
    return tuple(text.split("+")) if text else None


def format_hotkey(keys: tuple[str, ...] | None) -> str:
    """The ``key+key`` text of a hotkey; empty if there is none."""
    return "+".join(keys or ())
