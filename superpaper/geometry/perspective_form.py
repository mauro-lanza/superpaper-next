"""Saving a perspective from the perspective dialog, without any widgets.

A PerspectiveForm holds what the dialog's fields show, as typed. save_perspective turns it
into a perspective, asks first when it would need a very large intermediate image, and
saves the layout's perspective choice.
"""

import configparser
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from superpaper.files import SaveFailed
from superpaper.geometry import canvas, display_store
from superpaper.geometry.displays import MM_PER_INCH, Layout
from superpaper.geometry.perspective import (
    Perspective,
    SwivelAxis,
    check_new_perspective_name,
    parse_rotations_mm,
    parse_viewer_offsets_mm,
    perspective_from_mm,
)
from superpaper.user_input import Offset, Problems


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
    px_per_mm = layout.max_ppi() / MM_PER_INCH

    def mm(pixels: float) -> str:
        return str(round(pixels / px_per_mm, 1))

    return PerspectiveForm(
        name=perspective.name,
        use_perspective=layout.use_perspective,
        is_default=perspective.name == layout.default_perspective,
        central_display=perspective.central_display,
        viewer_offsets=tuple(str(offset / px_per_mm) for offset in perspective.viewer_pos),
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
            for swivel, tilt in zip(perspective.swivels, perspective.tilts)
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
    try:
        display_store.save_perspective_choice(config_dir, layout)
    except (OSError, configparser.Error, ValueError, KeyError) as error:
        return SaveFailed(f"The perspective settings could not be saved: {error}")
    return None


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
