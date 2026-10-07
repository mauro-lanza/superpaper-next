"""Composing the desktop image: opening the user's images, the geometry, and the three
ways of spreading images over the displays."""

import hashlib

import numpy
import PIL
import pytest
from PIL import Image

from superpaper import render
from tests.conftest import monitor


def write_image(path, size, pixel, image_format=None, **options):
    """Save an image whose pixel at (x, y) is ``pixel(x, y)``; return its path as a string."""
    with Image.new("RGB", size) as image:
        image.putdata([pixel(x, y) for y in range(size[1]) for x in range(size[0])])
        image.save(path, image_format, **options)
    return str(path)


def pixels(image):
    return [image.getpixel((x, y)) for y in range(image.height) for x in range(image.width)]


# Two 2x2 displays with a one-pixel gap between them, the second one pixel lower.
TINY_DISPLAYS = [monitor(0, 0, 2, 2, 10, 10), monitor(3, 1, 2, 2, 10, 10)]


def test_an_image_opens_upright_and_in_rgb(tmp_path):
    # Stored landscape, top half red and bottom half blue; EXIF orientation 6 means
    # "rotate 90 degrees clockwise to view".
    exif = Image.Exif()
    exif[0x0112] = 6
    path = write_image(
        tmp_path / "rotated.jpg", (40, 20), lambda x, y: (220, 0, 0) if y < 10 else (0, 0, 220), exif=exif.tobytes()
    )
    grey = tmp_path / "grey.png"
    Image.new("L", (3, 3), 128).save(grey)

    upright = render.open_source_image(path)

    assert upright.size == (20, 40)
    assert upright.getpixel((3, 20))[2] > 150  # blue on the left
    assert upright.getpixel((16, 20))[0] > 150  # red on the right
    assert render.open_source_image(grey).mode == "RGB"


def test_an_image_over_the_size_limit_is_refused_before_it_is_decoded(tmp_path, monkeypatch):
    path = write_image(tmp_path / "large.png", (4, 4), lambda x, y: (0, 0, 0))
    monkeypatch.setattr(render, "MAX_PIXELS", 15)
    monkeypatch.setattr(render.ImageOps, "exif_transpose", lambda image: pytest.fail("the image was decoded"))

    with pytest.raises(render.SourceImageError, match="too large: 4 x 4 pixels"):
        render.open_source_image(path)


def test_an_unusable_image_is_reported_by_its_path(tmp_path):
    not_an_image = tmp_path / "notes.png"
    not_an_image.write_bytes(b"not an image")
    truncated = tmp_path / "truncated.png"
    write_image(truncated, (64, 64), lambda x, y: (x * 37 % 256, y * 91 % 256, x * y % 256))
    truncated.write_bytes(truncated.read_bytes()[: truncated.stat().st_size // 2])

    for path, reason in [
        (tmp_path / "gone.png", "doesn't exist"),
        (not_an_image, "isn't an image Superpaper can read"),
        (truncated, "can't be read"),
    ]:
        with pytest.raises(render.SourceImageError, match=reason) as raised:
            render.open_source_image(path)
        assert str(path) in str(raised.value)


def test_compute_canvas_with_vertical_offset():
    assert render.compute_canvas([(1920, 1080), (1280, 1024)], [(0, 0), (1920, 200)]) == [3200, 1224]


def test_working_canvas_includes_outer_bezels():
    assert render.compute_working_canvas([(0, 0, 100, 80), (100, 10, 200, 90)], [(5, 4), (12, 8)]) == [212, 98]


def test_resize_to_fill_alignment():
    image = Image.new("RGB", (4, 2))
    for x in range(4):
        for y in range(2):
            image.putpixel((x, y), (x * 50, 0, 0))

    left = render.resize_to_fill(image, (2, 2), offset=(-1, 0))
    right = render.resize_to_fill(image, (2, 2), offset=(1, 0))

    assert left.getpixel((0, 0))[0] < right.getpixel((0, 0))[0]


def test_simple_spanning_fills_the_desktop(tmp_path, display_layout):
    source = write_image(tmp_path / "source.png", (10, 3), lambda x, y: (20 * x, 60 * y, 10 * x + y))

    image = render.simple(source, display_layout(TINY_DISPLAYS))

    assert image.size == (5, 3)
    assert pixels(image) == [
        (40, 0, 20),
        (60, 0, 30),
        (80, 0, 40),
        (100, 0, 50),
        (120, 0, 60),
        (40, 60, 21),
        (60, 60, 31),
        (80, 60, 41),
        (100, 60, 51),
        (120, 60, 61),
        (40, 120, 22),
        (60, 120, 32),
        (80, 120, 42),
        (100, 120, 52),
        (120, 120, 62),
    ]


def test_one_image_per_display_keeps_the_gaps_black(tmp_path, display_layout):
    red = write_image(tmp_path / "red.png", (2, 2), lambda x, y: (255, 0, 0))
    blue = write_image(tmp_path / "blue.png", (2, 2), lambda x, y: (0, 0, 255))

    image = render.multi([red, blue], display_layout(TINY_DISPLAYS))

    assert image.size == (5, 3)
    assert pixels(image) == [
        (255, 0, 0),
        (255, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (255, 0, 0),
        (255, 0, 0),
        (0, 0, 0),
        (0, 0, 255),
        (0, 0, 255),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 255),
        (0, 0, 255),
    ]


# Advanced spanning: two screens of different pixel density with a 6 mm bezel between
# them. The digests pin the output exactly; they were recorded with Pillow 12.2.0 and
# numpy 2.5.0, so a different version of either can change them, and then they are
# re-recorded deliberately.
SMALL_MONITORS = [
    monitor(0, 0, 64, 36, 120, 68, "A"),
    monitor(64, 6, 48, 27, 105, 59, "B"),
]
ADVANCED_GOLDENS = {
    "offsets": "d55a711c95670d2e4ad667b5967864f6a4ec9f9d67b2c94d06f43f95075dd618",
    "span groups": "49a179d205c35521f306a400e09310146b7b87cc69dcba71f61fb6016e549f98",
    "perspective": "f22045d3fa224a9f60cebf74ea1e1e0e31717313e3f92b785acdd52f288911a2",
}


@pytest.mark.parametrize(
    ("case", "spangroups", "perspective", "manual_offsets"),
    [
        ("offsets", None, None, [(0, 0), (2, -3)]),
        ("span groups", [[0], [1]], None, [(0, 0), (0, 0)]),
        ("perspective", None, "desk", [(0, 0), (0, 0)]),
    ],
)
def test_advanced_spanning_golden(tmp_path, display_layout, case, spangroups, perspective, manual_offsets):
    layout = display_layout(SMALL_MONITORS, config_dir=tmp_path)
    layout.update_bezels([(6.0, 0.0), (0.0, 0.0)])
    # The second screen swivels 25 degrees towards the viewer, who sits 200 px from the first.
    swivels = [(0, 0.0, 0.0, 0.0), (1, -25.0, 0.0, 0.0)]
    layout.update_perspectives("desk", True, False, (0, [0.0, 0.0, 200.0]), swivels, [(0.0, 0.0, 0.0)] * 2)
    landscape = write_image(
        tmp_path / "landscape.png", (160, 90), lambda x, y: (x * 255 // 159, y * 255 // 89, (x + y) % 256)
    )
    portrait = write_image(tmp_path / "portrait.png", (90, 160), lambda x, y: ((x * 7) % 256, (y * 3) % 256, 128))

    image = render.advanced(
        [landscape, portrait] if spangroups else [landscape],
        layout,
        manual_offsets=manual_offsets,
        spangroups=spangroups,
        perspective=layout.get_persp_data(perspective) if perspective else None,
    )

    assert image.size == (112, 36)
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    assert digest == ADVANCED_GOLDENS[case], f"pixels changed (Pillow {PIL.__version__}, numpy {numpy.__version__})"
