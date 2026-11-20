"""A platform Superpaper has no support for: nothing can be set."""

import os
import sys
from pathlib import Path

from superpaper.desktop.linux.kde import Activities
from superpaper.desktop.process import Result, run
from superpaper.desktop.process import run_hook as run_hook
from superpaper.desktop.wallpaper import Wallpaper


def takes_pieces(set_command: str) -> bool:
    """Whether the desktop sets one image per display, so a wallpaper is cut into pieces."""
    return False


def keeps_wallpaper() -> bool:
    """Whether the desktop shows the last wallpaper again after a restart by itself."""
    return False


def setter_problem(set_command: str) -> str | None:
    """Why Superpaper can't set the wallpaper on this desktop, if it can't."""
    return None


def set_spanmode(set_command: str) -> Result:
    """Nothing to set."""
    return Result()


def set_wallpaper(wallpaper: Wallpaper, *, set_command: str, activities: Activities) -> Result:
    """Report that the platform is not supported."""
    return Result(f"Unknown platform: {sys.platform}")


def open_folder(folder: Path) -> Result:
    """Show ``folder`` in the desktop's file manager."""
    return run(["xdg-open", os.fspath(folder)])
