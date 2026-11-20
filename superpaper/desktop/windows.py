"""Set the wallpaper on Windows, through Active Desktop."""

import ctypes
import os
import winreg
from pathlib import Path

import pythoncom  # ty:ignore[unresolved-import]
import win32gui  # ty:ignore[unresolved-import]
from win32com.shell import shell, shellcon  # ty:ignore[unresolved-import]

from superpaper.desktop.linux.kde import Activities
from superpaper.desktop.process import Result
from superpaper.desktop.process import run_hook as run_hook
from superpaper.desktop.wallpaper import Wallpaper

user32 = ctypes.windll.user32  # ty:ignore[unresolved-attribute]
DESKTOP_KEY = r"Control Panel\Desktop"


def takes_pieces(set_command: str) -> bool:
    """Whether the desktop sets one image per display, so a wallpaper is cut into pieces."""
    return False


def keeps_wallpaper() -> bool:
    """Whether the desktop shows the last wallpaper again after a restart by itself."""
    return True


def setter_problem(set_command: str) -> str | None:
    """Why Superpaper can't set the wallpaper on this desktop, if it can't."""
    return None


def open_folder(folder: Path) -> Result:
    """Show ``folder`` in the desktop's file manager."""
    try:
        os.startfile(folder)  # ty:ignore[unresolved-attribute]
    except OSError as error:
        return Result(f"Could not open {folder}: {error}")
    return Result()


def set_spanmode(set_command: str) -> Result:
    """Set Windows to span one image across the displays."""
    # WallpaperStyle 22 is Span; it only applies with TileWallpaper off.
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY, 0, winreg.KEY_SET_VALUE) as key:  # ty:ignore[unresolved-attribute]
            winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "22")  # ty:ignore[unresolved-attribute]
            winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")  # ty:ignore[unresolved-attribute]
    except OSError as error:
        return Result(f"Could not set Windows to span the displays: {error}")
    return Result()


def set_wallpaper(wallpaper: Wallpaper, *, set_command: str, activities: Activities) -> Result:
    """Show the image of ``wallpaper``, which spans the displays when Windows is set to span."""
    image = wallpaper.image

    def collect(handle: int, handles: list[int]) -> bool:
        if "Progman" in (win32gui.GetClassName(handle) or ""):
            handles.append(handle)
        return True  # returning None would stop the enumeration

    try:
        progman_handles: list[int] = []
        win32gui.EnumWindows(collect, progman_handles)
        if not progman_handles:
            return Result("Cannot enable Active Desktop")
        # https://stackoverflow.com/a/16351170
        user32.SendMessageTimeoutW(progman_handles[0], 0x52C, 0, 0, 0, 500, None)
        pythoncom.CoInitialize()
        try:
            iad = pythoncom.CoCreateInstance(
                shell.CLSID_ActiveDesktop, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IActiveDesktop
            )
            iad.SetWallpaper(image, 0)
            iad.ApplyChanges(shellcon.AD_APPLY_ALL)
            user32.UpdatePerUserSystemParameters(1)
        finally:
            pythoncom.CoUninitialize()
    except Exception as error:  # COM and Win32 failures come in many types
        return Result(f"Windows did not take the wallpaper: {error}")
    return Result()
