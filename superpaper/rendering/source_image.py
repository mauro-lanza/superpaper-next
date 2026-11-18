"""Opening the user's images: upright, in RGB, refused when too large, and cached for the preview."""

import os
from collections import OrderedDict

from PIL import Image, ImageOps, UnidentifiedImageError

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


def _downscaled(image: Image.Image) -> Image.Image:
    if image.width * image.height <= PREVIEW_MAX_PIXELS:
        return image
    scale = (PREVIEW_MAX_PIXELS / (image.width * image.height)) ** 0.5
    size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    return image.resize(size, Image.Resampling.HAMMING, reducing_gap=2.0)
