"""Integration with the operating system: setting the wallpaper, the tray icon and menu, hotkeys.

desktop/ is the only place that runs host programs or talks to D-Bus, AppKit, the registry
or win32. What goes wrong comes back as a Result, never as an exception, an exit or a dialog.
Each OS has one module with the functions of backend.Desktop; current() picks it.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from superpaper.desktop.backend import Desktop
from superpaper.desktop.linux.kde import Activities
from superpaper.desktop.process import Result
from superpaper.desktop.wallpaper import Wallpaper


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


def takes_pieces(set_command: str) -> bool:
    """Whether the desktop sets one image per display, so a wallpaper is cut into pieces."""
    return current().takes_pieces(set_command)


def keeps_wallpaper() -> bool:
    """Whether the desktop shows the last wallpaper again after a restart by itself."""
    return current().keeps_wallpaper()


def setter_problem(set_command: str) -> str | None:
    """Why Superpaper can't set the wallpaper on this desktop, if it can't."""
    return current().setter_problem(set_command)


def set_spanmode(set_command: str) -> Result:
    """Make the desktop span one wallpaper image across all displays, where that is a setting.

    ``set_command`` is the user's own setter command, if any (Linux only).
    """
    return current().set_spanmode(set_command)


def set_wallpaper(wallpaper: Wallpaper, *, set_command: str, activities: Activities) -> Result:
    """Show ``wallpaper``: its pieces, one image per display, on desktops that take those
    (see takes_pieces), else its image.

    ``set_command`` is the user's own setter command, if any (Linux only).
    """
    return current().set_wallpaper(wallpaper, set_command=set_command, activities=activities)


def run_hook(script: Path, image: str, sources: Sequence[str]) -> Result:
    """Run the user's script after a wallpaper change, with the image and then each source
    image as its own argument."""
    return current().run_hook(script, image, sources)


def open_folder(folder: Path) -> Result:
    """Show ``folder`` in the desktop's file manager."""
    return current().open_folder(folder)
