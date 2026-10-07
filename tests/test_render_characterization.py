import hashlib
from types import SimpleNamespace

import numpy
import PIL
import pytest
from PIL import Image

from tests.conftest import monitor


def create_image(path, size, color):
    with Image.new("RGB", size, color) as image:
        image.save(path)


def render_profile(name, files):
    return SimpleNamespace(
        name=name,
        zoom=1.0,
        offsets=(0.0, 0.0),
        next_wallpaper_files=lambda: list(files),
    )


def pixels(image):
    return [image.getpixel((x, y)) for y in range(image.height) for x in range(image.width)]


# Two 2x2 displays with a one-pixel gap between them, the second one pixel lower.
TINY_DISPLAYS = [monitor(0, 0, 2, 2, 10, 10), monitor(3, 1, 2, 2, 10, 10)]


def configure_render(wpproc, monkeypatch, display_layout):
    monkeypatch.setattr(wpproc, "IS_WINDOWS", False)
    return display_layout(TINY_DISPLAYS)


def test_simple_render_fills_virtual_canvas(profile_modules, monkeypatch, tmp_path, app_paths, display_layout):
    _, wpproc = profile_modules
    layout = configure_render(wpproc, monkeypatch, display_layout)
    source = tmp_path / "source.png"
    with Image.new("RGB", (10, 3)) as image:
        for x in range(10):
            for y in range(3):
                image.putpixel((x, y), (20 * x, 60 * y, 10 * x + y))
        image.save(source)
    setter_calls = []
    monkeypatch.setattr(wpproc, "G_ACTIVE_PROFILE", "simple")
    monkeypatch.setattr(wpproc, "set_wallpaper", lambda *args, **kwargs: setter_calls.append((args, kwargs)))

    profile = render_profile("simple", [str(source)])
    assert wpproc.span_single_image_simple(profile, False, display_system=layout, paths=app_paths) == 0

    output = app_paths.cache / "simple-a.png"
    with Image.open(output) as image:
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
    setter_options = {"display_system": layout, "paths": app_paths, "set_command": ""}
    assert setter_calls == [((str(output), False, [str(source)]), setter_options)]


def test_multi_render_preserves_monitor_gaps(profile_modules, monkeypatch, tmp_path, app_paths, display_layout):
    _, wpproc = profile_modules
    layout = configure_render(wpproc, monkeypatch, display_layout)
    red = tmp_path / "red.png"
    blue = tmp_path / "blue.png"
    create_image(red, (2, 2), (255, 0, 0))
    create_image(blue, (2, 2), (0, 0, 255))
    setter_calls = []
    monkeypatch.setattr(wpproc, "G_ACTIVE_PROFILE", "multi")
    monkeypatch.setattr(wpproc, "set_wallpaper", lambda *args, **kwargs: setter_calls.append((args, kwargs)))

    profile = render_profile("multi", [str(red), str(blue)])
    assert wpproc.set_multi_image_wallpaper(profile, False, display_system=layout, paths=app_paths) == 0

    output = app_paths.cache / "multi-a.png"
    with Image.open(output) as image:
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
    setter_options = {"display_system": layout, "paths": app_paths, "set_command": ""}
    assert setter_calls == [((str(output), False, [str(red), str(blue)]), setter_options)]


def test_multi_render_skips_a_profile_set_up_for_other_displays(
    profile_modules, monkeypatch, tmp_path, app_paths, display_layout
):
    _, wpproc = profile_modules
    one_display = display_layout([monitor(0, 0, 2, 2, 10, 10)])
    red = tmp_path / "red.png"
    blue = tmp_path / "blue.png"
    create_image(red, (2, 2), (255, 0, 0))
    create_image(blue, (2, 2), (0, 0, 255))
    setter_calls = []
    monkeypatch.setattr(wpproc, "set_wallpaper", lambda *args, **kwargs: setter_calls.append(args))

    profile = render_profile("multi", [str(red), str(blue)])
    assert wpproc.set_multi_image_wallpaper(profile, True, display_system=one_display, paths=app_paths) is None

    assert setter_calls == []
    assert list(app_paths.cache.iterdir()) == []


def test_render_cache_alternates_between_two_files(profile_modules, monkeypatch, tmp_path, app_paths, display_layout):
    _, wpproc = profile_modules
    layout = configure_render(wpproc, monkeypatch, display_layout)
    source = tmp_path / "source.png"
    create_image(source, (5, 3), (10, 20, 30))
    monkeypatch.setattr(wpproc, "G_ACTIVE_PROFILE", "other")
    monkeypatch.setattr(wpproc, "set_wallpaper", lambda *args, **kwargs: None)
    profile = render_profile("alternating", [str(source)])

    expected = [("alternating-a.png",), ("alternating-b.png",), ("alternating-a.png",)]
    for files in expected:
        assert wpproc.span_single_image_simple(profile, False, display_system=layout, paths=app_paths) == 0
        assert tuple(sorted(path.name for path in app_paths.cache.iterdir())) == files


def test_windows_cache_uses_jpeg_extension(profile_modules, monkeypatch, app_paths):
    _, wpproc = profile_modules
    monkeypatch.setattr(wpproc, "IS_WINDOWS", True)
    cache = app_paths.cache

    output, old_output = wpproc.alternating_outputfile(cache, "windows")

    assert output == str(cache / "windows-a.jpg")
    assert old_output == str(cache / "windows-b.jpg")


# Advanced spanning: two screens of different pixel density with a 6 mm bezel between
# them, rendered through the advanced (PPI-corrected) path. The digests pin today's output
# exactly; they were recorded with Pillow 12.2.0 and numpy 2.5.0, so a different version of
# either can change them, and then they are re-recorded deliberately.
SMALL_MONITORS = [
    SimpleNamespace(x=0, y=0, width=64, height=36, width_mm=120, height_mm=68, name="A"),
    SimpleNamespace(x=64, y=6, width=48, height=27, width_mm=105, height_mm=59, name="B"),
]
ADVANCED_GOLDENS = {
    "offsets": "d55a711c95670d2e4ad667b5967864f6a4ec9f9d67b2c94d06f43f95075dd618",
    "span groups": "49a179d205c35521f306a400e09310146b7b87cc69dcba71f61fb6016e549f98",
    "perspective": "f22045d3fa224a9f60cebf74ea1e1e0e31717313e3f92b785acdd52f288911a2",
}


def small_layout(wpproc, monkeypatch, config_dir):
    monkeypatch.setattr(wpproc, "get_monitors", lambda: SMALL_MONITORS)
    system = wpproc.DisplaySystem(config_dir)
    system.update_bezels([(6.0, 0.0), (0.0, 0.0)])
    # The second screen swivels 25 degrees towards the viewer, who sits 200 px from the first.
    swivels = [(0, 0.0, 0.0, 0.0), (1, -25.0, 0.0, 0.0)]
    tilts = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
    system.update_perspectives("desk", True, False, (0, [0.0, 0.0, 200.0]), swivels, tilts)
    return system


def write_gradient(path, size, pixel):
    with Image.new("RGB", size) as image:
        image.putdata([pixel(x, y) for y in range(size[1]) for x in range(size[0])])
        image.save(path)
    return str(path)


@pytest.mark.parametrize(
    ("case", "spangroups", "perspective", "offsets"),
    [
        ("offsets", None, "disabled", ["0", "0", "2", "-3"]),
        ("span groups", [[0], [1]], "disabled", None),
        ("perspective", None, "desk", None),
    ],
)
def test_advanced_render_golden(
    profile_modules, monkeypatch, tmp_path, app_paths, case, spangroups, perspective, offsets
):
    data, wpproc = profile_modules
    monkeypatch.setattr(wpproc, "IS_WINDOWS", False)
    setter_calls = []
    monkeypatch.setattr(wpproc, "set_wallpaper", lambda *args, **kwargs: setter_calls.append(args))
    system = small_layout(wpproc, monkeypatch, app_paths.config)
    landscape = write_gradient(
        tmp_path / "landscape.png", (160, 90), lambda x, y: (x * 255 // 159, y * 255 // 89, (x + y) % 256)
    )
    portrait = write_gradient(tmp_path / "portrait.png", (90, 160), lambda x, y: ((x * 7) % 256, (y * 3) % 256, 128))
    files = [landscape, portrait] if spangroups else [landscape]
    profile = data.CLIProfileData(files, advanced=True, perspective=perspective, spangroups=spangroups, offsets=offsets)

    wpproc.change_wallpaper_job(profile, app_paths, force=True, display_system=system).join(timeout=30)

    output = app_paths.cache / "cli-a.png"
    with Image.open(output) as image:
        assert image.size == (112, 36)
        digest = hashlib.sha256(image.tobytes()).hexdigest()
    assert digest == ADVANCED_GOLDENS[case], f"pixels changed (Pillow {PIL.__version__}, numpy {numpy.__version__})"
    assert setter_calls == [(str(output), True, files)]


@pytest.mark.parametrize(
    ("spanmode", "ppimode", "renderer"),
    [
        ("single", False, "span_single_image_simple"),
        # A single-image profile with legacy corrections (offsets=, ppi=, ...) is spanned
        # with the advanced renderer.
        ("single", True, "span_single_image_advanced"),
        ("advanced", False, "span_single_image_advanced"),
        ("multi", False, "set_multi_image_wallpaper"),
    ],
)
def test_span_mode_picks_the_renderer(
    profile_modules, monkeypatch, app_paths, display_layout, spanmode, ppimode, renderer
):
    _, wpproc = profile_modules
    called = []
    for name in ("span_single_image_simple", "span_single_image_advanced", "set_multi_image_wallpaper"):
        monkeypatch.setattr(wpproc, name, lambda profile, force, *, name=name, **kwargs: called.append(name))
    profile = SimpleNamespace(
        name="p",
        spanmode=spanmode,
        display_corrections=lambda resolutions: SimpleNamespace(ppimode=ppimode),
        has_valid_selection=lambda: True,
    )

    wpproc.change_wallpaper_job(profile, app_paths, display_system=display_layout()).join(timeout=10)

    assert called == [renderer]
