"""Compose one desktop image from the user's images, for a display layout.

Nothing here writes a file or shows anything: render_cache keeps the result and
superpaper.desktop shows it.
"""

import logging
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

import superpaper.geometry.perspective as persp
from superpaper.geometry.canvas import Crop, Point, canvas_size, canvas_size_with_bezels
from superpaper.geometry.displays import Layout
from superpaper.rendering.source_image import open_source_image

logger = logging.getLogger(__name__)


def shift_perspective(coeffs: Sequence[float], left: int, top: int) -> list[float]:
    """Perspective coefficients for the window of the output whose corner is (left, top).

    Substituting x + left, y + top into the mapping leaves a projective map whose
    denominator no longer starts at 1, so every coefficient is divided by it.
    """
    a, b, c, d, e, f, g, h = coeffs
    w = 1 + g * left + h * top
    return [a / w, b / w, (c + a * left + b * top) / w, d / w, e / w, (f + d * left + e * top) / w, g / w, h / w]


def resize_to_fill(
    img: Image.Image,
    res: tuple[int, int],
    zoom: float = 1.0,
    offset: tuple[float, float] = (0.0, 0.0),
    resample: Image.Resampling = Image.Resampling.LANCZOS,
    reducing_gap: float | None = None,
) -> Image.Image:
    """Scale the RGB ``img`` to cover ``res`` without letterboxing, then cut out a ``res`` window.

    ``zoom`` (>= 1) scales further in. ``offset`` is (x, y) in [-1, 1]: 0 centres the window,
    -1 aligns it to the left/top edge and +1 to the right/bottom. ``resample`` and
    ``reducing_gap`` are Pillow's resize arguments of those names.
    """
    offset_x, offset_y = offset
    image_size = img.size
    if image_size == res and zoom == 1.0 and offset_x == 0.0 and offset_y == 0.0:
        return img

    cover_multiplier = max(res[0] / image_size[0], res[1] / image_size[1])
    resize_multiplier = cover_multiplier * zoom
    # Rounding must never leave the scaled image smaller than ``res`` on an edge.
    new_size = (
        max(round(resize_multiplier * image_size[0]), res[0]),
        max(round(resize_multiplier * image_size[1]), res[1]),
    )
    img = img.resize(new_size, resample=resample, reducing_gap=reducing_gap)

    extra_width = new_size[0] - res[0]
    extra_height = new_size[1] - res[1]
    left = min(max(round(extra_width / 2 * (1 + offset_x)), 0), extra_width)
    top = min(max(round(extra_height / 2 * (1 + offset_y)), 0), extra_height)
    return img.crop((left, top, left + res[0], top + res[1]))


def simple(
    source: str | Path, layout: Layout, *, zoom: float = 1.0, pan: tuple[float, float] = (0.0, 0.0)
) -> Image.Image:
    """Span one image over the whole desktop, with no corrections.

    The image is resized to fill the bounding box of the displays, so this works for any
    arrangement of them. ``zoom`` and ``pan`` place the image as resize_to_fill describes.
    """
    return resize_to_fill(open_source_image(source), layout.desktop_size(), zoom=zoom, offset=pan)


def _to_group_coordinates(group_crops: list[list[Crop]]) -> list[list[Crop]]:
    """Each group's crops moved so that the group's top left corner is the origin."""
    if len(group_crops) == 1:
        return group_crops
    anchors = [(min(crop[0] for crop in crops), min(crop[1] for crop in crops)) for crops in group_crops]
    return [
        [(crop[0] - left, crop[1] - top, crop[2] - left, crop[3] - top) for crop in crops]
        for crops, (left, top) in zip(group_crops, anchors, strict=True)
    ]


def advanced(
    sources: Sequence[str | Path],
    layout: Layout,
    *,
    manual_offsets: Sequence[Point],
    spangroups: tuple[tuple[int, ...], ...] | None = None,
    perspective: persp.Perspective | None = None,
    zoom: float = 1.0,
    pan: tuple[float, float] = (0.0, 0.0),
) -> Image.Image:
    """Span images so that they line up physically across displays of different pixel
    densities, with bezels and ``manual_offsets`` (each display's, in pixels) accounted for.

    ``spangroups`` lists the displays that each image spans; without groups, one image
    spans all of them. ``sources`` has one image per group. ``perspective`` also corrects
    for displays turned towards the viewer.
    """
    resolutions = layout.resolutions()
    offsets = layout.digital_offsets()
    crop_tuples = layout.ppi_norm_crops(manual_offsets)
    if not spangroups:
        spangroups = (tuple(range(len(resolutions))),)

    grp_crop_tuples = _to_group_coordinates([[crop_tuples[index] for index in grp] for grp in spangroups])
    grp_res_array = [[resolutions[index] for index in grp] for grp in spangroups]
    # Grouped like the crops, so the working canvas can include outer bezels like the preview.
    bezels_px = layout.ppi_norm_bezels()
    grp_bezels = [[bezels_px[index] for index in grp] for grp in spangroups]

    combined_image = Image.new("RGB", layout.desktop_size(), color=0)
    for source, grp, grp_crops, grp_res_arr, grp_bez in zip(
        sources, spangroups, grp_crop_tuples, grp_res_array, grp_bezels, strict=True
    ):
        img = open_source_image(source)
        if perspective is not None:
            proj_plane_crops, persp_coeffs = persp.get_backprojected_display_system(
                grp_crops, perspective.of_displays(grp)
            )
            canvas_tuple_proj = canvas_size(proj_plane_crops)
            logger.info("Back-projected canvas size: %s", canvas_tuple_proj)
            img_workingsize = resize_to_fill(img, canvas_tuple_proj, zoom=zoom, offset=pan)
            for coeffs, ppin_crop, display, res in zip(persp_coeffs, grp_crops, grp, grp_res_arr, strict=True):
                left, top, right, bottom = (round(edge) for edge in ppin_crop)
                persp_crop = img_workingsize.transform(
                    (right - left, bottom - top),
                    Image.Transform.PERSPECTIVE,
                    shift_perspective(coeffs, left, top),
                    Image.Resampling.BICUBIC,
                )
                crop_img = persp_crop.resize(res, resample=Image.Resampling.LANCZOS)
                combined_image.paste(crop_img, offsets[display])
        else:
            # The canvas includes the outer bezels so the result matches the preview (issue
            # #156); the per-display crops stay resolution-sized.
            canvas_tuple_eff = canvas_size_with_bezels(grp_crops, grp_bez)
            img_workingsize = resize_to_fill(img, canvas_tuple_eff, zoom=zoom, offset=pan)
            for crop_tup, display, res in zip(grp_crops, grp, grp_res_arr, strict=True):
                crop_img = img_workingsize.crop(crop_tup)
                if crop_img.size != res:
                    crop_img = crop_img.resize(res, resample=Image.Resampling.LANCZOS)
                combined_image.paste(crop_img, offsets[display])
    return combined_image


def multi(
    sources: Sequence[str | Path], layout: Layout, *, zoom: float = 1.0, pan: tuple[float, float] = (0.0, 0.0)
) -> Image.Image:
    """Show a different image on each display: ``sources`` has one per display.

    Each image fills its display, and the gaps between displays stay black.
    """
    resolutions = layout.resolutions()
    offsets = layout.digital_offsets()
    combined_image = Image.new("RGB", layout.desktop_size(), color=0)
    for source, res, offset in zip(sources, resolutions, offsets, strict=True):
        combined_image.paste(resize_to_fill(open_source_image(source), res, zoom=zoom, offset=pan), offset)
    return combined_image
