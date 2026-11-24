"""The tray icon and its menu: the saved profiles to start, the slideshow, and the windows.

Where the desktop draws a native tray itself (Linux's StatusNotifierItem) it offers the same
menu, through the same methods of TaskBarIcon.
"""

import logging
from collections.abc import Callable
from typing import assert_never

import wx  # ty:ignore[unresolved-import]
import wx.adv  # ty:ignore[unresolved-import]

from superpaper.__version__ import __version__
from superpaper.desktop.backend import Desktop
from superpaper.desktop.tray_menu import Check, Item, MenuEntry, Notice, Separator, Submenu, tray_menu
from superpaper.paths import AppPaths, resource
from superpaper.profiles.profile_store import ProfileStore, StoredProfile
from superpaper.session import Session
from superpaper.ui.message import show_message

logger = logging.getLogger(__name__)

TRAY_TOOLTIP = "Superpaper"


def _append_entries(menu: wx.Menu, entries: tuple[MenuEntry, ...]) -> None:
    for entry in entries:
        match entry:
            case Item(label, action, enabled):
                _append_item(menu, label, action, wx.ITEM_NORMAL).Enable(enabled)
            case Check(label, action, checked, enabled):
                item = _append_item(menu, label, action, wx.ITEM_CHECK)
                item.Check(checked)
                item.Enable(enabled)
            case Notice(label):
                menu.Append(-1, label).Enable(False)
            case Separator():
                menu.AppendSeparator()
            case Submenu(label, items):
                submenu = wx.Menu()
                _append_entries(submenu, items)
                menu.AppendSubMenu(submenu, label)
            case _:
                assert_never(entry)


def _append_item(menu: wx.Menu, label: str, action: Callable[[], None], kind: int) -> wx.MenuItem:
    item = wx.MenuItem(menu, -1, label, kind=kind)
    menu.Bind(wx.EVT_MENU, lambda event: action(), id=item.GetId())
    menu.Append(item)
    return item


class TaskBarIcon(wx.adv.TaskBarIcon):
    """The tray icon: the native StatusNotifierItem where it can be registered, the wx
    one otherwise. Its menu lists the saved profiles in ``store`` and whether
    ``session``'s slideshow is paused, and first why the last wallpaper change failed, if
    ``last_failure()`` gives a reason.

    The application provides what the menu does beyond the session: ``open_editor()``,
    ``open_settings()``, ``reload_profiles()``, ``start_profile(stored)``, ``next_wallpaper()`` and ``quit()``;
    ``paths.config`` is the folder "Open Config Folder" opens.
    """

    def __init__(
        self,
        store: ProfileStore,
        session: Session,
        desktop: Desktop,
        *,
        last_failure: Callable[[], str | None],
        paths: AppPaths,
        open_editor: Callable[[], None],
        open_settings: Callable[[], None],
        reload_profiles: Callable[[], None],
        start_profile: Callable[[StoredProfile], None],
        next_wallpaper: Callable[[], None],
        quit: Callable[[], None],
    ):
        super().__init__()
        self._store = store
        self._session = session
        self._desktop = desktop
        self._last_failure = last_failure
        self._config_dir = paths.config
        self._open_editor = open_editor
        self._open_settings = open_settings
        self._reload_profiles = reload_profiles
        self._start_profile = start_profile
        self._next_wallpaper = next_wallpaper
        self._quit = quit
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, self.on_left_down)
        # Prefer the desktop's own tray (native StatusNotifierItem on Linux, which works on
        # Wayland); the wx TaskBarIcon can be non-interactive, e.g. on KDE Plasma 6.
        self._native_tray = desktop.make_tray(
            menu=self.menu,
            call_soon=wx.CallAfter,
            activate=self._open_editor,
            secondary_activate=next_wallpaper,
            icon_path=str(resource("superpaper.png")),
            title=TRAY_TOOLTIP,
        )
        if self._native_tray is None:
            self.set_icon(str(resource("superpaper.png")))

    @property
    def clickable(self) -> bool:
        """Whether the icon can be clicked: wx's own can't be on some desktops."""
        return self._native_tray is not None or self._desktop.wx_tray_clickable()

    def remove(self) -> None:
        """Take the icon away, as Superpaper quits."""
        if self._native_tray is not None:
            try:
                self._native_tray.remove()
            except Exception as exc:
                logger.info("Native tray cleanup failed: %s", exc)
        wx.CallAfter(self.Destroy)

    def menu(self) -> tuple[MenuEntry, ...]:
        """The tray menu as it is now, for both the wx and the native SNI tray to show."""
        return tray_menu(
            self._store.profiles,
            self._session.running,
            paused=self._session.paused,
            last_failure=self._last_failure(),
            open_config_folder=self.open_config,
            open_editor=self._open_editor,
            open_settings=self._open_settings,
            reload_profiles=self._reload_profiles,
            start_profile=self._start_profile,
            next_wallpaper=self._next_wallpaper,
            toggle_pause=self._session.toggle_pause,
            about=self.on_about,
            quit=self._quit,
        )

    def CreatePopupMenu(self):
        """Method called by WX library when user right clicks tray icon. Opens tray menu."""
        menu = wx.Menu()
        _append_entries(menu, self.menu())
        return menu

    def set_icon(self, path):
        """Sets tray icon."""
        icon = wx.Icon(path)
        self.SetIcon(wx.BitmapBundle(icon), TRAY_TOOLTIP)

    def on_left_down(self, event):
        """Allows binding left click event."""
        logger.info("Tray icon was left-clicked.")
        # Open configuration on left click as fallback
        self._open_editor()

    def open_config(self):
        """Opens Superpaper's config folder."""
        result = self._desktop.open_folder(self._config_dir)
        if not result.ok:
            logger.error("open_config failed for %s: %s", self._config_dir, result.problem)
            show_message("There was an error trying to open the config folder.")

    def on_about(self):
        """Opens About dialog."""
        # Credit for AboutDiaglog example to Jan Bodnar of
        # http://zetcode.com/wxpython/dialogs/
        description = (
            "Superpaper is an advanced multi monitor wallpaper\n"
            "manager for Unix and Windows operating systems.\n"
            "Features include setting a single or multiple image\n"
            "wallpaper, pixel per inch and bezel corrections,\n"
            "manual pixel offsets for tuning, slideshow with\n"
            "configurable file order, multiple path support and more."
        )
        licence = (
            "Superpaper is free software; you can redistribute\n"
            "it and/or modify it under the terms of the MIT"
            " License.\n\n"
            "Superpaper is distributed in the hope that it will"
            " be useful,\n"
            "but WITHOUT ANY WARRANTY; without even the implied"
            " warranty of\n"
            "MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.\n"
            "See the MIT License for more details."
        )
        artists = "Icons kindly provided by Icons8 https://icons8.com"

        info = wx.adv.AboutDialogInfo()
        info.SetIcon(wx.Icon(str(resource("superpaper.png")), wx.BITMAP_TYPE_PNG))
        info.SetName("Superpaper")
        info.SetVersion(__version__)
        info.SetDescription(description)
        info.SetCopyright("(C) 2022 Henri Hänninen")
        info.SetWebSite("https://github.com/hhannine/Superpaper/")
        info.SetLicence(licence)
        info.AddDeveloper("Henri Hänninen")
        info.AddArtist(artists)
        wx.adv.AboutBox(info)
