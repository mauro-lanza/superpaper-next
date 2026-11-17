import os

import pytest
from PIL import Image

from superpaper import render
from superpaper.render import SourceImageError, open_preview_image, source_icon_image


@pytest.fixture(autouse=True)
def empty_cache():
    render._preview_cache.clear()
    yield
    render._preview_cache.clear()


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
    paths = [save(tmp_path / f"{n}.png") for n in range(9)]
    images = [open_preview_image(path) for path in paths[:8]]
    assert open_preview_image(paths[0]) is images[0]  # now the most recent
    open_preview_image(paths[8])
    assert len(render._preview_cache) == 8
    assert open_preview_image(paths[0]) is images[0]
    assert open_preview_image(paths[1]) is not images[1]


def test_errors_are_not_cached(tmp_path):
    missing = str(tmp_path / "missing.png")
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not an image")
    for path in (missing, str(corrupt)):
        with pytest.raises(SourceImageError):
            open_preview_image(path)
    assert not render._preview_cache


def test_exif_orientation_is_applied(tmp_path):
    path = save(tmp_path / "a.jpg", size=(40, 20), orientation=6)
    assert open_preview_image(path).size == (20, 40)


def test_large_image_is_downscaled_keeping_aspect(tmp_path):
    path = save(tmp_path / "big.png", size=(4000, 2000))
    image = open_preview_image(path)
    assert image.width * image.height <= render.PREVIEW_MAX_PIXELS
    assert image.width * image.height > render.PREVIEW_MAX_PIXELS * 0.95
    assert abs(image.width / image.height - 2.0) < 0.01


def test_small_image_is_kept_at_full_size(tmp_path):
    assert open_preview_image(save(tmp_path / "a.png", size=(300, 200))).size == (300, 200)


def test_icon_image_honours_exif_and_fits(tmp_path):
    path = save(tmp_path / "a.jpg", size=(400, 200), orientation=6)
    icon = source_icon_image(path, (32, 32))
    assert icon is not None
    assert icon.size == (16, 32)


def test_icon_image_of_a_very_wide_image_is_one_pixel_high(tmp_path):
    icon = source_icon_image(save(tmp_path / "w.png", size=(5000, 2)), (32, 32))
    assert icon is not None
    assert icon.size == (32, 1)


def test_icon_image_of_unreadable_source_is_none(tmp_path):
    assert source_icon_image(str(tmp_path / "missing.png"), (32, 32)) is None
    assert source_icon_image(str(tmp_path), (32, 32)) is None


def test_icons_leave_the_preview_cache_alone(tmp_path):
    previews = [save(tmp_path / f"p{n}.png") for n in range(8)]
    cached = [open_preview_image(path) for path in previews]
    for n in range(20):
        assert source_icon_image(save(tmp_path / f"i{n}.jpg", size=(400, 300)), (32, 32)) is not None
    assert list(render._preview_cache.values()) == cached
