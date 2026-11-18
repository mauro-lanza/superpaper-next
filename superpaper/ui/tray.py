"""The tray icon and its menu: the saved profiles to start, the slideshow, and the windows.

On Linux the native StatusNotifierItem tray (sni_tray) offers the same menu, through the
same methods of TaskBarIcon.
"""

import logging
import os
import sys
from collections.abc import Callable
from functools import partial
from typing import assert_never

import wx  # ty:ignore[unresolved-import]
import wx.adv  # ty:ignore[unresolved-import]

import superpaper.desktop as desktop
from superpaper.__version__ import __version__
from superpaper.desktop.linux import running_kde
from superpaper.paths import resource
from superpaper.ui.message import show_message_dialog
from superpaper.ui.sni_tray import build_tray, sni_supported
from superpaper.ui.tray_menu import Check, Item, MenuEntry, Separator, Submenu

logger = logging.getLogger(__name__)

TRAY_TOOLTIP = "Superpaper"


def _append_entries(menu: wx.Menu, entries: tuple[MenuEntry, ...]) -> None:
    for entry in entries:
        match entry:
            case Item(label, action):
                _append_item(menu, label, action, wx.ITEM_NORMAL)
            case Check(label, action, checked):
                _append_item(menu, label, action, wx.ITEM_CHECK).Check(checked)
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
    ``session``'s slideshow is paused.

    The application provides what the menu does beyond the session: ``open_editor()``,
    ``open_settings()``, ``reload_profiles()``, ``start_profile(stored)`` and ``quit()``;
    ``config_dir`` is the folder "Open Config Folder" opens.
    """

    def __init__(self, store, session, *, config_dir, open_editor, open_settings, reload_profiles, start_profile, quit):
        super().__init__()
        self._store = store
        self._session = session
        self._config_dir = config_dir
        self._open_editor = open_editor
        self._open_settings = open_settings
        self._reload_profiles = reload_profiles
        self._start_profile = start_profile
        self._quit = quit
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, lambda event: self._open_editor())
        self.Bind(wx.adv.EVT_TASKBAR_RIGHT_DOWN, self.on_right_down)
        # On Linux, prefer a native StatusNotifierItem tray (works on Wayland);
        # the wx TaskBarIcon renders but is non-interactive on KDE Plasma 6.
        self._sni_tray = None
        if sys.platform == "linux" and sni_supported():
            self._sni_tray = build_tray(
                menu=self.menu,
                activate=self._open_editor,
                secondary_activate=session.next,
                bus_name=f"org.kde.StatusNotifierItem-{os.getpid()}-1",
                icon_path=str(resource("superpaper.png")),
                title=TRAY_TOOLTIP,
                tooltip=TRAY_TOOLTIP,
            )
        if self._sni_tray is None:
            self.set_icon(str(resource("superpaper.png")))

    @property
    def clickable(self):
        """Whether the icon can be clicked: the wx one can't be on KDE Plasma 6."""
        return self._sni_tray is not None or not running_kde()

    def remove(self):
        """Take the icon away, as Superpaper quits."""
        if self._sni_tray is not None:
            try:
                self._sni_tray.remove()
            except Exception as exc:
                logger.info("SNI tray cleanup failed: %s", exc)
        wx.CallAfter(self.Destroy)

    def menu(self) -> tuple[MenuEntry, ...]:
        """The tray menu as it is now, for both the wx and the native SNI tray to show."""
        profiles = tuple(
            Item(stored.profile.name, partial(self._start_profile, stored)) for stored in self._store.profiles
        )
        return (
            Item("Open Config Folder", self.open_config),
            Item("Wallpaper Configuration", self._open_editor),
            Item("Settings", self._open_settings),
            Item("Reload Profiles", self._reload_profiles),
            Separator(),
            Submenu("Profiles", profiles),
            Separator(),
            Item("Next Wallpaper", self._session.next),
            Check("Pause Timer", self._session.toggle_pause, checked=self._session.paused),
            Separator(),
            Item("About", self.on_about),
            Item("Exit", self._quit),
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

    def on_right_down(self, event):
        """Handle right click event."""
        logger.info("Tray icon was right-clicked.")

    def open_config(self):
        """Opens Superpaper's config folder."""
        result = desktop.open_folder(self._config_dir)
        if not result.ok:
            logger.error("open_config failed for %s: %s", self._config_dir, result.problem)
            show_message_dialog("There was an error trying to open the config folder.")

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
