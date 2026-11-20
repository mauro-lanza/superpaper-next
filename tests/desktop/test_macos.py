import sys
from types import ModuleType, SimpleNamespace

from superpaper.desktop.wallpaper import Pieces
from tests.desktop.conftest import IMAGE, NO_PROFILES, assert_satisfies_desktop


def test_macos_shows_one_piece_per_screen_in_display_order(appkit):
    set_images = appkit(screens=[(1920, 0, 1920, 1080), (0, 0, 1920, 1080)])
    from superpaper.desktop import macos

    result = macos.set_wallpaper(Pieces(IMAGE, ("/left.png", "/right.png")), set_command="", profiles=NO_PROFILES)

    assert result.ok
    assert set_images == [(2, "/left.png"), (1, "/right.png")]


def test_macos_reports_pieces_that_dont_match_the_screens(appkit):
    set_images = appkit(screens=[(0, 0, 1920, 1080), (1920, 0, 1920, 1080)])
    from superpaper.desktop import macos

    result = macos.set_wallpaper(Pieces(IMAGE, ("/only.png",)), set_command="", profiles=NO_PROFILES)

    assert result.problem == "There are 2 screens but 1 wallpaper pieces."
    assert set_images == []


def test_macos_detects_screens_from_the_top_left_of_the_primary_one(appkit):
    appkit(screens=[(0, 0, 2560, 1440), (2560, -265, 1080, 1920)])
    from superpaper.desktop import macos

    found = macos.detect_monitors()

    assert [(m.x, m.y, m.width, m.height) for m in found] == [(0, 0, 2560, 1440), (2560, -215, 1080, 1920)]
    assert [m.name for m in found] == ["Screen 1", "Screen 2"]
    assert all(m.width_mm is None and m.height_mm is None for m in found)


def test_macos_detects_retina_screens_in_pixels(appkit):
    appkit(screens=[(0, 0, 1440, 900, 2.0), (1440, 100, 1280, 800, 2.0)])
    from superpaper.desktop import macos

    found = macos.detect_monitors()

    assert [(m.x, m.y, m.width, m.height) for m in found] == [(0, 0, 2880, 1800), (2880, 0, 2560, 1600)]


def test_macos_scales_offsets_by_the_primary_screen_but_sizes_by_each_screen(appkit):
    appkit(screens=[(0, 0, 1440, 900, 2.0), (1440, 0, 1920, 1080, 1.0)])
    from superpaper.desktop import macos

    found = macos.detect_monitors()

    assert [(m.x, m.y, m.width, m.height) for m in found] == [(0, 0, 2880, 1800), (2880, -360, 1920, 1080)]


def test_macos_reads_the_physical_size_from_quartz(appkit, monkeypatch):
    appkit(screens=[(0, 0, 2560, 1440)])
    quartz = ModuleType("Quartz")
    quartz.CGDisplayScreenSize = lambda number: SimpleNamespace(width=597.0, height=336.4) if number == 1 else None
    monkeypatch.setitem(sys.modules, "Quartz", quartz)
    from superpaper.desktop import macos

    (found,) = macos.detect_monitors()

    assert (found.width_mm, found.height_mm) == (597, 336)


def test_macos_detects_and_assigns_screens_in_the_same_order(appkit):
    set_images = appkit(screens=[(0, 0, 1920, 1080), (-1920, 0, 1920, 1080), (1920, -500, 1920, 1080)])
    from superpaper.desktop import macos

    macos.set_wallpaper(Pieces(IMAGE, ("/a.png", "/b.png", "/c.png")), set_command="", profiles=NO_PROFILES)

    names = [m.name for m in macos.detect_monitors()]
    assert [f"Screen {number}" for number, _ in set_images] == names
    assert names == ["Screen 2", "Screen 1", "Screen 3"]


def test_macos_cuts_the_wallpaper_into_pieces_and_spans_nothing(appkit):
    appkit(screens=[(0, 0, 1920, 1080)])
    from superpaper.desktop import macos

    assert macos.takes_pieces("") is True
    assert macos.keeps_wallpaper() is False
    assert macos.setter_problem("") is None
    assert macos.set_spanmode("").ok


def test_macos_opens_the_folder_with_open(appkit, ran, tmp_path):
    appkit(screens=[(0, 0, 1920, 1080)])
    from superpaper.desktop import macos

    assert macos.open_folder(tmp_path).ok

    assert [command for command, _ in ran] == [["open", str(tmp_path)]]


def test_macos_satisfies_the_desktop_interface(appkit):
    appkit(screens=[(0, 0, 1920, 1080)])
    from superpaper.desktop import macos

    assert_satisfies_desktop(macos)


def test_macos_keeps_its_files_in_the_library(appkit, tmp_path):
    appkit(screens=[(0, 0, 1920, 1080)])
    from superpaper.desktop import macos

    config, cache = macos.default_dirs({"HOME": str(tmp_path / "home")}, tmp_path / "app")

    assert config == tmp_path / "home" / "Library" / "Application Support" / "Superpaper"
    assert cache == tmp_path / "home" / "Library" / "Caches" / "Superpaper"


def test_macos_defaults_are_png_renders_without_hotkeys_and_portable_profile_names(appkit):
    appkit(screens=[(0, 0, 1920, 1080)])
    from superpaper.desktop import macos

    assert macos.render_extension() == "png"
    assert macos.hotkeys_by_default() is False
    assert macos.strict_profile_names() is False
