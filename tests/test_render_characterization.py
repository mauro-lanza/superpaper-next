from types import SimpleNamespace

from PIL import Image


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


def configure_render(wpproc, monkeypatch, app_paths):
    monkeypatch.setattr(wpproc, "IS_WINDOWS", False)
    monkeypatch.setattr(wpproc, "NUM_DISPLAYS", 2)
    monkeypatch.setattr(wpproc, "RESOLUTION_ARRAY", [(2, 2), (2, 2)])
    monkeypatch.setattr(wpproc, "DISPLAY_OFFSET_ARRAY", [(0, 0), (3, 1)])
    return app_paths.cache


def test_simple_render_fills_virtual_canvas(profile_modules, monkeypatch, tmp_path, app_paths):
    _, wpproc = profile_modules
    cache = configure_render(wpproc, monkeypatch, app_paths)
    source = tmp_path / "source.png"
    with Image.new("RGB", (10, 3)) as image:
        for x in range(10):
            for y in range(3):
                image.putpixel((x, y), (20 * x, 60 * y, 10 * x + y))
        image.save(source)
    setter_calls = []
    monkeypatch.setattr(wpproc, "G_ACTIVE_PROFILE", "simple")
    monkeypatch.setattr(wpproc, "set_wallpaper", lambda *args, **kwargs: setter_calls.append((args, kwargs)))

    assert wpproc.span_single_image_simple(render_profile("simple", [str(source)]), False, paths=app_paths) == 0

    output = cache / "simple-a.png"
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
    assert setter_calls == [((str(output), False, [str(source)]), {"paths": app_paths, "set_command": ""})]


def test_multi_render_preserves_monitor_gaps(profile_modules, monkeypatch, tmp_path, app_paths):
    _, wpproc = profile_modules
    cache = configure_render(wpproc, monkeypatch, app_paths)
    red = tmp_path / "red.png"
    blue = tmp_path / "blue.png"
    create_image(red, (2, 2), (255, 0, 0))
    create_image(blue, (2, 2), (0, 0, 255))
    setter_calls = []
    monkeypatch.setattr(wpproc, "G_ACTIVE_PROFILE", "multi")
    monkeypatch.setattr(wpproc, "set_wallpaper", lambda *args, **kwargs: setter_calls.append((args, kwargs)))

    assert wpproc.set_multi_image_wallpaper(render_profile("multi", [str(red), str(blue)]), False, paths=app_paths) == 0

    output = cache / "multi-a.png"
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
    assert setter_calls == [((str(output), False, [str(red), str(blue)]), {"paths": app_paths, "set_command": ""})]


def test_render_cache_alternates_between_two_files(profile_modules, monkeypatch, tmp_path, app_paths):
    _, wpproc = profile_modules
    cache = configure_render(wpproc, monkeypatch, app_paths)
    source = tmp_path / "source.png"
    create_image(source, (5, 3), (10, 20, 30))
    monkeypatch.setattr(wpproc, "G_ACTIVE_PROFILE", "other")
    monkeypatch.setattr(wpproc, "set_wallpaper", lambda *args, **kwargs: None)
    profile = render_profile("alternating", [str(source)])

    expected = [("alternating-a.png",), ("alternating-b.png",), ("alternating-a.png",)]
    for files in expected:
        assert wpproc.span_single_image_simple(profile, False, paths=app_paths) == 0
        assert tuple(sorted(path.name for path in cache.iterdir())) == files


def test_windows_cache_uses_jpeg_extension(profile_modules, monkeypatch, tmp_path, app_paths):
    _, wpproc = profile_modules
    cache = configure_render(wpproc, monkeypatch, app_paths)
    monkeypatch.setattr(wpproc, "IS_WINDOWS", True)

    output, old_output = wpproc.alternating_outputfile(cache, "windows")

    assert output == str(cache / "windows-a.jpg")
    assert old_output == str(cache / "windows-b.jpg")
