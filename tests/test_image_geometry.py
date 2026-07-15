from PIL import Image


def test_compute_canvas_with_vertical_offset(profile_modules):
    _, wpproc = profile_modules

    assert wpproc.compute_canvas([(1920, 1080), (1280, 1024)], [(0, 0), (1920, 200)]) == [3200, 1224]


def test_working_canvas_includes_outer_bezels(profile_modules):
    _, wpproc = profile_modules

    assert wpproc.compute_working_canvas([(0, 0, 100, 80), (100, 10, 200, 90)], [(5, 4), (12, 8)]) == [212, 98]


def test_resize_to_fill_alignment(profile_modules):
    _, wpproc = profile_modules
    image = Image.new("RGB", (4, 2))
    for x in range(4):
        for y in range(2):
            image.putpixel((x, y), (x * 50, 0, 0))

    left = wpproc.resize_to_fill(image, (2, 2), offset=(-1, 0))
    right = wpproc.resize_to_fill(image, (2, 2), offset=(1, 0))

    assert left.getpixel((0, 0))[0] < right.getpixel((0, 0))[0]


def test_simple_renderer_ignores_empty_selection(profile_modules, monkeypatch):
    _, wpproc = profile_modules

    class EmptyProfile:
        name = "empty"

        @staticmethod
        def next_wallpaper_files():
            return []

    setter_called = False

    def record_setter(*args, **kwargs):
        nonlocal setter_called
        setter_called = True

    monkeypatch.setattr(wpproc, "set_wallpaper", record_setter)

    assert wpproc.span_single_image_simple(EmptyProfile(), force=True) is None
    assert setter_called is False
