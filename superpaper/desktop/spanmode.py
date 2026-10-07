"""Make the desktop span one wallpaper image across all displays, where that is a setting."""

import logging
import sys
from typing import Any

from superpaper.desktop import linux
from superpaper.desktop.process import Result
from superpaper.sp_platform import IS_LINUX, IS_WINDOWS

logger = logging.getLogger(__name__)

# winreg is a Windows-only stdlib module. Bind a fallback so the name is always
# defined, and guard the import with a literal sys.platform comparison so type
# checkers treat it as dead code off-Windows (a derived constant would not work).
winreg: Any = None
if sys.platform == "win32":
    import winreg


def set_spanmode():
    """Sets host OS desktop background to span all displays."""
    if IS_WINDOWS:
        # Windows wallpaper fitting style codes:
        # Fill = 10
        # Fit = 6
        # Stretch = 2
        # Tile = 0 and there is another key called "TileWallpaper" which needs value 1
        # Center = 0 (with key "TileWallpaper" = 0)
        # Span = 22

        # Both WallpaperStyle and TileWallpaper keys need to be set under HKEY_CURRENT_USER\Control Panel\Desktop
        reg_key_desktop = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(reg_key_desktop, "WallpaperStyle", 0, winreg.REG_SZ, "22")
        winreg.SetValueEx(reg_key_desktop, "TileWallpaper", 0, winreg.REG_SZ, "0")
    elif IS_LINUX:
        result = _linux_spanmode()
        if not result.ok:
            logger.info("Could not set the desktop to span the displays: %s", result.problem)


def _linux_spanmode() -> Result:
    match linux.setter(""):
        case "gnome":
            return linux.gsettings("org.gnome.desktop.background", "picture-options", "spanned")
        case "cinnamon":
            return linux.gsettings("org.cinnamon.desktop.background", "picture-options", "spanned")
        case "mate":
            return linux.gsettings("org.mate.background", "picture-options", "spanned")
        case "lxqt":
            return linux.pcmanfm("--wallpaper-mode=stretch")
        case _:
            return Result()  # nothing to set, or the desktop sets one image per display
