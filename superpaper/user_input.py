"""Numbers typed by the user, in the editor's fields and on the command line.

Unlike the lenient reading of profile files, a value that can't be used is an error that
says which one, so that nothing is saved or shown from it.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

Offset = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Problems:
    """What keeps input from being saved, shown or deleted, for the user to fix."""

    messages: tuple[str, ...]


class OffsetError(ValueError):
    """A typed offset is not a pair of whole pixel numbers."""


def parse_offsets(fields: Sequence[str]) -> tuple[Offset, ...]:
    """Each display's "x,y" offset in pixels from its field; an empty field is 0,0.

    Raises OffsetError naming every display whose field can't be read.
    """
    offsets = []
    problems = []
    for display, text in enumerate(fields):
        offset = _parse_field(text)
        if offset is None:
            problems.append(f"Manual offset of display {display}: expected whole pixel numbers as x,y, not '{text}'.")
        else:
            offsets.append(offset)
    if problems:
        raise OffsetError("\n".join(problems))
    return tuple(offsets)


def _parse_field(text: str) -> Offset | None:
    if not text.strip():
        return (0, 0)
    parts = text.split(",")
    if len(parts) != 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def parse_float(text: str) -> float | None:
    """The finite number ``text`` spells, or None if it isn't one."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def parse_diagonals(texts: Sequence[str]) -> list[float] | None:
    """The diagonal sizes in inches ``texts`` spell, or None unless every one is a positive number."""
    entered = [parse_float(text) for text in texts]
    inches = [inch for inch in entered if inch is not None and inch > 0]
    return inches if inches and len(inches) == len(entered) else None


def parse_bezel(text: str) -> float | None:
    """The bezel thickness in millimetres ``text`` spells, or None unless it is a non-negative number."""
    value = parse_float(text)
    return value if value is not None and value >= 0 else None
