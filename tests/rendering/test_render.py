"""Composing the desktop image: the three ways of spreading images over the displays."""

import hashlib
from pathlib import Path

import numpy
import PIL
import pytest
from PIL import Image

from superpaper.geometry.canvas import canvas_size
from superpaper.geometry.perspective import (
    Named,
    Perspective,
    Swivel,
    SwivelAxis,
    Tilt,
    get_backprojected_display_system,
)
from superpaper.rendering import render
from tests.conftest import TINY_DISPLAYS, monitor, pixels


def write_image(path, size, pixel, image_format=None, **options):
    """Save an image whose pixel at (x, y) is ``pixel(x, y)``; return its path as a string."""
    with Image.new("RGB", size) as image:
        image.putdata([pixel(x, y) for y in range(size[1]) for x in range(size[0])])
        image.save(path, image_format, **options)
    return str(path)


@pytest.mark.parametrize(
    ("zoom", "offset", "row"),
    [
        (1.0, (-1, 0), [0, 50]),
        (1.0, (0, 0), [50, 100]),
        (1.0, (1, 0), [100, 150]),
        (2.0, (-1, 0), [0, 0]),
        (2.0, (0, 0), [50, 100]),
        (2.0, (1, 0), [150, 150]),
    ],
)
def test_resize_to_fill_places_the_window_by_zoom_and_offset(zoom, offset, row):
    image = Image.new("RGB", (4, 2))
    image.putdata([(x * 50, 0, 0) for _ in range(2) for x in range(4)])

    window = render.resize_to_fill(image, (2, 2), zoom=zoom, offset=offset, resample=Image.Resampling.NEAREST)

    assert [window.getpixel((x, y))[0] for y in range(2) for x in range(2)] == row * 2


def test_advanced_spanning_zooms_and_pans_the_image(tmp_path, display_layout):
    layout = display_layout(SMALL_MONITORS[:1])
    halves = write_image(tmp_path / "halves.png", (64, 36), lambda x, y: (255, 0, 0) if x < 32 else (0, 0, 255))

    left = render.advanced([halves], layout, manual_offsets=[(0, 0)], zoom=2.0, pan=(-1, 0))
    right = render.advanced([halves], layout, manual_offsets=[(0, 0)], zoom=2.0, pan=(1, 0))

    assert left.getpixel((20, 18)) == (255, 0, 0)
    assert right.getpixel((44, 18)) == (0, 0, 255)
    assert left.getpixel((40, 18)) == (255, 0, 0)
    assert right.getpixel((20, 18)) == (0, 0, 255)


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
# re-recorded deliberately. The perspective case solves a linear system with numpy's
# OpenBLAS, whose kernels round its last bits differently per CPU, so it is compared
# with a tolerance against a stored image instead.
SMALL_MONITORS = [
    monitor(0, 0, 64, 36, 120, 68, "A"),
    monitor(64, 6, 48, 27, 105, 59, "B"),
]
ADVANCED_GOLDENS = {
    "offsets": {"d55a711c95670d2e4ad667b5967864f6a4ec9f9d67b2c94d06f43f95075dd618"},
    "span groups": {"0c5bd0c75270aa04e765d40b30d95d12b15fe854668d5da9b83af0d98934f762"},
}
PERSPECTIVE_GOLDEN = Path(__file__).parent / "goldens" / "perspective.png"
PERSPECTIVE_TOLERANCE = 2


@pytest.mark.parametrize(
    ("case", "spangroups", "perspective", "manual_offsets"),
    [
        ("offsets", None, None, [(0, 0), (2, -3)]),
        ("span groups", [[0], [1]], None, [(0, 0), (0, 0)]),
        ("perspective", None, "desk", [(0, 0), (0, 0)]),
    ],
)
def test_advanced_spanning_golden(tmp_path, display_layout, case, spangroups, perspective, manual_offsets):
    layout = display_layout(SMALL_MONITORS, config_dir=tmp_path).with_bezels([(6.0, 0.0), (0.0, 0.0)])
    # The second screen swivels 25 degrees towards the viewer, who sits 200 px from the first.
    desk = Perspective(
        "desk",
        0,
        (0.0, 0.0, 200.0),
        (Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0), Swivel(SwivelAxis.LEFT, -25.0, 0.0, 0.0)),
        (Tilt(0.0, 0.0, 0.0),) * 2,
    )
    layout = layout.with_perspective(desk, use_perspective=True, is_default=False)
    landscape = write_image(
        tmp_path / "landscape.png", (160, 90), lambda x, y: (x * 255 // 159, y * 255 // 89, (x + y) % 256)
    )
    portrait = write_image(tmp_path / "portrait.png", (90, 160), lambda x, y: ((x * 7) % 256, (y * 3) % 256, 128))

    image = render.advanced(
        [landscape, portrait] if spangroups else [landscape],
        layout,
        manual_offsets=manual_offsets,
        spangroups=spangroups,
        perspective=layout.perspective_for(Named(perspective)) if perspective else None,
    )

    assert image.size == (112, 36)
    if case == "perspective":
        with Image.open(PERSPECTIVE_GOLDEN) as golden:
            assert (image.size, image.mode) == (golden.size, golden.mode)
            difference = numpy.abs(numpy.asarray(image, int) - numpy.asarray(golden, int))
        assert difference.max() <= PERSPECTIVE_TOLERANCE
        return
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    assert digest in ADVANCED_GOLDENS[case], f"pixels changed (Pillow {PIL.__version__}, numpy {numpy.__version__})"


def test_transforming_only_a_display_area_matches_transforming_the_whole_canvas():
    crops = [(0, 0, 160, 90), (170, 10, 330, 100), (340, 0, 500, 90)]
    desk = Perspective(
        "desk",
        1,
        (0.0, 0.0, 300.0),
        (
            Swivel(SwivelAxis.RIGHT, 25.0, 0.0, 0.0),
            Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0),
            Swivel(SwivelAxis.LEFT, -25.0, 0.0, 0.0),
        ),
        (Tilt(0.0, 0.0, 0.0),) * 3,
    )
    plane_crops, coefficients = get_backprojected_display_system(crops, desk)
    source = Image.effect_noise(canvas_size(plane_crops), 60).convert("RGB")
    canvas = canvas_size(crops)

    for coeffs, (left, top, right, bottom) in zip(coefficients, crops, strict=True):
        whole = source.transform(canvas, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)
        part = source.transform(
            (right - left, bottom - top),
            Image.Transform.PERSPECTIVE,
            render.shift_perspective(coeffs, left, top),
            Image.Resampling.BICUBIC,
        )
        difference = numpy.abs(numpy.asarray(whole.crop((left, top, right, bottom)), int) - numpy.asarray(part, int))
        assert difference.max() <= 1


THREE_TURNED = Perspective(
    "desk",
    2,
    (20.0, -10.0, 300.0),
    (
        Swivel(SwivelAxis.RIGHT, 25.0, 0.0, 0.0),
        Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0),
        Swivel(SwivelAxis.LEFT, -25.0, 5.0, 3.0),
    ),
    (Tilt(0.0, 0.0, 0.0), Tilt(8.0, 0.0, 0.0), Tilt(-5.0, 2.0, 0.0)),
)


@pytest.mark.parametrize("group", [(0,), (0, 1), (1, 0)])
def test_a_span_group_sees_its_displays_as_the_whole_layout_does(group):
    crops = [(0, 0, 160, 90), (170, 10, 330, 100), (340, 0, 500, 90)]
    plane_crops, coefficients = get_backprojected_display_system(crops, THREE_TURNED)

    group_crops, group_coefficients = render.group_projection(plane_crops, coefficients, group)

    shift_x = plane_crops[group[0]][0] - group_crops[0][0]
    shift_y = plane_crops[group[0]][1] - group_crops[0][1]
    assert min(crop[0] for crop in group_crops) == 0 and min(crop[1] for crop in group_crops) == 0
    for index, crop, coeffs in zip(group, group_crops, group_coefficients, strict=True):
        assert crop == pytest.approx(numpy.subtract(plane_crops[index], (shift_x, shift_y, shift_x, shift_y)))
        left, top, right, bottom = crops[index]
        for x, y in [(left, top), (right, top), (right, bottom), (left, bottom)]:
            whole = map_point(coefficients[index], x, y)
            assert map_point(coeffs, x, y) == pytest.approx((whole[0] - shift_x, whole[1] - shift_y))


def map_point(coefficients, x, y):
    a, b, c, d, e, f, g, h = coefficients
    w = g * x + h * y + 1
    return ((a * x + b * y + c) / w, (d * x + e * y + f) / w)


def test_span_groups_without_the_central_display_render_with_perspective(tmp_path, display_layout):
    layout = display_layout([monitor(0, 0, 64, 36), monitor(64, 0, 64, 36), monitor(128, 0, 64, 36)])
    image = write_image(tmp_path / "image.png", (40, 20), lambda x, y: (x * 6, y * 12, 0))

    combined = render.advanced(
        [image, image],
        layout,
        manual_offsets=[(0, 0)] * 3,
        spangroups=[[0], [1, 2]],
        perspective=THREE_TURNED,
    )

    assert combined.size == layout.desktop_size()
    for (left, top), (width, height) in zip(layout.digital_offsets(), layout.resolutions(), strict=True):
        assert numpy.asarray(combined.crop((left, top, left + width, top + height))).any()
