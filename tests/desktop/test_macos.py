import sys
from types import ModuleType, SimpleNamespace

import pytest

import superpaper.desktop as desktop
from superpaper.desktop.wallpaper import Pieces
from tests.desktop.conftest import IMAGE


@pytest.fixture
def appkit(monkeypatch):
    """AppKit, as ``install(screens)`` gives it with screens at the given x positions, in any order.

    ``install`` returns what was set where, as (screen x, image) pairs.
    """

    def install(screens):
        set_images = []
        workspace = SimpleNamespace(
            setDesktopImageURL_forScreen_options_error_=lambda url, screen, options, error: (
                set_images.append((screen.x, url)) or (True, None)
            )
        )
        appkit_module = ModuleType("AppKit")
        appkit_module.NSScreen = SimpleNamespace(
            screens=lambda: [
                SimpleNamespace(x=x, frame=SimpleNamespace(origin=SimpleNamespace(x=x, y=0))) for x in screens
            ]
        )
        appkit_module.NSWorkspace = SimpleNamespace(sharedWorkspace=lambda: workspace)
        foundation = ModuleType("Foundation")
        foundation.NSURL = SimpleNamespace(fileURLWithPath_=lambda path: path)
        monkeypatch.setitem(sys.modules, "AppKit", appkit_module)
        monkeypatch.setitem(sys.modules, "Foundation", foundation)
        return set_images

    yield install
    sys.modules.pop("superpaper.desktop.macos", None)
    if hasattr(desktop, "macos"):
        del desktop.macos


def test_macos_shows_one_piece_per_screen_in_display_order(appkit):
    set_images = appkit(screens=[1920, 0])
    from superpaper.desktop import macos

    result = macos.set_wallpaper(Pieces(IMAGE, ("/left.png", "/right.png")))

    assert result.ok
    assert set_images == [(0, "/left.png"), (1920, "/right.png")]


def test_macos_reports_pieces_that_dont_match_the_screens(appkit):
    set_images = appkit(screens=[0, 1920])
    from superpaper.desktop import macos

    result = macos.set_wallpaper(Pieces(IMAGE, ("/only.png",)))

    assert result.problem == "There are 2 screens but 1 wallpaper pieces."
    assert set_images == []
