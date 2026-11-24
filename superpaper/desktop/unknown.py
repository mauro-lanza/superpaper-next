"""A platform Superpaper has no support for: nothing can be set."""

import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from superpaper.desktop.monitors import detect_monitors as detect_monitors
from superpaper.desktop.process import Result, run
from superpaper.desktop.process import run_hook as run_hook
from superpaper.desktop.tray_menu import MenuEntry, TrayHandle
from superpaper.desktop.wallpaper import ProfileWallpapers, Wallpaper


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
    return False


def keeps_wallpaper() -> bool:
    return False


def setter_problem(set_command: str) -> str | None:
    return f"Unknown platform: {sys.platform}"


def default_dirs(environ: Mapping[str, str], install: Path) -> tuple[Path, Path]:
    """Beside the installation."""
    return install, install / "temp"


def hotkeys_by_default() -> bool:
    """Hotkeys are on."""
    return True


def render_extension() -> str:
    """Rendered wallpapers are PNG."""
    return "png"


def strict_profile_names() -> bool:
    """Only new profile names must follow the portable rules."""
    return False


def set_spanmode(set_command: str) -> Result:
    """Nothing to set."""
    return Result()


def watch_displays(on_change: Callable[[], None]) -> bool:
    """Nothing reports display changes."""
    return False


def set_wallpaper(wallpaper: Wallpaper, *, set_command: str, profiles: ProfileWallpapers) -> Result:
    """Report that the platform is not supported."""
    return Result(f"Unknown platform: {sys.platform}")


def open_folder(folder: Path) -> Result:
    return run(["xdg-open", os.fspath(folder)])
