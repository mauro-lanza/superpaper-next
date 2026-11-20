"""Set the wallpaper on macOS: one image per screen, through AppKit."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from AppKit import NSScreen, NSWorkspace  # ty:ignore[unresolved-import]
from Foundation import NSURL  # ty:ignore[unresolved-import]

from superpaper.desktop.process import Result, run
from superpaper.desktop.process import run_hook as run_hook
from superpaper.desktop.tray_menu import MenuEntry, TrayHandle
from superpaper.desktop.wallpaper import Pieces, ProfileWallpapers, Wallpaper


def init_main_loop() -> None:
    """Nothing to prepare."""


def make_tray(
    *,
    menu: Callable[[], tuple[MenuEntry, ...]],
    call_soon: Callable[[Callable[[], None]], None],
    activate: Callable[[], None],
    secondary_activate: Callable[[], None],
    icon_path: str,
    title: str,
) -> TrayHandle | None:
    """wx's own tray icon is used."""
    return None


def wx_tray_clickable() -> bool:
    """wx's tray icon can be clicked."""
    return True


def hotkey_problems_in_dialog() -> bool:
    """A hotkey that can't be registered is shown to the user."""
    return True


def takes_pieces(set_command: str) -> bool:
    """Whether the desktop sets one image per display, so a wallpaper is cut into pieces."""
    return True


def keeps_wallpaper() -> bool:
    """Whether the desktop shows the last wallpaper again after a restart by itself."""
    return False


def setter_problem(set_command: str) -> str | None:
    """Why Superpaper can't set the wallpaper on this desktop, if it can't."""
    return None


def set_spanmode(set_command: str) -> Result:
    """Nothing to set: every screen has its own picture."""
    return Result()


def open_folder(folder: Path) -> Result:
    """Show ``folder`` in the desktop's file manager."""
    return run(["open", os.fspath(folder)])


def set_wallpaper(wallpaper: Wallpaper, *, set_command: str, profiles: ProfileWallpapers) -> Result:
    """Show the pieces of ``wallpaper``, one image per screen, in Superpaper's display order.

    Each screen has its own desktop picture. NSScreen doesn't list the screens in any
    particular order, so they are sorted by position first.
    https://developer.apple.com/documentation/appkit/nsscreen/1388393-screens
    https://developer.apple.com/documentation/appkit/nsworkspace/1527228-setdesktopimageurl
    """
    if not isinstance(wallpaper, Pieces):
        return Result("macOS needs the wallpaper cut into one image per screen.")
    screens = []
    for screen in NSScreen.screens():
        frame: Any = screen.frame
        if callable(frame):
            frame = frame()
        screens.append(((int(frame.origin.x), int(frame.origin.y)), screen))
    screens.sort(key=lambda pair: pair[0])
    if len(screens) != len(wallpaper.pieces):
        return Result(f"There are {len(screens)} screens but {len(wallpaper.pieces)} wallpaper pieces.")
    workspace = NSWorkspace.sharedWorkspace()
    problems = []
    for (_origin, screen), piece in zip(screens, wallpaper.pieces, strict=True):
        url = NSURL.fileURLWithPath_(piece)
        _done, error = workspace.setDesktopImageURL_forScreen_options_error_(url, screen, {}, None)
        if error:
            problems.append(f"setDesktopImageURL failed with error: {error}")
    return Result("; ".join(problems)) if problems else Result()
