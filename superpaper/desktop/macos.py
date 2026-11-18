"""Set the wallpaper on macOS: one image per screen, through AppKit."""

from typing import Any

from AppKit import NSScreen, NSWorkspace  # ty:ignore[unresolved-import]
from Foundation import NSURL  # ty:ignore[unresolved-import]

from superpaper.desktop.process import Result
from superpaper.desktop.wallpaper import Pieces, Wallpaper


def set_wallpaper(wallpaper: Wallpaper) -> Result:
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
