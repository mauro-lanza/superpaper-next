"""The displays and their layout, as values: the pixel-density, bezel, offset and diagonal
geometry that lines a wallpaper up across them.

Nothing here detects displays or touches a file: display_detection finds the displays and
display_store keeps the layout. A Layout never changes; an edit is a new Layout, so one can
be handed to another thread as it is.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import assert_never

from superpaper.geometry.canvas import Crop, DisplayArea, Point, canvas_size
from superpaper.geometry.perspective import Default, Disabled, Named, Perspective, PerspectiveChoice
from superpaper.geometry.units import MM_PER_INCH, mm_to_pixels

SIZE_HINT = (
    "Detection of the diagonal size of a display has failed. It will show up as a 23 inch "
    "display in advanced mode. Enter the correct diagonal size with the Override Detected "
    "Sizes tool."
)


@dataclass(frozen=True, slots=True)
class Display:
    """A display as detected: where it is on the desktop, in pixels, and its physical size.

    ``digital_offset`` is non-negative. ``phys_size_failed`` is set when the size is a guess.
    """

    resolution: tuple[int, int]
    digital_offset: tuple[int, int]
    detected_phys_size_mm: tuple[float, float]
    phys_size_failed: bool
    name: str | None

    def __hash__(self) -> int:
        # Part of the key a layout is saved under (Layout.key): ints only, never the name.
        return hash((self.resolution, self.digital_offset, self.detected_phys_size_mm))


@dataclass(frozen=True, slots=True)
class DisplaySettings:
    """What the display settings band edits and saves as a unit, to compare or restore."""

    bezels_mm: tuple[Point, ...]
    offsets: tuple[Point, ...]
    use_user_diagonals: bool
    diagonal_inches: tuple[float, ...]
    use_perspective: bool
    default_perspective: str | None
    perspectives: tuple[Perspective, ...]


@dataclass(frozen=True, slots=True)
class Layout:
    """The displays with what the user set for them.

    ``ppi_norm_offsets`` are the displays' positions on the canvas where every display has
    the pixel density of the densest one, bezels included. ``user_diagonal_inches`` replaces
    the detected sizes when the user entered them. Bezels are kept in millimetres and their
    pixels follow the current densities.
    """

    displays: tuple[Display, ...]
    ppi_norm_offsets: tuple[Point, ...]
    bezels_mm: tuple[Point, ...]
    user_diagonal_inches: tuple[float, ...] | None
    use_perspective: bool
    default_perspective: str | None
    perspectives: tuple[Perspective, ...]

    def __post_init__(self) -> None:
        count = len(self.displays)
        sizes = [len(self.ppi_norm_offsets), len(self.bezels_mm)]
        if self.user_diagonal_inches is not None:
            sizes.append(len(self.user_diagonal_inches))
        if count == 0 or any(size != count for size in sizes):
            message = f"A layout needs the same number of values for each of its {count} displays: {sizes}"
            raise ValueError(message)

    @classmethod
    def initial(cls, displays: tuple[Display, ...]) -> Layout:
        """The layout of ``displays`` before anything is set: detected sizes, no bezels, and
        the displays arranged by their positions on the desktop."""
        offsets = ((0, 0),) * len(displays)
        bezels = ((0.0, 0.0),) * len(displays)  # saved as 0.0, as earlier versions wrote them
        return cls(displays, offsets, bezels, None, True, None, ()).with_initial_offsets()

    @property
    def key(self) -> str:
        """What the layout is saved under. It is CPython's hash of the displays'
        resolutions, positions and detected sizes, all ints, so it is the same in every
        run. It must never change: every user's saved layouts would be lost."""
        return str(hash(self.displays))

    @property
    def uses_user_diagonals(self) -> bool:
        return self.user_diagonal_inches is not None

    def size_hint(self) -> str | None:
        """What to tell the user when a display's physical size wasn't detected and no
        diagonal they entered replaces the guess."""
        if not self.uses_user_diagonals and any(display.phys_size_failed for display in self.displays):
            return SIZE_HINT
        return None

    def resolutions(self) -> list[tuple[int, int]]:
        """Each display's resolution in pixels, in desktop order."""
        return [display.resolution for display in self.displays]

    def digital_offsets(self) -> list[tuple[int, int]]:
        """Each display's top-left corner on the desktop, in desktop order."""
        return [display.digital_offset for display in self.displays]

    def desktop_size(self) -> tuple[int, int]:
        """The size of the desktop, in pixels."""
        crops = [
            (left, top, left + width, top + height)
            for (width, height), (left, top) in zip(self.resolutions(), self.digital_offsets(), strict=True)
        ]
        return canvas_size(crops)

    def diagonal_inches(self) -> list[float]:
        """Each display's diagonal in inches, to a tenth."""
        return [round(math.sqrt(width**2 + height**2) / MM_PER_INCH, 1) for width, height in self._phys_sizes_mm()]

    def max_ppi(self) -> float:
        """The highest pixel density of the displays."""
        return max(self._ppis())

    def ppi_norm_resolutions(self) -> list[tuple[int, int]]:
        """Each display's resolution scaled to the pixel density of the densest display."""
        max_ppi = self.max_ppi()
        sizes = []
        for display, ppi in zip(self.displays, self._ppis(), strict=True):
            relative_ppi = ppi / max_ppi
            sizes.append((round(display.resolution[0] / relative_ppi), round(display.resolution[1] / relative_ppi)))
        return sizes

    def bezels_in_mm(self) -> list[Point]:
        """Each display's (right, bottom) bezel in millimetres."""
        return [(round(bezel[0], 2), round(bezel[1], 2)) for bezel in self.bezels_mm]

    def ppi_norm_bezels(self) -> list[Point]:
        """Each display's (right, bottom) bezel in pixels of the densest display."""
        # Unset bezels stay integers, so a fresh layout saves byte-identically.
        if all(bezel == (0, 0) for bezel in self.bezels_mm):
            return [(0, 0)] * len(self.displays)
        max_ppi = self.max_ppi()
        return [(mm_to_pixels(bezel[0], max_ppi), mm_to_pixels(bezel[1], max_ppi)) for bezel in self.bezels_mm]

    def ppi_norm_crops(self, manual_offsets: Sequence[Point]) -> list[Crop]:
        """Each display's (left, top, right, bottom) to cut from the density-normalised
        canvas, moved by ``manual_offsets``; a display without one isn't moved."""
        crops = []
        for index, (offset, size) in enumerate(zip(self.ppi_norm_offsets, self.ppi_norm_resolutions(), strict=True)):
            manual = manual_offsets[index] if index < len(manual_offsets) else (0, 0)
            left_top = (round(offset[0] + manual[0]), round(offset[1] + manual[1]))
            crops.append((*left_top, round(size[0]) + left_top[0], round(size[1]) + left_top[1]))
        return crops

    def real_areas(self) -> list[DisplayArea]:
        """The displays as they are on the desktop, in real pixels."""
        return [DisplayArea(display.resolution, display.digital_offset, (0, 0)) for display in self.displays]

    def ppi_norm_areas(self) -> list[DisplayArea]:
        """The displays as they are placed on the density-normalised canvas."""
        return [
            DisplayArea(size, offset, bezels)
            for size, offset, bezels in zip(
                self.ppi_norm_resolutions(), self.ppi_norm_offsets, self.ppi_norm_bezels(), strict=True
            )
        ]

    def with_offsets(self, offsets: Sequence[Point]) -> Layout:
        """The layout with the displays at ``offsets`` on the density-normalised canvas."""
        return replace(self, ppi_norm_offsets=tuple((offset[0], offset[1]) for offset in offsets))

    def with_initial_offsets(self) -> Layout:
        """The layout with its displays arranged from their positions on the desktop.

        Displays that overlap horizontally form a column; columns are tiled left to right,
        centred vertically on each other, and the displays of a column top to bottom,
        centred horizontally. Column membership is decided in desktop pixels, but sizes are
        the density-normalised ones, so the arrangement reflects the physical sizes. The
        displays must be listed so that those of a column are together.
        """
        sizes = self.ppi_norm_resolutions()
        bezels = self.ppi_norm_bezels()
        cells = [(size[0] + bezel[0], size[1] + bezel[1]) for size, bezel in zip(sizes, bezels, strict=True)]

        columns: list[list[int]] = []
        for index, display in enumerate(self.displays):
            if columns and _fits_in_column(display, self.displays[columns[-1][-1]]):
                columns[-1].append(index)
            else:
                columns.append([index])
        for column in columns:
            column.sort(key=lambda index: self.displays[index].digital_offset[1])

        column_widths = [max(cells[index][0] for index in column) for column in columns]
        column_heights = [sum(cells[index][1] for index in column) for column in columns]
        tallest = max(column_heights)

        offsets: dict[int, Point] = {}
        left = 0
        for column, width, height in zip(columns, column_widths, column_heights, strict=True):
            top = round((tallest - height) / 2)
            current_top = 0
            for index in column:
                offsets[index] = (left + round((width - cells[index][0]) / 2), top + current_top)
                current_top += sizes[index][1] + bezels[index][1]
            left += width
        return self.with_offsets([offsets[index] for index in range(len(self.displays))])

    def with_bezels(self, bezels_mm: Sequence[Point]) -> Layout:
        """The layout with new bezels, in millimetres; they can't be negative.

        Offsets are cell origins and the bezel is part of the cell, so a hand-arranged
        layout keeps its gaps only if every display moves by the growth of the bezels
        before it in the same row or column. A layout that overlaps afterwards, such as
        corner-touching displays that share no row or column, is arranged afresh.
        """
        if any(bezel < 0 for pair in bezels_mm for bezel in pair):
            message = f"Bezel thicknesses can't be negative: {bezels_mm}"
            raise ValueError(message)
        changed = replace(self, bezels_mm=tuple((pair[0], pair[1]) for pair in bezels_mm))
        if not self.is_valid():
            return changed.with_initial_offsets()
        old_cells = self._cells()
        old_bezels = self.ppi_norm_bezels()
        new_bezels = changed.ppi_norm_bezels()
        shifted = []
        for i, (left, top, right, bottom) in enumerate(old_cells):
            dx = dy = 0.0
            for j, (other_left, other_top, other_right, other_bottom) in enumerate(old_cells):
                if j == i:
                    continue
                growth = (new_bezels[j][0] - old_bezels[j][0], new_bezels[j][1] - old_bezels[j][1])
                if other_right <= left + 1 and _spans_overlap(top, bottom, other_top, other_bottom):
                    dx += growth[0]
                if other_bottom <= top + 1 and _spans_overlap(left, right, other_left, other_right):
                    dy += growth[1]
            shifted.append((self.ppi_norm_offsets[i][0] + dx, self.ppi_norm_offsets[i][1] + dy))
        moved = changed.with_offsets(shifted)
        return moved if moved.is_valid() else moved.with_initial_offsets()

    def with_overlaps_shifted(self) -> Layout | None:
        """The layout with only the displays that overlap moved apart, each right or down by
        the least that clears the displays placed before it; None if some still overlap.

        Displays are placed left to right, top to bottom, so a display never moves for one
        that comes after it, and every move passes a placed display for good.
        """
        cells = self._cells()
        offsets: list[Point] = list(self.ppi_norm_offsets)
        placed: list[int] = []
        for i in sorted(range(len(cells)), key=lambda index: (cells[index][0], cells[index][1])):
            while True:
                left, top, right, bottom = cells[i]
                blocker = next(
                    (
                        cells[j]
                        for j in placed
                        if _spans_overlap(left, right, cells[j][0], cells[j][2])
                        and _spans_overlap(top, bottom, cells[j][1], cells[j][3])
                    ),
                    None,
                )
                if blocker is None:
                    break
                dx, dy = blocker[2] - left, blocker[3] - top
                step = (dx, 0.0) if dx <= dy else (0.0, dy)
                offsets[i] = (offsets[i][0] + step[0], offsets[i][1] + step[1])
                cells[i] = (left + step[0], top + step[1], right + step[0], bottom + step[1])
            placed.append(i)
        shifted = self.with_offsets(offsets)
        return shifted if shifted.is_valid() else None

    def with_diagonals(self, diagonal_inches: Sequence[float]) -> Layout:
        """The layout with the diagonal sizes the user entered; positions are kept, so
        displays may overlap afterwards."""
        return replace(self, user_diagonal_inches=tuple(diagonal_inches))

    def with_detected_sizes(self) -> Layout:
        """The layout with the detected display sizes; positions are kept."""
        return replace(self, user_diagonal_inches=None)

    def settings(self) -> DisplaySettings:
        """What the display settings band edits, rounded as it shows them, to compare or restore."""
        return DisplaySettings(
            bezels_mm=tuple(self.bezels_in_mm()),
            offsets=self.ppi_norm_offsets,
            use_user_diagonals=self.uses_user_diagonals,
            diagonal_inches=tuple(round(diagonal, 2) for diagonal in self.diagonal_inches()),
            use_perspective=self.use_perspective,
            default_perspective=self.default_perspective,
            perspectives=self.perspectives,
        )

    def with_settings(self, settings: DisplaySettings) -> Layout:
        """The layout with ``settings`` restored."""
        layout = self.with_bezels(settings.bezels_mm)
        layout = (
            layout.with_diagonals(settings.diagonal_inches)
            if settings.use_user_diagonals
            else layout.with_detected_sizes()
        )
        layout = replace(
            layout,
            use_perspective=settings.use_perspective,
            default_perspective=settings.default_perspective,
            perspectives=settings.perspectives,
        )
        # Positions are restored last: the bezel update above may rearrange the displays.
        return layout.with_offsets(settings.offsets)

    def with_use_perspective(self, use_perspective: bool) -> Layout:
        return replace(self, use_perspective=use_perspective)

    def with_perspectives_of(self, other: Layout) -> Layout:
        """The layout with the perspective choice of ``other``: whether they are used, which
        is the default, and the perspectives."""
        return replace(
            self,
            use_perspective=other.use_perspective,
            default_perspective=other.default_perspective,
            perspectives=other.perspectives,
        )

    def with_perspective(self, perspective: Perspective, *, use_perspective: bool, is_default: bool) -> Layout:
        """The layout with ``perspective`` added, or replacing the one of its name, and
        whether it is the default."""
        default = self.default_perspective
        if is_default:
            default = perspective.name
        elif default == perspective.name:
            default = None
        if self.perspective(perspective.name) is None:
            perspectives = (*self.perspectives, perspective)
        else:
            perspectives = tuple(
                perspective if existing.name == perspective.name else existing for existing in self.perspectives
            )
        return replace(self, use_perspective=use_perspective, default_perspective=default, perspectives=perspectives)

    def without_perspective(self, name: str) -> Layout:
        """The layout without the perspective ``name``, which also stops being the default."""
        default = None if self.default_perspective == name else self.default_perspective
        perspectives = tuple(perspective for perspective in self.perspectives if perspective.name != name)
        return replace(self, default_perspective=default, perspectives=perspectives)

    def perspective(self, name: str) -> Perspective | None:
        return next((perspective for perspective in self.perspectives if perspective.name == name), None)

    def perspective_names(self) -> list[str]:
        return [perspective.name for perspective in self.perspectives]

    def perspective_for(self, choice: PerspectiveChoice) -> Perspective | None:
        """The perspective a profile's ``choice`` means for this layout, if there is one."""
        match choice:
            case Default():
                name = self.default_perspective
            case Disabled():
                return None
            case Named(chosen):
                name = chosen
            case _:
                assert_never(choice)
        if not name:
            return None
        return self.perspective(name)

    def _phys_sizes_mm(self) -> list[Point]:
        if self.user_diagonal_inches is None:
            return [display.detected_phys_size_mm for display in self.displays]
        sizes = []
        for display, diagonal in zip(self.displays, self.user_diagonal_inches, strict=True):
            width_inch = _width_inches(display.resolution, diagonal)
            height_inch = display.resolution[1] / display.resolution[0] * width_inch
            sizes.append((width_inch * MM_PER_INCH, height_inch * MM_PER_INCH))
        return sizes

    def _ppis(self) -> list[float]:
        if self.user_diagonal_inches is None:
            return [display.resolution[0] / display.detected_phys_size_mm[0] * MM_PER_INCH for display in self.displays]
        return [
            display.resolution[0] / _width_inches(display.resolution, diagonal)
            for display, diagonal in zip(self.displays, self.user_diagonal_inches, strict=True)
        ]

    def _cells(self) -> list[tuple[float, float, float, float]]:
        """Each display with its bezel as (left, top, right, bottom) in ppi norm pixels."""
        return [
            (offset[0], offset[1], offset[0] + size[0] + bezel[0], offset[1] + size[1] + bezel[1])
            for offset, size, bezel in zip(
                self.ppi_norm_offsets, self.ppi_norm_resolutions(), self.ppi_norm_bezels(), strict=True
            )
        ]

    def is_valid(self) -> bool:
        """Whether no two displays overlap, bezels included."""
        cells = self._cells()
        return not any(
            _spans_overlap(a[0], a[2], b[0], b[2]) and _spans_overlap(a[1], a[3], b[1], b[3])
            for i, a in enumerate(cells)
            for b in cells[i + 1 :]
        )


def _width_inches(resolution: tuple[int, int], diagonal_inch: float) -> float:
    height_to_width_ratio = resolution[1] / resolution[0]
    return diagonal_inch / math.sqrt(1 + height_to_width_ratio**2)


def _fits_in_column(display: Display, last_in_column: Display) -> bool:
    """Whether, in desktop pixels, the horizontal centre of ``display`` is within the last display of a column."""
    left = display.digital_offset[0]
    centre = (left + left + display.resolution[0]) / 2
    column_left = last_in_column.digital_offset[0]
    column_right = column_left + last_in_column.resolution[0]
    return column_left < centre < column_right


def _spans_overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> bool:
    return min(end_a, end_b) - max(start_a, start_b) > 1
