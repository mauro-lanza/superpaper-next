"""Hand a finished wallpaper to the desktop.

desktop/ is the only place that runs host programs or talks to D-Bus, AppKit or win32.
What goes wrong comes back as a Result, never as an exception, an exit or a dialog.
"""

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from superpaper.desktop import kde, linux
from superpaper.desktop.process import Result, run


def takes_pieces(set_command: str) -> bool:
    """Whether the desktop sets one image per display, so a wallpaper is cut into pieces."""
    if sys.platform == "darwin":
        return True
    return sys.platform == "linux" and linux.setter(set_command) == "kde"


def setter_problem(set_command: str) -> str | None:
    """Why Superpaper can't set the wallpaper on this desktop, if it can't."""
    if sys.platform == "linux" and linux.setter(set_command) == "unknown":
        return linux.UNKNOWN_DESKTOP
    return None


def set_wallpaper(image: str, pieces: Sequence[str] | None, *, set_command: str, activities: kde.Activities) -> Result:
    """Show ``image`` as the wallpaper, or ``pieces``, one image per display in Superpaper's
    display order, on desktops that take those (see takes_pieces).

    ``set_command`` is the user's own setter command, if any (Linux only).
    """
    if sys.platform == "win32":
        from superpaper.desktop import windows

        return windows.set_wallpaper(image)
    if sys.platform == "darwin":
        from superpaper.desktop import macos

        return macos.set_wallpaper(pieces or [])
    if sys.platform == "linux":
        return linux.set_wallpaper(image, pieces, set_command=set_command, activities=activities)
    return Result(f"Unknown platform: {sys.platform}")


def run_hook(script: Path, image: str, sources: Sequence[str]) -> Result:
    """Run the user's script after a wallpaper change, with the image and then each source
    image as its own argument."""
    return run(["python3", str(script), str(image), *map(str, sources)])


def open_folder(folder: Path) -> Result:
    """Show ``folder`` in the desktop's file manager."""
    if sys.platform == "win32":
        try:
            os.startfile(folder)  # pyright: ignore[reportAttributeAccessIssue]
        except OSError as error:
            return Result(f"Could not open {folder}: {error}")
        return Result()
    return run(["open" if sys.platform == "darwin" else "xdg-open", os.fspath(folder)])
