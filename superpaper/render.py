"""Compose one desktop image from the user's images, for a display layout.

Nothing here writes a file or shows anything: render_cache keeps the result and
superpaper.desktop shows it.
"""

import logging
from collections.abc import Sequence
from operator import itemgetter
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, UnidentifiedImageError

import superpaper.perspective as persp

if TYPE_CHECKING:
    from superpaper.wallpaper_processing import DisplaySystem

logger = logging.getLogger(__name__)

# open_source_image decides what is too large. Pillow's own limit, which warns at about
# 89 and refuses at about 179 megapixels, would turn away images Superpaper accepts.
Image.MAX_IMAGE_PIXELS = None

MAX_PIXELS = 250_000_000
"""The largest image Superpaper opens, in pixels: about 750 MB once decoded."""


class SourceImageError(Exception):
    """One of the user's images can't be used; the message says which and why."""


def open_source_image(path) -> Image.Image:
    """Open one of the user's images, upright as its EXIF orientation says, in RGB.

    An image over MAX_PIXELS is refused from its header, before it is decoded.
    """
    try:
        source = Image.open(path)
    except FileNotFoundError:
        message = f"The image {path} doesn't exist."
        raise SourceImageError(message) from None
    except UnidentifiedImageError:
        message = f"{path} isn't an image Superpaper can read."
        raise SourceImageError(message) from None
    except OSError as error:
        message = f"The image {path} can't be opened: {error}"
        raise SourceImageError(message) from error
    with source:
        width, height = source.size
        if width * height > MAX_PIXELS:
            message = (
                f"The image {path} is too large: {width} x {height} pixels, more than the "
                f"{MAX_PIXELS // 1_000_000} megapixels Superpaper opens."
            )
            raise SourceImageError(message)
        try:
            upright = ImageOps.exif_transpose(source)
            image = upright if upright.mode == "RGB" else upright.convert("RGB")
        except (OSError, ValueError) as error:  # truncated or corrupt image data
            message = f"The image {path} can't be read: {error}"
            raise SourceImageError(message) from error
    return image


def compute_canvas(res_array, offset_array):
    """Computes the size of the total desktop area from monitor resolutions and offsets."""
    # Take the subtractions of right-most right - left-most left
    # and bottom-most bottom - top-most top (=0).
    leftmost = 0
    topmost = 0
    right_edges = []
    bottom_edges = []
    for res, off in zip(res_array, offset_array):
        right_edges.append(off[0] + res[0])
        bottom_edges.append(off[1] + res[1])
    # Right-most edge.
    rightmost = max(right_edges)
    # Bottom-most edge.
    bottommost = max(bottom_edges)
    canvas_size = [rightmost - leftmost, bottommost - topmost]
    logger.info("Canvas size: %s", canvas_size)
    return canvas_size


def resize_to_fill(
    img,
    res,
    quality: str | Image.Resampling = Image.Resampling.LANCZOS,
    zoom=1.0,
    offset=(0.0, 0.0),
):
    """Resize image to fill given rectangle and do a positioned crop to size.

    The image is always scaled so that it fully covers the target rectangle
    ``res`` (no letterboxing). ``zoom`` (>= 1.0) scales the image further in,
    cropping away more of the source. ``offset`` is an (x, y) pair in the range
    [-1.0, 1.0] that slides the crop window within the available overflow:
    0.0 keeps the default centered crop, -1.0 aligns to the left/top edge and
    +1.0 aligns to the right/bottom edge. The result always fills ``res``.
    """
    if quality == "fast":
        quality = Image.Resampling.HAMMING
        reducing_gap = 1.5
    else:
        quality = Image.Resampling.LANCZOS
        reducing_gap = None

    if img.mode != "RGB":
        img = img.convert("RGB")

    # Sanitize positioning parameters.
    try:
        zoom = float(zoom)
    except TypeError, ValueError:
        zoom = 1.0
    if zoom < 1.0:
        zoom = 1.0
    try:
        offset_x = min(1.0, max(-1.0, float(offset[0])))
        offset_y = min(1.0, max(-1.0, float(offset[1])))
    except TypeError, ValueError, IndexError:
        offset_x, offset_y = 0.0, 0.0

    image_size = img.size  # returns image (width,height)
    if image_size == res and zoom == 1.0 and offset_x == 0.0 and offset_y == 0.0:
        # input image is already of the correct size, no action needed.
        return img

    # Scale so the image at least covers the target rectangle (cover fit),
    # then apply the additional user zoom. Using max() of the edge ratios
    # guarantees coverage regardless of aspect ratios.
    cover_multiplier = max(res[0] / image_size[0], res[1] / image_size[1])
    resize_multiplier = cover_multiplier * zoom
    # Guarantee the scaled image is never smaller than the target on either
    # edge despite rounding, so the final crop always yields exactly res.
    new_size = (
        max(round(resize_multiplier * image_size[0]), res[0]),
        max(round(resize_multiplier * image_size[1]), res[1]),
    )
    img = img.resize(new_size, resample=quality, reducing_gap=reducing_gap)

    extra_width = new_size[0] - res[0]
    extra_height = new_size[1] - res[1]
    # offset 0.0 -> centered crop (extra/2); -1.0 -> 0; +1.0 -> extra.
    left = round(extra_width / 2 * (1 + offset_x))
    top = round(extra_height / 2 * (1 + offset_y))
    # Clamp the crop origin so the window stays fully inside the image.
    left = min(max(left, 0), extra_width)
    top = min(max(top, 0), extra_height)
    crop_tuple = (left, top, left + res[0], top + res[1])
    cropped_res = img.crop(crop_tuple)
    if cropped_res.size == res:
        return cropped_res
    else:
        logger.info("Error: result image not of correct size. crp:%s, res:%s", cropped_res.size, res)
        return cropped_res


def compute_working_canvas(crop_tuples, bezels=None):
    """Computes effective size of the desktop are taking into account PPI/offsets/bezels.

    When ``bezels`` is provided (a list of ``(right, bottom)`` ppi-normalized
    bezel sizes parallel to ``crop_tuples``), the outer bezels extend the
    canvas so that the rendered image matches what the GUI preview shows. The
    preview sizes its canvas with these bezels included, so omitting them here
    made the applied wallpaper ignore outer bezels.
    """
    # Take the subtractions of right-most right - left-most left
    # and bottom-most bottom - top-most top (=0).
    leftmost = 0
    topmost = 0
    if bezels:
        # Right-/bottom-most edge including each display's outer bezel.
        rightmost = max(round(crp[2] + bez[0]) for crp, bez in zip(crop_tuples, bezels))
        bottommost = max(round(crp[3] + bez[1]) for crp, bez in zip(crop_tuples, bezels))
    else:
        # Right-most edge of the crop tuples.
        rightmost = max(crop_tuples, key=itemgetter(2))[2]
        # Bottom-most edge of the crop tuples.
        bottommost = max(crop_tuples, key=itemgetter(3))[3]
    canvas_size = [rightmost - leftmost, bottommost - topmost]
    return canvas_size


def simple(source, layout: DisplaySystem, *, zoom=1.0, pan=(0.0, 0.0)) -> Image.Image:
    """Span one image over the whole desktop, with no corrections.

    The image is resized to fill the bounding box of the displays, so this works for any
    arrangement of them. ``zoom`` and ``pan`` place the image as resize_to_fill describes.
    """
    canvas_tuple = tuple(compute_canvas(layout.resolutions(), layout.digital_offsets()))
    return resize_to_fill(open_source_image(source), canvas_tuple, zoom=zoom, offset=pan)


def group_persp_data(persp_dat, groups):
    """Rerturn list of grouped perspective data objects."""
    if not persp_dat:
        return [None] * len(groups)
    group_persp_data_list = []
    for grp in groups:
        group_data = {
            "central_disp": persp_dat["central_disp"],
            "viewer_pos": persp_dat["viewer_pos"],
            "swivels": [persp_dat["swivels"][index] for index in grp],
            "tilts": [persp_dat["tilts"][index] for index in grp],
        }
        group_persp_data_list.append(group_data)
    return group_persp_data_list


def translate_to_group_coordinates(group_crop_list):
    """Translates lists of group crops into groups internal coordinates."""
    if len(group_crop_list) == 1:
        return group_crop_list
    else:
        group_crop_list_transl = []
        for grp_crops in group_crop_list:
            left_anch = min([crp[0] for crp in grp_crops])
            top_anch = min([crp[1] for crp in grp_crops])
            transl_crops = []
            for crp in grp_crops:
                transl_crops.append((crp[0] - left_anch, crp[1] - top_anch, crp[2] - left_anch, crp[3] - top_anch))
            group_crop_list_transl.append(transl_crops)
        return group_crop_list_transl


def advanced(
    sources: Sequence,
    layout: DisplaySystem,
    *,
    manual_offsets,
    spangroups=None,
    perspective=None,
    zoom=1.0,
    pan=(0.0, 0.0),
) -> Image.Image:
    """Span images so that they line up physically across displays of different pixel
    densities, with bezels and ``manual_offsets`` (each display's, in pixels) accounted for.

    ``spangroups`` lists the displays that each image spans; without groups, one image
    spans all of them. ``sources`` has one image per group. ``perspective`` is the
    layout's perspective data, which also corrects for displays turned towards the viewer.
    """
    # Cropping now sections of the image to be shown, USE EFFECTIVE WORKING
    # SIZES. Also EFFECTIVE SIZE Offsets are now required.
    resolutions = layout.resolutions()
    cropped_images = {}
    crop_tuples = layout.get_ppi_norm_crops(manual_offsets)
    if not spangroups:
        spangroups = [list(range(len(resolutions)))]

    grp_crop_tuples = translate_to_group_coordinates([[crop_tuples[index] for index in grp] for grp in spangroups])
    grp_res_array = [[resolutions[index] for index in grp] for grp in spangroups]
    # Per-display outer bezel sizes (ppi-normalized), grouped to match the
    # crops, so the working canvas can include outer bezels like the preview.
    bezels_px = layout.bezels_in_px()
    grp_bezels = [[bezels_px[index] for index in grp] for grp in spangroups]
    grp_persp_dat = group_persp_data(perspective, spangroups)

    for source, grp, grp_p_dat, grp_crops, grp_res_arr, grp_bez in zip(
        sources, spangroups, grp_persp_dat, grp_crop_tuples, grp_res_array, grp_bezels, strict=True
    ):
        img = open_source_image(source)
        if perspective:
            proj_plane_crops, persp_coeffs = persp.get_backprojected_display_system(grp_crops, grp_p_dat)
            # Canvas containing back-projected displays
            canvas_tuple_proj = tuple(compute_working_canvas(proj_plane_crops))
            # Canvas containing ppi normalized displays
            canvas_tuple_trgt = tuple(compute_working_canvas(grp_crops))
            logger.info("Back-projected canvas size: %s", canvas_tuple_proj)
            img_workingsize = resize_to_fill(img, canvas_tuple_proj, zoom=zoom, offset=pan)
            for _crop_tup, coeffs, ppin_crop, (i_res, res) in zip(
                proj_plane_crops, persp_coeffs, grp_crops, enumerate(grp_res_arr)
            ):
                # Whole image needs to be transformed for each display separately
                # since the coeffs live between the full back-projected plane
                # containing all displays and the full 'target' working canvas
                # size canvas_tuple_trgt containing ppi normalized displays.
                persp_crop = img_workingsize.transform(
                    canvas_tuple_trgt, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC
                )
                # Crop desired region from transformed image which is now in
                # ppi normalized resolution
                crop_img = persp_crop.crop(ppin_crop)
                # Resize correct crop to actual display resolution
                crop_img = crop_img.resize(res, resample=Image.Resampling.LANCZOS)
                cropped_images[grp[i_res]] = crop_img
        else:
            # larger working size needed to fill all the normalized lower density
            # displays. Takes account manual offsets that might require extra space.
            # Outer bezels extend the canvas so the result matches the preview
            # (issue #156); the per-display crops below stay resolution-sized.
            canvas_tuple_eff = tuple(compute_working_canvas(grp_crops, grp_bez))
            # Image is now the height of the eff tallest display + possible manual
            # offsets and the width of the combined eff widths + possible manual
            # offsets.
            img_workingsize = resize_to_fill(img, canvas_tuple_eff, zoom=zoom, offset=pan)
            # Simultaneously make crops at working size and then resize down to actual
            # display resolution as needed.
            for crop_tup, (i_res, res) in zip(grp_crops, enumerate(grp_res_arr)):
                crop_img = img_workingsize.crop(crop_tup)
                if crop_img.size != res:
                    crop_img = crop_img.resize(res, resample=Image.Resampling.LANCZOS)
                cropped_images[grp[i_res]] = crop_img
    # Combine crops to a single canvas of the size of the actual desktop
    # actual combined size of the display resolutions
    offsets = layout.digital_offsets()
    canvas_tuple_fin = tuple(compute_canvas(resolutions, offsets))
    combined_image = Image.new("RGB", canvas_tuple_fin, color=0)
    combined_image.load()
    for crp_id in cropped_images:
        combined_image.paste(cropped_images[crp_id], offsets[crp_id])
    return combined_image


def multi(sources: Sequence, layout: DisplaySystem, *, zoom=1.0, pan=(0.0, 0.0)) -> Image.Image:
    """Show a different image on each display: ``sources`` has one per display.

    Each image fills its display, and the gaps between displays stay black.
    """
    resolutions = layout.resolutions()
    offsets = layout.digital_offsets()
    combined_image = Image.new("RGB", tuple(compute_canvas(resolutions, offsets)), color=0)
    combined_image.load()
    for source, res, offset in zip(sources, resolutions, offsets, strict=True):
        combined_image.paste(resize_to_fill(open_source_image(source), res, zoom=zoom, offset=pan), offset)
    return combined_image
