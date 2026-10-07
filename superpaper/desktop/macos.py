"""Set the wallpaper on macOS: one image per screen, through AppKit."""

from collections.abc import Sequence
from typing import Any

from AppKit import NSScreen, NSWorkspace  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]
from Foundation import NSURL  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

from superpaper.desktop.process import Result


def set_wallpaper(pieces: Sequence[str]) -> Result:
    """Show ``pieces``, one image per screen, in Superpaper's display order.

    Each screen has its own desktop picture. NSScreen doesn't list the screens in any
    particular order, so they are sorted by position first.
    https://developer.apple.com/documentation/appkit/nsscreen/1388393-screens
    https://developer.apple.com/documentation/appkit/nsworkspace/1527228-setdesktopimageurl
    """
    screens = []
    for screen in NSScreen.screens():
        frame: Any = screen.frame
        if callable(frame):
            frame = frame()
        screens.append(((int(frame.origin.x), int(frame.origin.y)), screen))
    screens.sort(key=lambda pair: pair[0])
    workspace = NSWorkspace.sharedWorkspace()
    problems = []
    for (_origin, screen), piece in zip(screens, pieces):
        url = NSURL.fileURLWithPath_(piece)
        _done, error = workspace.setDesktopImageURL_forScreen_options_error_(url, screen, {}, None)
        if error:
            problems.append(f"setDesktopImageURL failed with error: {error}")
    return Result("; ".join(problems)) if problems else Result()
