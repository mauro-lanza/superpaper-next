"""Set the wallpaper on Windows, through Active Desktop."""

import ctypes
import winreg

import pythoncom  # ty:ignore[unresolved-import]
import pywintypes  # ty:ignore[unresolved-import]
import win32gui  # ty:ignore[unresolved-import]
from win32com.shell import shell, shellcon  # ty:ignore[unresolved-import]

from superpaper.desktop.process import Result

user32 = ctypes.windll.user32  # ty:ignore[unresolved-attribute]
DESKTOP_KEY = r"Control Panel\Desktop"


def set_spanmode() -> Result:
    """Set Windows to span one image across the displays."""
    # WallpaperStyle 22 is Span; it only applies with TileWallpaper off.
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DESKTOP_KEY, 0, winreg.KEY_SET_VALUE) as key:  # ty:ignore[unresolved-attribute]
            winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "22")  # ty:ignore[unresolved-attribute]
            winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")  # ty:ignore[unresolved-attribute]
    except OSError as error:
        return Result(f"Could not set Windows to span the displays: {error}")
    return Result()


def set_wallpaper(image: str) -> Result:
    """Show ``image``, which spans the displays when Windows is set to span."""
    try:
        set_wallpaper_win(image)
    except Exception as error:  # COM and Win32 failures come in many types
        return Result(f"Windows did not take the wallpaper: {error}")
    return Result()


def find_window_handles(window_class: str) -> list[int]:
    """Top-level windows whose class name contains ``window_class``."""

    def collect(handle: int, handles: list[int]) -> bool | None:
        if window_class not in (win32gui.GetClassName(handle) or ""):
            return True  # continue enumeration
        handles.append(handle)

    try:
        handle_list: list[int] = []
        win32gui.EnumWindows(collect, handle_list)
    except pywintypes.error:
        return []
    else:
        return handle_list


def force_refresh_syspar() -> None:
    user32.UpdatePerUserSystemParameters(1)


def enable_activedesktop() -> None:
    """https://stackoverflow.com/a/16351170"""
    try:
        progman = find_window_handles("Progman")[0]
        cryptic_params = (0x52C, 0, 0, 0, 500, None)
        user32.SendMessageTimeoutW(progman, *cryptic_params)
    except IndexError as e:
        msg = "Cannot enable Active Desktop"
        raise OSError(msg) from e


def set_wallpaper_win(image_path: str) -> None:
    enable_activedesktop()
    pythoncom.CoInitialize()
    iad = pythoncom.CoCreateInstance(
        shell.CLSID_ActiveDesktop, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IActiveDesktop
    )
    iad.SetWallpaper(str(image_path), 0)
    iad.ApplyChanges(shellcon.AD_APPLY_ALL)
    force_refresh_syspar()
