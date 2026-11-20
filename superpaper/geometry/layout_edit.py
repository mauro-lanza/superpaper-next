"""The rules of editing a layout in the preview: the positions and bezel tools, which can be
saved or cancelled, and the display settings band's unsaved changes.

Each transition takes the state and the layout and returns the new state and layout; the
caller keeps both and does the drawing.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from superpaper.geometry import display_store
from superpaper.geometry.canvas import Point
from superpaper.geometry.display_store import SaveFailed
from superpaper.geometry.displays import Layout
from superpaper.user_input import Problems, parse_float


@dataclass(frozen=True, slots=True)
class Idle:
    pass


@dataclass(frozen=True, slots=True)
class ConfiguringPositions:
    """Displays are being dragged; ``offsets`` are those to restore on cancel."""

    offsets: tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class ConfiguringBezels:
    """Bezels are being set; ``bezels_mm`` and ``offsets`` are those to restore on cancel."""

    bezels_mm: tuple[Point, ...]
    offsets: tuple[Point, ...]


EditState = Idle | ConfiguringPositions | ConfiguringBezels

MIN_DIAGONAL_INCHES = 1
MAX_DIAGONAL_INCHES = 1000
_DIAGONAL = re.compile(r"[0-9]+(?:[.,][0-9]+)?")
OVERLAP_MESSAGE = "The displays overlap. Move them apart before pressing Done."
REARRANGED_MESSAGE = "The displays could not be kept where they were without overlapping, so they were arranged afresh."


@dataclass(frozen=True, slots=True)
class Resized:
    """A layout made valid after its displays changed size, and whether all were arranged afresh."""

    layout: Layout
    rearranged_all: bool


def start_positions(state: EditState, layout: Layout) -> ConfiguringPositions:
    """Begin positioning the displays. Raises ValueError unless idle."""
    _require_idle(state)
    return ConfiguringPositions(layout.ppi_norm_offsets)


def save_positions(
    state: EditState, layout: Layout, dragged_offsets: Sequence[Point] | None
) -> tuple[Idle, Layout] | Problems:
    """Keep the positions: ``dragged_offsets`` if the displays were dragged, else the layout
    as it is; a message instead if the displays overlap there.

    Raises ValueError unless positioning.
    """
    match state:
        case ConfiguringPositions():
            placed = layout if dragged_offsets is None else layout.with_offsets(dragged_offsets)
            return (Idle(), placed) if placed.is_valid() else Problems((OVERLAP_MESSAGE,))
        case Idle() | ConfiguringBezels():
            raise WrongState(state, ConfiguringPositions)
        case _:
            assert_never(state)


def cancel_positions(state: EditState, layout: Layout) -> tuple[Idle, Layout]:
    """Put the displays back where they were when positioning began. Raises ValueError unless positioning."""
    match state:
        case ConfiguringPositions(offsets):
            return Idle(), layout.with_offsets(offsets)
        case Idle() | ConfiguringBezels():
            raise WrongState(state, ConfiguringPositions)
        case _:
            assert_never(state)


def start_bezels(state: EditState, layout: Layout) -> ConfiguringBezels:
    """Begin setting the bezels. Raises ValueError unless idle."""
    _require_idle(state)
    return ConfiguringBezels(tuple(layout.bezels_in_mm()), layout.ppi_norm_offsets)


def save_bezels(state: EditState, layout: Layout) -> tuple[Idle, Layout]:
    """Keep the bezels set so far. Raises ValueError unless setting bezels."""
    match state:
        case ConfiguringBezels():
            return Idle(), layout
        case Idle() | ConfiguringPositions():
            raise WrongState(state, ConfiguringBezels)
        case _:
            assert_never(state)


def cancel_bezels(state: EditState, layout: Layout) -> tuple[Idle, Layout]:
    """Put the bezels and positions back as they were when setting began. Raises ValueError unless setting bezels."""
    match state:
        case ConfiguringBezels(bezels_mm, offsets):
            return Idle(), layout.with_bezels(bezels_mm).with_offsets(offsets)
        case Idle() | ConfiguringPositions():
            raise WrongState(state, ConfiguringBezels)
        case _:
            assert_never(state)


def save_display_settings(config_dir: Path, layout: Layout) -> SaveFailed | None:
    """Write the display settings of ``layout`` to ``config_dir``; why that failed, or None."""
    return display_store.save_or_failure(display_store.save_layout, config_dir, layout, "display settings")


def with_entered_diagonals(layout: Layout, texts: Sequence[str]) -> Resized | None:
    """The layout with the diagonals the field ``texts`` spell, made valid, or None while they aren't all valid."""
    inches = parse_diagonals(texts)
    return None if inches is None else fit_resized(layout.with_diagonals(inches))


def fit_resized(layout: Layout) -> Resized:
    """``layout``, whose displays changed size, without overlaps: only the displays that overlap
    are shifted, and if that doesn't resolve it all are arranged afresh."""
    if layout.is_valid():
        return Resized(layout, rearranged_all=False)
    shifted = layout.with_overlaps_shifted()
    if shifted is not None:
        return Resized(shifted, rearranged_all=False)
    return Resized(layout.with_initial_offsets(), rearranged_all=True)


def parse_diagonal(text: str) -> float | None:
    """The diagonal size in inches ``text`` spells as digits with an optional decimal point
    or comma, or None unless it is a number from 1 to 1000."""
    match = _DIAGONAL.fullmatch(text.strip())
    if match is None:
        return None
    inches = float(text.strip().replace(",", "."))
    return inches if MIN_DIAGONAL_INCHES <= inches <= MAX_DIAGONAL_INCHES else None


def parse_diagonals(texts: Sequence[str]) -> list[float] | None:
    """The diagonal sizes in inches ``texts`` spell, or None unless every one is valid."""
    inches = [parse_diagonal(text) for text in texts]
    return [inch for inch in inches if inch is not None] if inches and None not in inches else None


def parse_bezel(text: str) -> float | None:
    """The bezel thickness in millimetres ``text`` spells, or None unless it is a non-negative number."""
    value = parse_float(text)
    return value if value is not None and value >= 0 else None


def with_entered_bezels(layout: Layout, entered: Sequence[tuple[str, str]]) -> Layout | Problems:
    """The layout with the (right, bottom) bezel thicknesses the field texts of each display
    spell, in millimetres; else a message for each text that isn't a valid thickness."""
    messages: list[str] = []
    bezels: list[Point] = []
    for right_text, bottom_text in entered:
        right, bottom = parse_bezel(right_text), parse_bezel(bottom_text)
        for text, thickness in ((right_text, right), (bottom_text, bottom)):
            if thickness is None:
                messages.append(f"Bezel thickness must be a non-negative number, '{text}' was entered.")
        if right is not None and bottom is not None:
            bezels.append((right, bottom))
    return Problems(tuple(messages)) if messages else layout.with_bezels(bezels)


def _require_idle(state: EditState) -> None:
    if state != Idle():
        raise WrongState(state, Idle)


class WrongState(ValueError):
    def __init__(self, state: EditState, expected: type[EditState]):
        super().__init__(f"Expected {expected.__name__}, got {state}")
