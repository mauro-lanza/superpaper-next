"""Numbers typed by the user, in the editor's fields and on the command line.

Unlike the lenient reading of profile files, a value that can't be used is an error that
says which one, so that nothing is saved or shown from it.
"""

import math
from dataclasses import dataclass

Offset = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Problems:
    """What keeps input from being saved, shown or deleted, for the user to fix."""

    messages: tuple[str, ...]


class OffsetError(ValueError):
    """A typed offset is not a pair of whole pixel numbers."""


def parse_float(text: str) -> float | None:
    """The finite number ``text`` spells, or None if it isn't one."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None
