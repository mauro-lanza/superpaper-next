from superpaper.desktop.wallpaper import Pieces
from tests.desktop.conftest import IMAGE, NO_PROFILES, assert_satisfies_desktop


def test_macos_shows_one_piece_per_screen_in_display_order(appkit, set_images):
    macos = appkit(screens=[(1920, 0, 1920, 1080), (0, 0, 1920, 1080)])

    result = macos.set_wallpaper(Pieces(IMAGE, ("/left.png", "/right.png")), set_command="", profiles=NO_PROFILES)

    assert result.ok
    assert set_images == [(2, "/left.png"), (1, "/right.png")]


def test_macos_reports_pieces_that_dont_match_the_screens(appkit, set_images):
    macos = appkit(screens=[(0, 0, 1920, 1080), (1920, 0, 1920, 1080)])

    result = macos.set_wallpaper(Pieces(IMAGE, ("/only.png",)), set_command="", profiles=NO_PROFILES)

    assert result.problem == "There are 2 screens but 1 wallpaper pieces."
    assert set_images == []


def test_macos_detects_screens_from_the_top_left_of_the_primary_one(appkit):
    macos = appkit(screens=[(0, 0, 2560, 1440), (2560, -265, 1080, 1920)])

    found = macos.detect_monitors()

    assert [(m.x, m.y, m.width, m.height) for m in found] == [(0, 0, 2560, 1440), (2560, -215, 1080, 1920)]
    assert [m.name for m in found] == ["Screen 1", "Screen 2"]


def test_macos_detects_retina_screens_in_pixels(appkit):
    macos = appkit(screens=[(0, 0, 1440, 900, 2.0), (1440, 100, 1280, 800, 2.0)])

    found = macos.detect_monitors()

    assert [(m.x, m.y, m.width, m.height) for m in found] == [(0, 0, 2880, 1800), (2880, 0, 2560, 1600)]


def test_macos_scales_offsets_by_the_primary_screen_but_sizes_by_each_screen(appkit):
    macos = appkit(screens=[(0, 0, 1440, 900, 2.0), (1440, 0, 1920, 1080, 1.0)])

    found = macos.detect_monitors()

    assert [(m.x, m.y, m.width, m.height) for m in found] == [(0, 0, 2880, 1800), (2880, -360, 1920, 1080)]


def test_macos_reads_the_physical_size_from_quartz(appkit):
    macos = appkit(screens=[(0, 0, 2560, 1440)], sizes_mm={1: (597.0, 336.4)})

    (found,) = macos.detect_monitors()

    assert (found.width_mm, found.height_mm) == (597, 336)


def test_macos_detects_and_assigns_screens_in_the_same_order(appkit, set_images):
    macos = appkit(screens=[(0, 0, 1920, 1080), (-1920, 0, 1920, 1080), (1920, -500, 1920, 1080)])

    macos.set_wallpaper(Pieces(IMAGE, ("/a.png", "/b.png", "/c.png")), set_command="", profiles=NO_PROFILES)

    names = [m.name for m in macos.detect_monitors()]
    assert [f"Screen {number}" for number, _ in set_images] == names
    assert names == ["Screen 2", "Screen 1", "Screen 3"]


def test_macos_opens_the_folder_with_open(appkit, ran, tmp_path):
    macos = appkit(screens=[(0, 0, 1920, 1080)])

    assert macos.open_folder(tmp_path).ok

    assert [command for command, _ in ran] == [["open", str(tmp_path)]]


def test_macos_satisfies_the_desktop_interface(appkit):
    assert_satisfies_desktop(appkit(screens=[(0, 0, 1920, 1080)]))


def test_macos_watches_screen_parameter_changes(appkit, notification_center):
    macos = appkit(screens=[(0, 0, 1920, 1080)])
    changes = []

    assert macos.watch_displays(lambda: changes.append("changed")) is True

    notification_center.post("screen parameters changed")
    notification_center.post("another notification")
    assert changes == ["changed"]


def test_macos_keeps_its_files_in_the_library(appkit, tmp_path):
    macos = appkit(screens=[(0, 0, 1920, 1080)])

    config, cache = macos.default_dirs({"HOME": str(tmp_path / "home")}, tmp_path / "app")

    assert config == tmp_path / "home" / "Library" / "Application Support" / "Superpaper"
    assert cache == tmp_path / "home" / "Library" / "Caches" / "Superpaper"
