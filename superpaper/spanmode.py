"""Control host OS desktop background spanning mode when needed."""
import os
import subprocess
import sys
from typing import Any

from superpaper.sp_platform import IS_LINUX, IS_MACOS, IS_WINDOWS

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
        reg_key_desktop = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                        r'Control Panel\Desktop',
                                        0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(reg_key_desktop, "WallpaperStyle", 0, winreg.REG_SZ, "22")
        winreg.SetValueEx(reg_key_desktop, "TileWallpaper", 0, winreg.REG_SZ, "0")
    elif IS_LINUX:
        desk_env = os.environ.get("DESKTOP_SESSION")
        if desk_env:
            if desk_env in ["gnome", "gnome-wayland", "gnome-xorg",
                            "unity", "ubuntu",
                            "pantheon", "budgie-desktop",
                            "pop"]:
                subprocess.run(["/usr/bin/gsettings", "set",
                                "org.gnome.desktop.background", "picture-options",
                                "spanned"])
            elif desk_env in ["cinnamon"]:
                subprocess.run(["/usr/bin/gsettings", "set",
                                "org.cinnamon.desktop.background", "picture-options",
                                "spanned"])
            elif desk_env in ["mate"]:
                subprocess.run(["/usr/bin/gsettings", "set",
                                "org.mate.background", "picture-options",
                                "spanned"])
            elif desk_env.lower() == "lubuntu" or "lxqt" in desk_env.lower():
                try:
                    subprocess.run(["pcmanfm", "--wallpaper-mode=stretch"])
                except OSError:
                    try:
                        subprocess.run(["pcmanfm-qt", "--wallpaper-mode=stretch"])
                    except OSError:
                        pass
    elif IS_MACOS:
        # Mac support TODO
        pass
    else:
        pass
