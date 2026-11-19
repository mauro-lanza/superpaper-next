"""Set the wallpaper on Windows, through Active Desktop."""

import ctypes
import winreg

import pythoncom  # ty:ignore[unresolved-import]
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
