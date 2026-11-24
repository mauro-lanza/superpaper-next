import os

import pytest
from PIL import Image

from superpaper.rendering import source_image
from superpaper.rendering.source_image import (
    SourceImageError,
    open_preview_image,
    open_source_image,
    source_icon_image,
)


@pytest.fixture(autouse=True)
def empty_cache():
    source_image._preview_cache.clear()
    yield
    source_image._preview_cache.clear()


def save(path, size=(40, 20), color=(200, 10, 10), orientation=None):
    image = Image.new("RGB", size, color)
    if orientation is None:
        image.save(path)
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(path, exif=exif)
    return str(path)


def test_second_open_is_the_cached_image(tmp_path):
    path = save(tmp_path / "a.png")
    assert open_preview_image(path) is open_preview_image(path)


def test_changed_file_is_decoded_again(tmp_path):
    path = save(tmp_path / "a.png")
    first = open_preview_image(path)
    save(tmp_path / "a.png", size=(60, 30))
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    second = open_preview_image(path)
    assert second is not first
    assert second.size == (60, 30)


def test_ninth_image_evicts_the_least_recently_used(tmp_path):
    size = source_image.PREVIEW_CACHE_SIZE
    paths = [save(tmp_path / f"{n}.png") for n in range(size + 1)]
    images = [open_preview_image(path) for path in paths[:size]]
    assert open_preview_image(paths[0]) is images[0]  # now the most recent
    open_preview_image(paths[size])
    assert len(source_image._preview_cache) == size
    assert open_preview_image(paths[0]) is images[0]
    assert open_preview_image(paths[1]) is not images[1]


def test_errors_are_not_cached(tmp_path):
    missing = str(tmp_path / "missing.png")
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not an image")
    for path in (missing, str(corrupt)):
        with pytest.raises(SourceImageError):
            open_preview_image(path)
    assert not source_image._preview_cache


def test_an_image_opens_upright_and_in_rgb(tmp_path):
    # Stored landscape, top half red and bottom half blue; EXIF orientation 6 means
    # "rotate 90 degrees clockwise to view".
    exif = Image.Exif()
    exif[0x0112] = 6
    stored = Image.new("RGB", (40, 20), (0, 0, 220))
    stored.paste((220, 0, 0), (0, 0, 40, 10))
    stored.save(tmp_path / "rotated.jpg", exif=exif.tobytes())
    Image.new("L", (3, 3), 128).save(tmp_path / "grey.png")

    upright = open_source_image(tmp_path / "rotated.jpg", None)

    assert upright.size == (20, 40)
    assert upright.getpixel((3, 20))[2] > 150  # blue on the left
    assert upright.getpixel((16, 20))[0] > 150  # red on the right
    assert open_source_image(tmp_path / "grey.png", None).mode == "RGB"


@pytest.mark.parametrize("orientation", [None, 6])
@pytest.mark.parametrize("min_size", [(100, 50), (101, 51), (500, 40), (800, 600), (1600, 1200)])
def test_a_jpeg_is_never_decoded_below_the_requested_size(tmp_path, orientation, min_size):
    stored = (1600, 1200) if orientation is None else (1200, 1600)
    path = save(tmp_path / "big.jpg", size=stored, orientation=orientation)

    image = open_source_image(path, min_size)

    assert image.width >= min_size[0]
    assert image.height >= min_size[1]


def test_a_jpeg_is_decoded_at_a_reduced_scale_when_less_is_needed(tmp_path):
    path = save(tmp_path / "big.jpg", size=(1200, 1600), orientation=6)

    assert open_source_image(path, (100, 50)).size == (200, 150)


def test_transparent_pixels_are_black_whatever_colour_they_hide(tmp_path):
    rgba = Image.new("RGBA", (2, 1))
    rgba.putdata([(255, 0, 0, 0), (0, 200, 0, 255)])
    rgba.save(tmp_path / "rgba.png")
    palette = Image.new("P", (2, 1))
    palette.putpalette([255, 0, 0, 0, 200, 0])
    palette.putdata([0, 1])
    palette.save(tmp_path / "palette.png", transparency=0)

    for name in ("rgba.png", "palette.png"):
        image = open_source_image(tmp_path / name, None)
        assert image.mode == "RGB"
        assert [image.getpixel((x, 0)) for x in range(2)] == [(0, 0, 0), (0, 200, 0)]


def test_an_image_over_the_size_limit_is_refused_before_it_is_decoded(tmp_path, monkeypatch):
    path = save(tmp_path / "large.png", size=(4, 4))
    monkeypatch.setattr(source_image, "MAX_PIXELS", 15)
    monkeypatch.setattr(source_image.ImageOps, "exif_transpose", lambda image: pytest.fail("the image was decoded"))

    with pytest.raises(SourceImageError, match="too large: 4 x 4 pixels"):
        open_source_image(path, None)


def test_an_unusable_image_is_reported_by_its_path(tmp_path):
    not_an_image = tmp_path / "notes.png"
    not_an_image.write_bytes(b"not an image")
    truncated = tmp_path / "truncated.png"
    noise = Image.effect_noise((64, 64), 80)
    noise.save(truncated)
    truncated.write_bytes(truncated.read_bytes()[: truncated.stat().st_size // 2])

    for path, reason in [
        (tmp_path / "gone.png", "doesn't exist"),
        (not_an_image, "isn't an image Superpaper can read"),
        (truncated, "can't be read"),
    ]:
        with pytest.raises(SourceImageError, match=reason) as raised:
            open_source_image(path, None)
        assert str(path) in str(raised.value)


def test_large_image_is_downscaled_keeping_aspect(tmp_path, monkeypatch):
    monkeypatch.setattr(source_image, "PREVIEW_MAX_PIXELS", 10_000)
    path = save(tmp_path / "big.png", size=(400, 200))
    image = open_preview_image(path)
    assert image.width * image.height <= 10_000
    assert image.width * image.height > 10_000 * 0.95
    assert abs(image.width / image.height - 2.0) < 0.02


def test_small_image_is_kept_at_full_size(tmp_path):
    assert open_preview_image(save(tmp_path / "a.png", size=(300, 200))).size == (300, 200)


@pytest.mark.parametrize(
    ("size", "orientation", "icon_size"),
    [
        ((400, 200), 6, (16, 32)),  # EXIF turns it upright before it is fitted
        ((5000, 2), None, (32, 1)),  # never thinner than a pixel
    ],
)
def test_icon_image_fits_the_box_keeping_its_aspect(tmp_path, size, orientation, icon_size):
    path = save(tmp_path / "a.jpg", size=size, orientation=orientation)
    icon = source_icon_image(path, (32, 32))
    assert icon is not None
    assert icon.size == icon_size


def test_icon_image_of_unreadable_source_is_none(tmp_path):
    assert source_icon_image(str(tmp_path / "missing.png"), (32, 32)) is None
    assert source_icon_image(str(tmp_path), (32, 32)) is None


def test_icons_leave_the_preview_cache_alone(tmp_path):
    previews = [save(tmp_path / f"p{n}.png") for n in range(8)]
    cached = [open_preview_image(path) for path in previews]
    for n in range(20):
        assert source_icon_image(save(tmp_path / f"i{n}.jpg", size=(400, 300)), (32, 32)) is not None
    assert list(source_image._preview_cache.values()) == cached
