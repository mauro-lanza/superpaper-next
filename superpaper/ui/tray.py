"""The tray icon and its menu: the saved profiles to start, the slideshow, and the windows.

On Linux the native StatusNotifierItem tray (sni_tray) offers the same menu, through the
same methods of TaskBarIcon.
"""

import os
import sys

import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]
import wx.adv  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

import superpaper.desktop as desktop
import superpaper.sp_logging as sp_logging
from superpaper.__version__ import __version__
from superpaper.desktop.linux import running_kde
from superpaper.paths import resource
from superpaper.ui.message import show_message_dialog
from superpaper.ui.sni_tray import build_tray, sni_supported

TRAY_TOOLTIP = "Superpaper"


def create_menu_item(menu, label, func, *args, **kwargs):
    """Helper function to create menu items for the tray menu."""
    item = wx.MenuItem(menu, -1, label, **kwargs)
    menu.Bind(wx.EVT_MENU, lambda event: func(event, *args), id=item.GetId())
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
        self.pause_item = None
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.configure_wallpapers)
        self.Bind(wx.adv.EVT_TASKBAR_RIGHT_DOWN, self.on_right_down)
        # On Linux, prefer a native StatusNotifierItem tray (works on Wayland);
        # the wx TaskBarIcon renders but is non-interactive on KDE Plasma 6.
        self._sni_tray = None
        if sys.platform == "linux" and sni_supported():
            self._sni_tray = build_tray(
                self,
                f"org.kde.StatusNotifierItem-{os.getpid()}-1",
                str(resource("superpaper.png")),
                TRAY_TOOLTIP,
                TRAY_TOOLTIP,
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
                sp_logging.G_LOGGER.info("SNI tray cleanup failed: %s", exc)
        wx.CallAfter(self.Destroy)

    #
    # The menu, which the native SNI menu shares (sni_tray._MenuModel).
    #
    @property
    def list_of_profiles(self):
        """The saved profiles, in the order the menus show them."""
        return self._store.profiles

    @property
    def is_paused(self):
        return self._session.paused

    def CreatePopupMenu(self):
        """Method called by WX library when user right clicks tray icon. Opens tray menu."""
        menu = wx.Menu()
        create_menu_item(menu, "Open Config Folder", self.open_config)
        create_menu_item(menu, "Wallpaper Configuration", self.configure_wallpapers)
        create_menu_item(menu, "Settings", self.configure_settings)
        create_menu_item(menu, "Reload Profiles", self.reload_profiles)
        menu.AppendSeparator()
        for item in self.list_of_profiles:
            create_menu_item(menu, item.profile.name, self.start_profile, item)
        menu.AppendSeparator()
        create_menu_item(menu, "Next Wallpaper", self.next_wallpaper)
        self.pause_item = create_menu_item(menu, "Pause Timer", self.pause_timer, kind=wx.ITEM_CHECK)
        self.pause_item.Check(self.is_paused)
        menu.AppendSeparator()
        create_menu_item(menu, "About", self.on_about)
        create_menu_item(menu, "Exit", self.on_exit)
        return menu

    def set_icon(self, path):
        """Sets tray icon."""
        icon = wx.Icon(path)
        self.SetIcon(wx.BitmapBundle(icon), TRAY_TOOLTIP)

    def on_left_down(self, *event):
        """Allows binding left click event."""
        sp_logging.G_LOGGER.info("Tray icon was left-clicked.")
        # Open configuration on left click as fallback
        self.configure_wallpapers(event)

    def on_right_down(self, event):
        """Handle right click event."""
        sp_logging.G_LOGGER.info("Tray icon was right-clicked.")

    def open_config(self, event):
        """Opens Superpaper's config folder."""
        result = desktop.open_folder(self._config_dir)
        if not result.ok:
            sp_logging.G_LOGGER.error("open_config failed for %s: %s", self._config_dir, result.problem)
            show_message_dialog("There was an error trying to open the config folder.")

    def configure_wallpapers(self, event):
        """Opens wallpaper configuration panel."""
        self._open_editor()

    def configure_settings(self, event):
        """Opens general settings panel."""
        self._open_settings()

    def reload_profiles(self, event):
        """Reloads profiles from disk."""
        self._reload_profiles()

    def start_profile(self, event, profile):
        """Run ``profile``, or show its next image if it runs already."""
        self._start_profile(profile)

    def next_wallpaper(self, event):
        """Show the running profile's next image."""
        self._session.next()

    def pause_timer(self, event):
        """Pause the running slideshow, or resume it."""
        self._session.toggle_pause()

    def on_about(self, event):
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

    def on_exit(self, event):
        """Exits Superpaper."""
        self._quit()
