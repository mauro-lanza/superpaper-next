"""Compose one desktop image from the user's images, for a display layout.

Nothing here writes a file or shows anything: render_cache keeps the result and
superpaper.desktop shows it.
"""

import logging
import os
from collections import OrderedDict
from collections.abc import Sequence

from PIL import Image, ImageOps, UnidentifiedImageError

import superpaper.geometry.perspective as persp
from superpaper.geometry.canvas import canvas_size, canvas_size_with_bezels
from superpaper.geometry.displays import Layout

logger = logging.getLogger(__name__)

# open_source_image decides what is too large. Pillow's own limit, which warns at about
# 89 and refuses at about 179 megapixels, would turn away images Superpaper accepts.
Image.MAX_IMAGE_PIXELS = None

MAX_PIXELS = 250_000_000
"""The largest image Superpaper opens, in pixels: about 750 MB once decoded."""

PREVIEW_MAX_PIXELS = 4_000_000
PREVIEW_CACHE_SIZE = 8
_preview_cache: OrderedDict[tuple[str, int, int], Image.Image] = OrderedDict()


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


def _downscaled(image: Image.Image) -> Image.Image:
    if image.width * image.height <= PREVIEW_MAX_PIXELS:
        return image
    scale = (PREVIEW_MAX_PIXELS / (image.width * image.height)) ** 0.5
    size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    return image.resize(size, Image.Resampling.HAMMING, reducing_gap=2.0)


def open_preview_image(path) -> Image.Image:
    """Like open_source_image, but at most PREVIEW_MAX_PIXELS and remembered until the file changes.

    The caller must not modify the result. Only the UI thread calls this, so no lock.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return open_source_image(path)  # raises the SourceImageError that says why
    key = (os.fspath(path), stat.st_mtime_ns, stat.st_size)
    cached = _preview_cache.get(key)
    if cached is not None:
        _preview_cache.move_to_end(key)
        return cached
    image = _downscaled(open_source_image(path))
    _preview_cache[key] = image
    while len(_preview_cache) > PREVIEW_CACHE_SIZE:
        _preview_cache.popitem(last=False)
    return image


def source_icon_image(path, size: tuple[int, int]) -> Image.Image | None:
    """The image at ``path`` shrunk to fit ``size`` keeping its aspect, or None if it can't be read.

    Opened on its own, not through the preview cache, so a long source list doesn't evict
    the preview's images; a JPEG is decoded at a reduced scale.
    """
    try:
        with Image.open(path) as source:
            if source.width * source.height > MAX_PIXELS:
                return None
            source.draft("RGB", size)
            upright = ImageOps.exif_transpose(source)
            image = upright if upright.mode == "RGB" else upright.convert("RGB")
    except OSError, ValueError:
        return None
    width, height = image.size
    scale = min(size[0] / width, size[1] / height)
    fitted = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image.resize(fitted, Image.Resampling.BOX)


def resize_to_fill(
    img: Image.Image,
    res: tuple[int, int],
    zoom: float = 1.0,
    offset: tuple[float, float] = (0.0, 0.0),
    resample: Image.Resampling = Image.Resampling.LANCZOS,
    reducing_gap: float | None = None,
) -> Image.Image:
    """Resize image to fill given rectangle and do a positioned crop to size.

    The image is always scaled so that it fully covers the target rectangle
    ``res`` (no letterboxing). ``zoom`` (>= 1.0) scales the image further in,
    cropping away more of the source. ``offset`` is an (x, y) pair in the range
    [-1.0, 1.0] that slides the crop window within the available overflow:
    0.0 keeps the default centered crop, -1.0 aligns to the left/top edge and
    +1.0 aligns to the right/bottom edge. The result always fills ``res``.
    Contract: zoom >= 1, offset in [-1, 1].
    ``resample`` and ``reducing_gap`` are Pillow's resize arguments of those names.
    """
    if img.mode != "RGB":
        img = img.convert("RGB")

    offset_x, offset_y = offset
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
    img = img.resize(new_size, resample=resample, reducing_gap=reducing_gap)

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


def simple(source, layout: Layout, *, zoom=1.0, pan=(0.0, 0.0)) -> Image.Image:
    """Span one image over the whole desktop, with no corrections.

    The image is resized to fill the bounding box of the displays, so this works for any
    arrangement of them. ``zoom`` and ``pan`` place the image as resize_to_fill describes.
    """
    return resize_to_fill(open_source_image(source), layout.desktop_size(), zoom=zoom, offset=pan)


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
    layout: Layout,
    *,
    manual_offsets,
    spangroups: tuple[tuple[int, ...], ...] | None = None,
    perspective: persp.Perspective | None = None,
    zoom=1.0,
    pan=(0.0, 0.0),
) -> Image.Image:
    """Span images so that they line up physically across displays of different pixel
    densities, with bezels and ``manual_offsets`` (each display's, in pixels) accounted for.

    ``spangroups`` lists the displays that each image spans; without groups, one image
    spans all of them. ``sources`` has one image per group. ``perspective`` also corrects
    for displays turned towards the viewer.
    """
    # Cropping now sections of the image to be shown, USE EFFECTIVE WORKING
    # SIZES. Also EFFECTIVE SIZE Offsets are now required.
    resolutions = layout.resolutions()
    cropped_images = {}
    crop_tuples = layout.ppi_norm_crops(manual_offsets)
    if not spangroups:
        spangroups = (tuple(range(len(resolutions))),)

    grp_crop_tuples = translate_to_group_coordinates([[crop_tuples[index] for index in grp] for grp in spangroups])
    grp_res_array = [[resolutions[index] for index in grp] for grp in spangroups]
    # Per-display outer bezel sizes (ppi-normalized), grouped to match the
    # crops, so the working canvas can include outer bezels like the preview.
    bezels_px = layout.ppi_norm_bezels()
    grp_bezels = [[bezels_px[index] for index in grp] for grp in spangroups]

    for source, grp, grp_crops, grp_res_arr, grp_bez in zip(
        sources, spangroups, grp_crop_tuples, grp_res_array, grp_bezels, strict=True
    ):
        img = open_source_image(source)
        if perspective is not None:
            proj_plane_crops, persp_coeffs = persp.get_backprojected_display_system(
                grp_crops, perspective.of_displays(grp)
            )
            # Canvas containing back-projected displays
            canvas_tuple_proj = canvas_size(proj_plane_crops)
            # Canvas containing ppi normalized displays
            canvas_tuple_trgt = canvas_size(grp_crops)
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
            canvas_tuple_eff = canvas_size_with_bezels(grp_crops, grp_bez)
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
    combined_image = Image.new("RGB", layout.desktop_size(), color=0)
    combined_image.load()
    for crp_id in cropped_images:
        combined_image.paste(cropped_images[crp_id], offsets[crp_id])
    return combined_image


def multi(sources: Sequence, layout: Layout, *, zoom=1.0, pan=(0.0, 0.0)) -> Image.Image:
    """Show a different image on each display: ``sources`` has one per display.

    Each image fills its display, and the gaps between displays stay black.
    """
    resolutions = layout.resolutions()
    offsets = layout.digital_offsets()
    combined_image = Image.new("RGB", layout.desktop_size(), color=0)
    combined_image.load()
    for source, res, offset in zip(sources, resolutions, offsets, strict=True):
        combined_image.paste(resize_to_fill(open_source_image(source), res, zoom=zoom, offset=pan), offset)
    return combined_image
