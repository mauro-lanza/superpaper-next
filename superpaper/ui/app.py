"""Superpaper's wx shell: the wx.App, the main loop, and the windows, dialogs and tray icon
that the application in superpaper.controller opens through its Shell."""

import configparser
import logging
import os
import sys

import wx  # ty:ignore[unresolved-import]

from superpaper.controller import Shell, Superpaper
from superpaper.paths import AppPaths
from superpaper.profiles.profile_id import ProfileId, ProfileIdError
from superpaper.settings import Settings
from superpaper.ui.editor import ConfigFrame
from superpaper.ui.help import HelpFrame
from superpaper.ui.message import show_message_dialog
from superpaper.ui.settings_dialog import SettingsFrame
from superpaper.ui.tray import TaskBarIcon

logger = logging.getLogger(__name__)


def run(paths: AppPaths, settings: Settings, profile: ProfileId | str | os.PathLike[str] | None = None):
    """Run the tray application until it is quit; ``profile`` is run at once, if given."""
    # On Linux (wxGTK) the tray icon (StatusNotifierItem) title is derived
    # from the program name, i.e. the basename of sys.argv[0]. When launched
    # via "python -m superpaper" this becomes "__main__.py", so normalize it
    # to a clean application name before the wx.App is created.
    sys.argv[0] = "Superpaper"
    startup_profile = None
    if profile:
        try:
            startup_profile = profile if isinstance(profile, ProfileId) else ProfileId.from_path(profile)
        except ProfileIdError:
            startup_profile = None
        logger.info("Startup profile: %s", startup_profile.value if startup_profile else profile)
    if sys.platform == "linux":
        # Route incoming D-Bus calls (native SNI tray) through wxGTK's own
        # GLib main loop. Must be set as the default main loop before the
        # first bus connection is created (i.e. before the wx.App).
        try:
            from dbus.mainloop.glib import DBusGMainLoop  # ty:ignore[unresolved-import]

            DBusGMainLoop(set_as_default=True)
        except ImportError:
            pass
    app = App(paths, settings, startup_profile)
    app.MainLoop()


class App(wx.App):
    """The wx application, which builds Superpaper once wx is ready."""

    def __init__(self, paths: AppPaths, settings: Settings, startup_profile: ProfileId | None):
        # wx.App.__init__ runs OnInit, which builds the application from these.
        self._paths = paths
        self._settings = settings
        self._startup_profile = startup_profile
        super().__init__(False)

    def OnInit(self):
        self.SetAppName("Superpaper")
        self.SetAppDisplayName("Superpaper")
        frame = wx.Frame(None)
        self.SetTopWindow(frame)
        try:
            self.superpaper = start_superpaper(frame, self._paths, self._settings, self._startup_profile)
        except (ValueError, configparser.Error) as error:
            message = f"The saved display layout could not be read: {error}"
            logger.exception(message)
            show_message_dialog(message, "Error")
            return False
        return True

    def InitLocale(self):
        """Override with nothing (or impliment local if actually needed)"""


def start_superpaper(
    frame: wx.Frame, paths: AppPaths, settings: Settings, startup_profile: ProfileId | None
) -> Superpaper:
    """Superpaper running in the wx application whose top window is ``frame``, closed on quitting."""

    def close() -> None:
        frame.Close()

    shell = Shell(
        notify=_notify,
        confirm=lambda message: show_message_dialog(message, "Error", style="YES_NO"),
        call_soon=wx.CallAfter,
        open_editor=_open_editor,
        open_settings=_open_settings,
        open_help=_open_help,
        make_tray=_make_tray,
        close=close,
    )
    return Superpaper(shell, paths, settings, startup_profile)


def _notify(message: str, title: str) -> None:
    show_message_dialog(message, title)


def _open_editor(app: Superpaper) -> None:
    ConfigFrame(
        app.paths,
        lambda: app.settings,
        app.store,
        app.session,
        update_settings=app.update_settings,
        refresh_displays=app.refresh_displays,
        rebind_hotkey=app.rebind_hotkey,
    )


def _open_settings(app: Superpaper) -> None:
    SettingsFrame(app.settings, save_settings=app.apply_settings)


def _open_help(app: Superpaper) -> None:
    HelpFrame(lambda: app.settings, app.update_settings)


def _make_tray(app: Superpaper) -> TaskBarIcon:
    return TaskBarIcon(
        app.store,
        app.session,
        config_dir=app.paths.config,
        open_editor=app.open_editor,
        open_settings=app.open_settings,
        reload_profiles=app.reload_profiles,
        start_profile=app.start_profile,
        quit=app.quit,
    )
