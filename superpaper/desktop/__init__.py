"""Integration with the operating system: setting the wallpaper, the tray icon and menu, hotkeys.

desktop/ is the only place that runs host programs or talks to D-Bus, AppKit, the registry
or win32. What goes wrong comes back as a Result, never as an exception, an exit or a dialog.
Each OS has one module with the functions of backend.Desktop; current() picks it.
"""

import sys

from superpaper.desktop.backend import Desktop


def current() -> Desktop:
    """The module for the operating system Superpaper runs on."""
    match sys.platform:
        case "linux":
            from superpaper.desktop import linux

            return linux
        case "darwin":
            from superpaper.desktop import macos

            return macos
        case "win32":
            from superpaper.desktop import windows

            return windows
        case _:
            from superpaper.desktop import unknown

            return unknown
