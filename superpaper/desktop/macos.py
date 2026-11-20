"""Set the wallpaper on macOS: one image per screen, through AppKit."""

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from AppKit import NSScreen, NSWorkspace  # ty:ignore[unresolved-import]
from Foundation import NSURL  # ty:ignore[unresolved-import]

from superpaper.desktop.monitors import Monitor
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


def default_dirs(environ: Mapping[str, str], install: Path) -> tuple[Path, Path]:
    """~/Library/Application Support/Superpaper and ~/Library/Caches/Superpaper."""
    library = Path(environ.get("HOME") or os.path.expanduser("~")) / "Library"
    return library / "Application Support" / "Superpaper", library / "Caches" / "Superpaper"


def hotkeys_by_default() -> bool:
    """Hotkeys are off."""
    return False


def render_extension() -> str:
    """Rendered wallpapers are PNG."""
    return "png"


def strict_profile_names() -> bool:
    """Only new profile names must follow the portable rules."""
    return False


def set_spanmode(set_command: str) -> Result:
    """Nothing to set: every screen has its own picture."""
    return Result()


def open_folder(folder: Path) -> Result:
    """Show ``folder`` in the desktop's file manager."""
    return run(["open", os.fspath(folder)])


def detect_monitors() -> list[Monitor]:
    """The screens in pixels from the top-left corner of the primary screen."""
    return [monitor for monitor, _screen in _screens()]


def _screens() -> list[tuple[Monitor, Any]]:
    """Each screen with its monitor, sorted by position: the one order of detection and wallpaper pieces.

    Cocoa's origin is the primary screen's bottom-left, so ``top = primary height - (y + height)``
    in points. Points become pixels at the primary screen's scale, so offsets stay consistent on mixed
    scales; each size uses its own screen's scale.
    """
    screens = list(NSScreen.screens())
    if not screens:
        return []
    primary_height = _frame(screens[0]).size.height
    primary_scale = screens[0].backingScaleFactor()
    found = []
    for screen in screens:
        frame = _frame(screen)
        scale = screen.backingScaleFactor()
        top = primary_height - (frame.origin.y + frame.size.height)
        width_mm, height_mm = _size_in_mm(screen)
        monitor = Monitor(
            name=screen.localizedName(),
            x=round(frame.origin.x * primary_scale),
            y=round(top * primary_scale),
            width=round(frame.size.width * scale),
            height=round(frame.size.height * scale),
            width_mm=width_mm,
            height_mm=height_mm,
        )
        found.append((monitor, screen))
    found.sort(key=lambda pair: (pair[0].x, pair[0].y))
    return found


def _frame(screen: Any) -> Any:
    frame = screen.frame
    return frame() if callable(frame) else frame


def _size_in_mm(screen: Any) -> tuple[int, int] | tuple[None, None]:
    """The screen's physical size, or unknown without pyobjc-framework-Quartz."""
    try:
        from Quartz import CGDisplayScreenSize  # ty:ignore[unresolved-import]
    except ImportError:
        return None, None
    size = CGDisplayScreenSize(screen.deviceDescription()["NSScreenNumber"])
    return round(size.width), round(size.height)


def set_wallpaper(wallpaper: Wallpaper, *, set_command: str, profiles: ProfileWallpapers) -> Result:
    """Show the pieces of ``wallpaper``, one image per screen, in Superpaper's display order.

    Each screen has its own desktop picture. NSScreen doesn't list the screens in any
    particular order, so they are sorted by position first (see ``_screens``).
    https://developer.apple.com/documentation/appkit/nsscreen/1388393-screens
    https://developer.apple.com/documentation/appkit/nsworkspace/1527228-setdesktopimageurl
    """
    if not isinstance(wallpaper, Pieces):
        return Result("macOS needs the wallpaper cut into one image per screen.")
    screens = [screen for _monitor, screen in _screens()]
    if len(screens) != len(wallpaper.pieces):
        return Result(f"There are {len(screens)} screens but {len(wallpaper.pieces)} wallpaper pieces.")
    workspace = NSWorkspace.sharedWorkspace()
    problems = []
    for screen, piece in zip(screens, wallpaper.pieces, strict=True):
        url = NSURL.fileURLWithPath_(piece)
        _done, error = workspace.setDesktopImageURL_forScreen_options_error_(url, screen, {}, None)
        if error:
            problems.append(f"setDesktopImageURL failed with error: {error}")
    return Result("; ".join(problems)) if problems else Result()
