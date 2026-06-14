import ctypes
from typing import Optional

# pywin32 ships type stubs but the compiled modules are Windows-only, so the
# source can't be resolved off-Windows (reportMissingModuleSource).
import pythoncom  # pyright: ignore[reportMissingModuleSource]  # ty:ignore[unresolved-import]
import pywintypes  # pyright: ignore[reportMissingModuleSource]  # ty:ignore[unresolved-import]
import win32gui  # pyright: ignore[reportMissingModuleSource]  # ty:ignore[unresolved-import]
from win32com.shell import shell, shellcon  # pyright: ignore[reportMissingModuleSource]  # ty:ignore[unresolved-import]

user32 = ctypes.windll.user32  # pyright: ignore[reportAttributeAccessIssue]  # ty:ignore[unresolved-attribute]


def _make_filter(class_name: Optional[str], title: Optional[str]):
    """https://docs.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumwindows"""

    def enum_windows(handle: int, h_list: list):
        if not (class_name or title):
            h_list.append(handle)
        if class_name and class_name not in (win32gui.GetClassName(handle) or ""):
            return True  # continue enumeration
        if title and title not in (win32gui.GetWindowText(handle) or ""):
            return True  # continue enumeration
        h_list.append(handle)

    return enum_windows


def find_window_handles(
    parent: Optional[int] = None, window_class: Optional[str] = None, title: Optional[str] = None
) -> list[int]:
    cb = _make_filter(window_class, title)
    try:
        handle_list = []
        if parent:
            win32gui.EnumChildWindows(parent, cb, handle_list)
        else:
            win32gui.EnumWindows(cb, handle_list)
    except pywintypes.error:
        return []
    else:
        return handle_list


def force_refresh_syspar():
    user32.UpdatePerUserSystemParameters(1)


def enable_activedesktop():
    """https://stackoverflow.com/a/16351170"""
    try:
        progman = find_window_handles(window_class="Progman")[0]
        cryptic_params = (0x52C, 0, 0, 0, 500, None)
        user32.SendMessageTimeoutW(progman, *cryptic_params)
    except IndexError as e:
        msg = "Cannot enable Active Desktop"
        raise OSError(msg) from e


def set_wallpaper_win(image_path: str, use_activedesktop: bool = True):
    if use_activedesktop:
        enable_activedesktop()
    pythoncom.CoInitialize()
    iad = pythoncom.CoCreateInstance(
        shell.CLSID_ActiveDesktop, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IActiveDesktop
    )
    iad.SetWallpaper(str(image_path), 0)  # pyright: ignore[reportAttributeAccessIssue]
    iad.ApplyChanges(shellcon.AD_APPLY_ALL)  # pyright: ignore[reportAttributeAccessIssue]
    force_refresh_syspar()
