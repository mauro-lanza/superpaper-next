"""Superpaper's wx shell: the wx.App, the main loop, and the windows, dialogs and tray icon
that the application in superpaper.controller opens through its Shell."""

import configparser
import logging
import sys
from collections.abc import Callable

import wx  # ty:ignore[unresolved-import]

from superpaper.controller import Shell, Superpaper
from superpaper.desktop.backend import Desktop
from superpaper.geometry.display_detection import DisplayDetectionError
from superpaper.paths import AppPaths
from superpaper.profiles.profile_id import ProfileId
from superpaper.settings import Settings
from superpaper.ui.editor import ConfigFrame
from superpaper.ui.help import HelpFrame
from superpaper.ui.message import show_message_dialog
from superpaper.ui.settings_dialog import SettingsFrame
from superpaper.ui.tray import TaskBarIcon

logger = logging.getLogger(__name__)


def run(paths: AppPaths, settings: Settings, desktop: Desktop, profile: ProfileId | None = None):
    """Run the tray application until it is quit; ``profile`` is run at once, if given."""
    # On Linux (wxGTK) the tray icon (StatusNotifierItem) title is derived
    # from the program name, i.e. the basename of sys.argv[0]. When launched
    # via "python -m superpaper" this becomes "__main__.py", so normalize it
    # to a clean application name before the wx.App is created.
    sys.argv[0] = "Superpaper"
    if profile:
        logger.info("Startup profile: %s", profile.value)
    desktop.init_main_loop()
    app = App(paths, settings, desktop, profile)
    app.MainLoop()


class App(wx.App):
    """The wx application, which builds Superpaper once wx is ready."""

    def __init__(self, paths: AppPaths, settings: Settings, desktop: Desktop, startup_profile: ProfileId | None):
        # wx.App.__init__ runs OnInit, which builds the application from these.
        self._paths = paths
        self._settings = settings
        self._desktop = desktop
        self._startup_profile = startup_profile
        super().__init__(False)

    def OnInit(self):
        self.SetAppName("Superpaper")
        self.SetAppDisplayName("Superpaper")
        frame = wx.Frame(None)
        self.SetTopWindow(frame)
        try:
            self.superpaper = start_superpaper(frame, self._paths, self._settings, self._desktop, self._startup_profile)
        except DisplayDetectionError as error:
            return _fail_startup(f"No displays could be detected: {error}")
        except (ValueError, configparser.Error) as error:
            return _fail_startup(f"The saved display layout could not be read: {error}")
        except OSError as error:
            return _fail_startup(f"Superpaper's files could not be read or written: {error}")
        return True

    def InitLocale(self):
        # Skip wx's locale setup, which Superpaper has no use for.
        pass


def _fail_startup(message: str) -> bool:
    logger.exception(message)
    show_message_dialog(message, "Error")
    return False


def start_superpaper(
    frame: wx.Frame, paths: AppPaths, settings: Settings, desktop: Desktop, startup_profile: ProfileId | None
) -> Superpaper:
    """Superpaper running in the wx application whose top window is ``frame``, closed on quitting."""

    def close() -> None:
        frame.Close()

    open_frames: dict[str, wx.Frame] = {}

    shell = Shell(
        notify=_notify,
        confirm=lambda message: show_message_dialog(message, "Error", style="YES_NO"),
        call_soon=wx.CallAfter,
        open_editor=lambda app: _open_editor(app, open_frames),
        open_settings=lambda app: _open_settings(app, open_frames),
        open_help=_open_help,
        make_tray=_make_tray,
        close=close,
    )
    return Superpaper(shell, paths, desktop, settings, startup_profile)


def _notify(message: str, title: str) -> None:
    show_message_dialog(message, title)


def _open_editor(app: Superpaper, open_frames: dict[str, wx.Frame]) -> None:
    _show_once(
        open_frames,
        "editor",
        lambda: ConfigFrame(
            app.paths,
            lambda: app.settings,
            app.store,
            app.session,
            update_settings=app.update_settings,
            refresh_displays=app.refresh_displays,
            rebind_hotkey=app.rebind_hotkey,
        ),
    )


def _open_settings(app: Superpaper, open_frames: dict[str, wx.Frame]) -> None:
    _show_once(open_frames, "settings", lambda: SettingsFrame(lambda: app.settings, save_settings=app.apply_settings))


def _show_once(open_frames: dict[str, wx.Frame], name: str, make_frame: Callable[[], wx.Frame]) -> None:
    """Raise the window ``name`` if it is still open, else open it."""
    frame = open_frames.get(name)
    # A destroyed wx object is falsy.
    if frame:
        frame.Raise()
    else:
        open_frames[name] = make_frame()


def _open_help(app: Superpaper) -> None:
    HelpFrame(lambda: app.settings, app.update_settings)


def _make_tray(app: Superpaper) -> TaskBarIcon:
    return TaskBarIcon(
        app.store,
        app.session,
        last_failure=lambda: app.last_failure,
        config_dir=app.paths.config,
        desktop=app.desktop,
        open_editor=app.open_editor,
        open_settings=app.open_settings,
        reload_profiles=app.reload_profiles,
        start_profile=app.start_profile,
        quit=app.quit,
    )
