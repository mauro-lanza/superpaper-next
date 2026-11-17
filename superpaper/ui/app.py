"""Superpaper's tray application: builds the saved profiles, the session that runs them,
the hotkeys and the tray icon, connects them, and runs the wx main loop."""

import configparser
import logging
import os
import sys

import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

import superpaper.desktop as desktop
import superpaper.displays as displays
import superpaper.profile_store as profile_store
from superpaper.paths import AppPaths
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.profile_store import ProfileDiagnosticKind, ProfileStore
from superpaper.session import Session
from superpaper.settings import SETTINGS_FILE, Settings
from superpaper.ui.editor import ConfigFrame
from superpaper.ui.help import HelpFrame
from superpaper.ui.hotkeys import Hotkeys
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
            startup_profile = _startup_profile_id(profile)
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


def _startup_profile_id(profile: ProfileId | str | os.PathLike[str]) -> ProfileId:
    """Extract a managed identity from a legacy path or a direct profile ID."""
    if isinstance(profile, ProfileId):
        return profile
    value = os.fspath(profile)
    leaf = value.replace("\\", "/").rsplit("/", 1)[-1]
    if leaf.endswith(".profile"):
        leaf = leaf.removesuffix(".profile")
    return ProfileId.parse(leaf)


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
        self.superpaper = Superpaper(frame, self._paths, self._settings, self._startup_profile)
        return True

    def InitLocale(self):
        """Override with nothing (or impliment local if actually needed)"""


class Superpaper:
    """The tray application as it runs: the saved profiles, the session that runs them,
    the general settings, the hotkeys and the tray icon, and what connects them.

    ``frame`` is the application's top window, closed on quitting.
    """

    def __init__(self, frame, paths: AppPaths, settings: Settings, startup_profile: ProfileId | None):
        self._frame = frame
        self.paths = paths
        self.settings_path = paths.config / SETTINGS_FILE
        self.settings = settings
        # The running profile, its slideshow and every wallpaper change, starting with the
        # displays as they are now. Wallpaper changes use the custom command as last saved.
        self.session = Session(
            paths, displays.DisplaySystem(paths.config), set_command=lambda: self.settings.set_command
        )
        self.store = ProfileStore(paths)
        self._load_profiles()
        # Renders and selections of profiles deleted or renamed since the last start
        # aren't needed.
        self.store.sweep()
        self._run_at_startup(startup_profile)
        self.hotkeys = self._start_hotkeys()
        self.tray = TaskBarIcon(
            self.store,
            self.session,
            config_dir=paths.config,
            open_editor=self.open_editor,
            open_settings=self.open_settings,
            reload_profiles=self.reload_profiles,
            start_profile=self.start_profile,
            quit=self.quit,
        )
        self._show_at_start()

    def _run_at_startup(self, startup_profile):
        """Run the profile asked for on the command line, or carry on with the one that ran
        when Superpaper last exited."""
        if startup_profile:
            # An explicit `--profile` launch runs the profile now, as the tray menu does.
            started = self.store.get(startup_profile)
            if started is None:
                logger.error("Startup profile '%s' could not be matched to a saved profile.", startup_profile.value)
            else:
                self.session.activate(started)
            return
        # A normal start shows the last wallpaper again, and the slideshow carries on from
        # there on its own schedule (issue #140).
        previous = self.store.active()
        if previous is None:
            logger.info("No previous profile was found.")
        else:
            self.session.restore(previous)

    def _start_hotkeys(self):
        """The system-wide hotkeys, bound; None while they are off or unavailable. Hotkeys
        turned on or off in the settings apply after a restart."""
        if not self.settings.use_hotkeys:
            return None
        try:
            hotkeys = Hotkeys(
                next_wallpaper=self.session.next,
                pause=self.session.toggle_pause,
                start_profile=self.start_profile_by_id,
            )
        except ImportError as error:
            logger.info(
                "WARNING: Could not import keyboard hotkey hook library, hotkeys will not work. Exception: %s", error
            )
            return None
        hotkeys.register_general(self.settings)
        hotkeys.register_profiles(self.store.profiles)
        return hotkeys

    def _show_at_start(self):
        """Open the help and the configuration if they are to be shown at start, and say
        once if wallpapers can't be set here or the displays' sizes aren't known."""
        if self.settings.show_help:
            self.open_editor()
            HelpFrame(self.settings_path)
        elif not self.tray.clickable:
            # KDE Plasma 6 workaround: clicks on the wx tray icon don't work there, so the
            # configuration opens at startup.
            logger.info("KDE Plasma without the native tray: auto-opening the configuration")
            wx.CallAfter(self.open_editor)
        # Say once, now, if wallpapers can't be set here, rather than on every change.
        problem = desktop.setter_problem(self.settings.set_command)
        if problem:
            logger.error("%s", problem)
            wx.CallAfter(show_message_dialog, problem, "Error")
        size_hint = self.session.display_system.size_hint()
        if size_hint:
            logger.warning("%s", size_hint)
            wx.CallAfter(show_message_dialog, size_hint)

    def open_editor(self):
        """Open the wallpaper configuration."""
        try:
            ConfigFrame(
                self.paths,
                self.store,
                self.session,
                refresh_displays=self.refresh_displays,
                rebind_hotkey=self.rebind_hotkey,
            )
        except Exception as error:
            logger.error("configure_wallpapers error: %s", error, exc_info=True)

    def open_settings(self):
        """Open the general settings."""
        SettingsFrame(self.settings_path, on_saved=self.apply_settings)

    def start_profile(self, stored):
        """Run the saved profile ``stored`` on the displays as they are now, or show its
        next image if it runs already."""
        self.refresh_displays()
        self.session.activate(stored)

    def start_profile_by_id(self, profile_id):
        """Start the profile currently loaded under ``profile_id``, if it still exists."""
        stored = self.store.get(profile_id)
        if stored is None:
            logger.info("The profile bound to this hotkey, '%s', no longer exists.", profile_id.value)
            return
        self.start_profile(stored)

    def reload_profiles(self):
        """Load the profiles directory again, asking about profiles that can't be loaded."""
        self._load_profiles()
        # The running profile carries on with its current record, whose file may have
        # changed, or stops if it is gone.
        running = self.session.running
        if running is not None:
            self.session.update(running.profile_id, self.store.get(running.profile_id))

    def _load_profiles(self):
        """Read the profiles directory again, offering to delete profiles that can't be loaded."""
        for diagnostic in self.store.reload():
            if diagnostic.kind is not ProfileDiagnosticKind.MALFORMED_CONTENT:
                logger.warning("Ignoring %s: %s", diagnostic.path, diagnostic.detail)
                continue
            message = (
                f"There was an error when loading profile '{diagnostic.path.name}'.\n"
                "Would you like to delete it? Choosing 'No' will just ignore the profile."
            )
            logger.info("%s %s", message, diagnostic.detail)
            if show_message_dialog(message, "Error", style="YES_NO"):
                profile_store.delete_malformed(diagnostic)

    def refresh_displays(self):
        """Detect the displays again and load their saved layout; later wallpaper changes
        use it. If detection fails, the previous layout stays in use.

        Displays are detected here, on the main thread, never by the session's worker:
        see displays.get_display_data.
        """
        try:
            display_system = displays.DisplaySystem(self.paths.config)
        except (displays.DisplayDetectionError, OSError, ValueError, KeyError, configparser.Error) as error:
            logger.warning("Keeping the previous display layout: %s", error)
            return
        self.session.use_displays(display_system)

    def rebind_hotkey(self, before, after):
        """Rebind a profile's hotkey once it was saved, renamed or deleted: see
        Hotkeys.profile_changed."""
        if self.hotkeys is not None:
            self.hotkeys.profile_changed(before, after)

    def apply_settings(self, settings):
        """The general settings were saved as ``settings``: wallpaper changes and hotkeys
        use them from now on."""
        self.settings = settings
        # Hotkeys turned on or off apply after a restart.
        if self.hotkeys is not None and settings.use_hotkeys:
            self.hotkeys.register_general(settings)
        if settings.logging:
            show_message_dialog("Logging is enabled after an application restart.", "Info")

    def quit(self):
        """Stop the session, take the tray icon away and close the application."""
        self.session.shutdown()
        self.tray.remove()
        self._frame.Close()
