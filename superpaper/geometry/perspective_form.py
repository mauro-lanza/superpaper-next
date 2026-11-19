"""Saving a perspective from the perspective dialog, without any widgets.

A PerspectiveForm holds what the dialog's fields show, as typed. save_perspective turns it
into a perspective, asks first when it would need a very large intermediate image, and
saves the layout's perspective choice.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from superpaper.geometry import canvas, display_store
from superpaper.geometry.display_store import SaveFailed
from superpaper.geometry.displays import Layout
from superpaper.geometry.perspective import Perspective, Swivel, SwivelAxis, Tilt, mm_to_pixels, pixels_to_mm
from superpaper.user_input import Offset, Problems, parse_float

# "default" and "disabled" clash with the editor's perspective choices.
_RESERVED_PERSPECTIVE_NAMES = frozenset({"default", "disabled", display_store.NO_DEFAULT_PERSPECTIVE.casefold()})
ROTATION_CELL_NAMES = (
    "Swivel angle",
    "Sw. ax. lat. off.",
    "Sw. ax. dep. off.",
    "Tilt angle",
    "Ti. ax. ver. off.",
    "Ti. ax. dep. off.",
)


@dataclass(frozen=True, slots=True)
class PerspectiveForm:
    """What the dialog's fields hold: text where the user types, choices where they pick."""

    name: str
    use_perspective: bool
    is_default: bool
    central_display: int
    viewer_offsets: tuple[str, ...]
    """The viewer's three offsets in millimetres."""
    swivel_axes: tuple[int, ...]
    """The swivel axis chosen for each display (a SwivelAxis value)."""
    rotation_cells: tuple[tuple[str, ...], ...]
    """Each display's texts, in the order of ROTATION_CELL_NAMES."""


@dataclass(frozen=True, slots=True)
class Saved:
    layout: Layout
    """The layout with the perspective choice that was saved."""


@dataclass(frozen=True, slots=True)
class NeedsConfirm:
    """The settings would need a very large intermediate image; save again with
    ``confirmed`` once the user accepts."""

    message: str


def blank_form(layout: Layout) -> PerspectiveForm:
    """The form of a new perspective for the displays of ``layout``."""
    count = len(layout.displays)
    return PerspectiveForm(
        name="",
        use_perspective=layout.use_perspective,
        is_default=False,
        central_display=0,
        viewer_offsets=("0", "0", "0"),
        swivel_axes=count * (SwivelAxis.NONE.value,),
        rotation_cells=count * (("0.0",) * 6,),
    )


def form_from(perspective: Perspective, layout: Layout) -> PerspectiveForm:
    """The form that shows ``perspective``, its lengths in millimetres at the densest display of ``layout``."""
    max_ppi = layout.max_ppi()

    def mm(pixels: float) -> str:
        return str(round(pixels_to_mm(pixels, max_ppi), 1))

    return PerspectiveForm(
        name=perspective.name,
        use_perspective=layout.use_perspective,
        is_default=perspective.name == layout.default_perspective,
        central_display=perspective.central_display,
        viewer_offsets=tuple(mm(offset) for offset in perspective.viewer_pos),
        swivel_axes=tuple(swivel.axis.value for swivel in perspective.swivels),
        rotation_cells=tuple(
            (
                str(swivel.angle),
                mm(swivel.lateral_offset),
                mm(swivel.depth_offset),
                str(tilt.angle),
                mm(tilt.vertical_offset),
                mm(tilt.depth_offset),
            )
            for swivel, tilt in zip(perspective.swivels, perspective.tilts, strict=True)
        ),
    )


def save_perspective(
    form: PerspectiveForm,
    *,
    layout: Layout,
    offsets: Sequence[Offset],
    warn_large: bool,
    confirmed: bool,
    config_dir: Path,
) -> Saved | Problems | NeedsConfirm | SaveFailed:
    """Save the perspective ``form`` describes into ``layout``'s choice.

    ``offsets`` are the applied manual offsets that the image size check uses.
    """
    if not form.name:
        return Problems(("Profile name is required.",))
    if layout.perspective(form.name) is None:
        try:
            check_new_perspective_name(form.name)
        except ValueError as error:
            return Problems((str(error),))
    try:
        viewer_offset_mm = parse_viewer_offsets_mm(form.viewer_offsets)
        swivels, tilts = parse_rotations_mm(form.swivel_axes, form.rotation_cells)
    except ValueError as error:
        return Problems((str(error),))
    perspective = perspective_from_mm(
        form.name, layout.max_ppi(), form.central_display, viewer_offset_mm, swivels, tilts
    )

    # Checked as they are, so the layout is only changed once they are accepted.
    if warn_large and not confirmed:
        size = canvas.source_size(layout.ppi_norm_crops(offsets), perspective)
        if canvas.exceeds_perspective_limit(size):
            return NeedsConfirm(_large_image_warning(size))

    chosen = layout.with_perspective(perspective, use_perspective=form.use_perspective, is_default=form.is_default)
    # The .persp file is written first, then the default it is named in.
    return save_choice(config_dir, chosen) or Saved(chosen)


def save_choice(config_dir: Path, layout: Layout) -> SaveFailed | None:
    """Save the perspective choice of ``layout`` alone, without its unsaved layout edits."""
    return display_store.save_or_failure(
        display_store.save_perspective_choice, config_dir, layout, "perspective settings"
    )


def check_new_perspective_name(name: str) -> None:
    """Raise ValueError if ``name`` cannot be given to a perspective being saved."""
    if name.casefold() in _RESERVED_PERSPECTIVE_NAMES:
        message = f"'{name}' is reserved; choose another perspective name."
        raise ValueError(message)


def parse_viewer_offsets_mm(texts: Sequence[str]) -> list[float]:
    """The viewer's (horizontal, vertical, distance) offsets in millimetres, as typed.

    Raises ValueError saying what is wrong with them; the distance must be positive.
    """
    numbers = [parse_float(text) for text in texts]
    offsets = [number for number in numbers if number is not None]
    if len(offsets) != len(numbers):
        message = "Viewer offsets should be lengths in millimetres, separate decimals with a point."
        raise ValueError(message)
    if offsets[2] <= 0:
        message = "Viewer distance must be entered and positive."
        raise ValueError(message)
    return offsets


def parse_rotations_mm(
    axes: Sequence[int], cells: Sequence[Sequence[str]]
) -> tuple[list[tuple[SwivelAxis, float, float, float]], list[tuple[float, float, float]]]:
    """The swivels and tilts of the displays in the dialog's grid, as typed.

    ``axes`` holds each display's swivel axis choice (a SwivelAxis value) and ``cells`` its
    texts in the order of ROTATION_CELL_NAMES. Raises ValueError naming the display and
    column of a cell that is not a number.
    """
    swivels = []
    tilts = []
    for display, (axis, row) in enumerate(zip(axes, cells, strict=True)):
        numbers = []
        for name, text in zip(ROTATION_CELL_NAMES, row, strict=True):
            number = parse_float(text)
            if number is None:
                message = f"Display {display}, '{name}': '{text}' is not a number; separate decimals with a point."
                raise ValueError(message)
            numbers.append(number)
        swivels.append((SwivelAxis(axis), numbers[0], numbers[1], numbers[2]))
        tilts.append((numbers[3], numbers[4], numbers[5]))
    return swivels, tilts


def perspective_from_mm(
    name: str,
    max_ppi: float,
    central_display: int,
    viewer_offset_mm: list[float],
    swivels_mm: list[tuple[SwivelAxis, float, float, float]],
    tilts_mm: list[tuple[float, float, float]],
) -> Perspective:
    """The perspective for the dialog's lengths in millimetres, converted to pixels at
    ``max_ppi``; angles and axes are kept."""
    lateral, vertical, depth = (mm_to_pixels(length, max_ppi) for length in viewer_offset_mm)
    return Perspective(
        name,
        central_display,
        (lateral, vertical, depth),
        tuple(
            Swivel(axis, angle, mm_to_pixels(lat, max_ppi), mm_to_pixels(dep, max_ppi))
            for axis, angle, lat, dep in swivels_mm
        ),
        tuple(Tilt(angle, mm_to_pixels(ver, max_ppi), mm_to_pixels(dep, max_ppi)) for angle, ver, dep in tilts_mm),
    )


def _large_image_warning(size: tuple[int, int]) -> str:
    return (
        "These perspective settings will produce large intermediate images "
        "which might use a large amount of system memory during processing. "
        "Take care not to set the perspective so that you would see arbitrarily "
        "far into the projected image as this will produce unboundedly large "
        "images and will cause problems, even a system crash."
        "\n\n"
        f"Intermediate resolution with these settings is {size[0]}x{size[1]}"
        "\n\n"
        "Do you want to continue?\n"
        "\n"
        "This warning may be disabled from settings."
    )
