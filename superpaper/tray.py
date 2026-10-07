"""Tray applet for Superpaper."""
# from configuration_dialogs import * # Katso ensin että tuleeko tästä liian pitkä dialogien kanssa.

import os
import sys
from threading import Lock

import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]
import wx.adv  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

import superpaper.desktop as desktop
import superpaper.displays as displays
import superpaper.render_cache as render_cache
import superpaper.sp_logging as sp_logging
import superpaper.wallpaper_processing as wpproc
from superpaper.__version__ import __version__
from superpaper.configuration_dialogs import HelpFrame, SettingsFrame
from superpaper.data import (
    list_profiles,
    read_active_profile,
    stored_profile_ids,
    write_active_profile,
)
from superpaper.desktop.linux import running_kde
from superpaper.gui import ConfigFrame
from superpaper.message_dialog import show_message_dialog
from superpaper.paths import AppPaths, resource
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.settings import SETTINGS_FILE, Settings, read_settings
from superpaper.sni_tray import build_tray, sni_supported
from superpaper.wallpaper_processing import (
    change_wallpaper_job,
    quick_profile_job,
    run_profile_job,
)

# Constants
TRAY_TOOLTIP = "Superpaper"


def _startup_profile_id(profile: ProfileId | str | os.PathLike[str]) -> ProfileId:
    """Extract a managed identity from a legacy path or a direct profile ID."""
    if isinstance(profile, ProfileId):
        return profile
    value = os.fspath(profile)
    leaf = value.replace("\\", "/").rsplit("/", 1)[-1]
    if leaf.endswith(".profile"):
        leaf = leaf.removesuffix(".profile")
    return ProfileId.parse(leaf)


def tray_loop(paths: AppPaths, settings: Settings, profile: ProfileId | str | os.PathLike[str] | None = None):
    """Runs the tray applet."""
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
        sp_logging.G_LOGGER.info("Startup profile: %s", startup_profile.value if startup_profile else profile)
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


# Tray applet definitions
def create_menu_item(menu, label, func, *args, **kwargs):
    """Helper function to create menu items for the tray menu."""
    item = wx.MenuItem(menu, -1, label, **kwargs)
    menu.Bind(wx.EVT_MENU, lambda event: func(event, *args), id=item.GetId())
    menu.Append(item)
    return item


class TaskBarIcon(wx.adv.TaskBarIcon):
    """Taskbar icon and menu class."""

    def __init__(self, frame, paths: AppPaths, settings: Settings, startup_profile: ProfileId | None = None):
        self.paths = paths
        self.settings_path = paths.config / SETTINGS_FILE
        self.g_settings = settings

        self.frame = frame
        super().__init__()
        # On Linux, prefer a native StatusNotifierItem tray (works on Wayland);
        # the wx TaskBarIcon renders but is non-interactive on KDE Plasma 6.
        self._sni_tray = None
        self._use_sni = sys.platform == "linux" and sni_supported()
        if not self._use_sni:
            self.set_icon(str(resource("superpaper.png")))
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.configure_wallpapers)
        self.Bind(wx.adv.EVT_TASKBAR_RIGHT_DOWN, self.on_right_down)
        # Initialize display data
        self.refresh_displays()
        # profile initialization
        self.job_lock = Lock()
        self.repeating_timer = None
        self.pause_item = None
        self.is_paused = False
        self.list_of_profiles = list_profiles(self.paths)
        # Renders of profiles deleted or renamed since the last start aren't needed.
        stored = stored_profile_ids(self.paths)
        if stored is not None:
            render_cache.sweep(self.paths.cache, stored)
        # Should now return an object if a previous profile was written or
        # None if no previous data was found
        if startup_profile:
            self.active_profile = self.get_profile_by_id(startup_profile)
            if self.active_profile is None:
                sp_logging.G_LOGGER.error(
                    "Startup profile '%s' could not be matched to a saved profile.",
                    startup_profile.value,
                )
        else:
            prev_active_prof = read_active_profile(self.paths)
            if prev_active_prof:
                self.active_profile = self.get_profile_by_id(prev_active_prof.profile_id)
            else:
                self.active_profile = None
        if self.active_profile:
            wpproc.G_ACTIVE_PROFILE = self.active_profile.name
        # An explicit CLI `--profile` launch should apply the wallpaper right
        # away; a normal daemon restart only restores the last shown wallpaper
        # without re-cycling (issue #140).
        self.start_prev_profile(self.active_profile, apply_now=bool(startup_profile))
        # if self.active_profile is None:
        #     sp_logging.G_LOGGER.info("Starting up the first profile found.")
        #     self.start_profile(wx.EVT_MENU, self.list_of_profiles[0])

        # Hotkey callbacks arrive on system_hotkey's listener thread; every one of
        # them is handed to the wx main loop (wx.CallAfter) before touching state.
        self.hk = None
        self.hk2 = None
        self.seen_binding = set()
        if self.g_settings.use_hotkeys is True:
            try:
                # import keyboard # https://github.com/boppreh/keyboard
                # This import is here to have the module in the class scope
                from system_hotkey import SystemHotkey

                self.hk = SystemHotkey(check_queue_interval=0.05)
                self.hk2 = SystemHotkey(
                    consumer=self.profile_consumer,  # pyright: ignore[reportArgumentType]
                    check_queue_interval=0.05,
                )
                self.register_hotkeys()
            except ImportError as excep:
                sp_logging.G_LOGGER.info(
                    "WARNING: Could not import keyboard hotkey hook library, \
hotkeys will not work. Exception: %s",
                    excep,
                )
        if self.g_settings.show_help is True:
            ConfigFrame(self)
            HelpFrame(self.settings_path)
        elif self._use_sni:
            # Register the native SNI tray now that the profile list and pause
            # state are initialized (the menu reads them on demand).
            self._sni_tray = build_tray(
                self,
                f"org.kde.StatusNotifierItem-{os.getpid()}-1",
                str(resource("superpaper.png")),
                TRAY_TOOLTIP,
                TRAY_TOOLTIP,
            )
            if self._sni_tray is None:
                # Registration failed: fall back to the wx tray icon plus the
                # KDE auto-open-config workaround (wx clicks don't work).
                self._use_sni = False
                self.set_icon(str(resource("superpaper.png")))
                if running_kde():
                    sp_logging.G_LOGGER.info("Native SNI tray unavailable: auto-opening configuration GUI")
                    wx.CallAfter(self.configure_wallpapers, None)
        elif running_kde():
            # KDE Plasma 6 workaround: tray icon clicks don't work with wxPython
            # Automatically open the config GUI on startup
            sp_logging.G_LOGGER.info("KDE Plasma detected: Auto-opening configuration GUI")
            wx.CallAfter(self.configure_wallpapers, None)
        # Say once, now, if wallpapers can't be set here, rather than on every change.
        problem = desktop.setter_problem(self.g_settings.set_command)
        if problem:
            sp_logging.G_LOGGER.error("%s", problem)
            wx.CallAfter(show_message_dialog, problem, "Error")
        size_hint = self.display_system.size_hint()
        if size_hint:
            sp_logging.G_LOGGER.warning("%s", size_hint)
            wx.CallAfter(show_message_dialog, size_hint)

    def register_hotkeys(self):
        """Registers system-wide hotkeys for profiles and application interaction."""
        hk, hk2 = self.hk, self.hk2
        if hk is None or hk2 is None:
            # Hotkeys were off or unavailable at startup; turning them on applies after a restart.
            return
        if self.g_settings.use_hotkeys is True:
            if "system_hotkey" not in sys.modules:
                try:
                    # import keyboard # https://github.com/boppreh/keyboard
                    # Imported here only to verify availability; the registration
                    # error handling below uses broad ``except Exception`` clauses
                    # because the specific exception classes are not reliably in
                    # scope (this import is conditional on sys.modules).
                    import system_hotkey  # noqa: F401
                except ImportError as import_e:
                    sp_logging.G_LOGGER.info(
                        "WARNING: Could not import keyboard hotkey hook library, \
    hotkeys will not work. Exception: %s",
                        import_e,
                    )
            if "system_hotkey" in sys.modules:
                try:
                    # Keyboard bindings: https://github.com/boppreh/keyboard
                    #
                    # Alternative KB bindings for X11 systems and Windows:
                    # system_hotkey https://github.com/timeyyy/system_hotkey
                    # seen_binding = set()
                    # self.hk = SystemHotkey(check_queue_interval=0.05)
                    # self.hk2 = SystemHotkey(
                    #     consumer=self.profile_consumer,
                    #     check_queue_interval=0.05)

                    # Unregister previous hotkeys
                    # if self.seen_binding:
                    # for binding in self.seen_binding:
                    #     try:
                    #         self.hk.unregister(binding)
                    #         if sp_logging.DEBUG:
                    #             sp_logging.G_LOGGER.info("Unreg hotkey %s",
                    #                                      binding)
                    #     except (SystemHotkeyError, UnregisterError, InvalidKeyError):
                    #         pass
                    #     try:
                    #         self.hk2.unregister(binding)
                    #         if sp_logging.DEBUG:
                    #             sp_logging.G_LOGGER.info("Unreg hotkey %s",
                    #                                         binding)
                    #     except (SystemHotkeyError, UnregisterError, InvalidKeyError):
                    #         if sp_logging.DEBUG:
                    #             sp_logging.G_LOGGER.info("Could not unreg hotkey '%s'",
                    #                                         binding)
                    # from system_hotkey import SystemHotkey
                    # self.hk = SystemHotkey(check_queue_interval=0.05)
                    # self.hk2 = SystemHotkey(consumer=self.profile_consumer, check_queue_interval=0.05)
                    # self.seen_binding = set()

                    # register general bindings
                    if self.g_settings.hk_binding_next not in self.seen_binding:
                        try:
                            hk.register(
                                self.g_settings.hk_binding_next,
                                callback=lambda _event: wx.CallAfter(self.next_wallpaper, None),
                                overwrite=False,
                            )
                            self.seen_binding.add(self.g_settings.hk_binding_next)
                        # except (SystemHotkeyError, SystemRegisterError, InvalidKeyError):
                        except Exception:
                            msg = f"Error: could not register hotkey {self.g_settings.hk_binding_next}. \
Check that it is formatted properly and valid keys."
                            sp_logging.G_LOGGER.warning(msg)
                            sp_logging.G_LOGGER.warning(sys.exc_info()[0])
                            if not running_kde():
                                show_message_dialog(msg, "Error")
                    if self.g_settings.hk_binding_pause not in self.seen_binding:
                        try:
                            hk.register(
                                self.g_settings.hk_binding_pause,
                                callback=lambda _event: wx.CallAfter(self.pause_timer, None),
                                overwrite=False,
                            )
                            self.seen_binding.add(self.g_settings.hk_binding_pause)
                        # except (SystemHotkeyError, SystemRegisterError, InvalidKeyError):
                        except Exception:
                            msg = f"Error: could not register hotkey {self.g_settings.hk_binding_pause}. \
Check that it is formatted properly and valid keys."
                            sp_logging.G_LOGGER.warning(msg)
                            sp_logging.G_LOGGER.warning(sys.exc_info()[0])
                            if not running_kde():
                                show_message_dialog(msg, "Error")
                    # try:
                    # self.hk.register(('control', 'super', 'shift', 'q'),
                    #  callback=lambda x: self.on_exit(wx.EVT_MENU))
                    # except (SystemHotkeyError, SystemRegisterError, InvalidKeyError):
                    # pass

                    # register profile specific bindings
                    self.list_of_profiles = list_profiles(self.paths)
                    for profile in self.list_of_profiles:
                        if sp_logging.DEBUG:
                            sp_logging.G_LOGGER.info(
                                "Registering binding: \
                                %s for profile: %s",
                                profile.hk_binding,
                                profile.name,
                            )
                        if profile.hk_binding is not None and profile.hk_binding not in self.seen_binding:
                            try:
                                # Bind the identity, not the object: a profile edited later
                                # must start with its current settings.
                                hk2.register(profile.hk_binding, profile.profile_id, overwrite=False)
                                self.seen_binding.add(profile.hk_binding)
                            # except (SystemHotkeyError, SystemRegisterError, InvalidKeyError):
                            except Exception:
                                msg = f"Error: could not register hotkey {profile.hk_binding}. \
Check that it is formatted properly and valid keys."
                                sp_logging.G_LOGGER.warning(msg)
                                sp_logging.G_LOGGER.warning(sys.exc_info()[0])
                                if not running_kde():
                                    show_message_dialog(msg, "Error")
                        elif profile.hk_binding in self.seen_binding:
                            msg = f"Could not register hotkey: '{profile.hk_binding}' for profile: '{profile.name}'.\n\
It is already registered for another action."
                            sp_logging.G_LOGGER.warning(msg)
                            if not running_kde():
                                show_message_dialog(msg, "Error")
                # except (SystemHotkeyError, SystemRegisterError, UnregisterError, InvalidKeyError):
                except Exception:
                    if sp_logging.DEBUG:
                        sp_logging.G_LOGGER.info("Coulnd't register hotkeys, exception:")
                        sp_logging.G_LOGGER.info(sys.exc_info()[0])

    def update_hotkey(self, profile_name, old_hotkey, new_hotkey):
        """Rebind a profile's hotkey after the profile was saved with a different one."""
        if self.hk2 is None:
            return  # hotkeys are disabled or unavailable
        new_hotkey = tuple(new_hotkey.split("+")) if new_hotkey else None
        if old_hotkey == new_hotkey:
            return
        if old_hotkey in self.seen_binding:
            try:
                self.hk2.unregister(old_hotkey)
                self.seen_binding.remove(old_hotkey)
            except Exception:
                # The binding belongs to another action, or the library refused it.
                sp_logging.G_LOGGER.warning("Could not unregister hotkey %s: %s", old_hotkey, sys.exc_info()[1])
        if new_hotkey is None:
            return
        try:
            self.hk2.register(new_hotkey, ProfileId.parse(profile_name), overwrite=False)
            self.seen_binding.add(new_hotkey)
        except Exception:
            msg = f"Error: could not register hotkey {'+'.join(new_hotkey)}. \
Check that it is formatted properly and valid keys."
            sp_logging.G_LOGGER.warning(msg)
            sp_logging.G_LOGGER.warning(sys.exc_info()[0])
            if not running_kde():
                show_message_dialog(msg, "Error")

    def get_profile_by_name(self, name):
        try:
            return self.get_profile_by_id(ProfileId.parse(name))
        except ProfileIdError:
            return None

    def get_profile_by_id(self, profile_id):
        for prof in self.list_of_profiles:
            if prof.profile_id == profile_id:
                return prof
        return None

    def profile_consumer(self, event, hotkey, bound_args):
        """Start the profile bound to a hotkey; called on the hotkey listener thread."""
        profile_id = bound_args[0][0]
        wx.CallAfter(self.start_profile_by_id, profile_id)

    def start_profile_by_id(self, profile_id):
        """Start the profile currently loaded under ``profile_id``, if it still exists."""
        profile = self.get_profile_by_id(profile_id)
        if profile is None:
            sp_logging.G_LOGGER.info("The profile bound to this hotkey, '%s', no longer exists.", profile_id.value)
            return
        self.start_profile(None, profile)

    def read_general_settings(self):
        """Refreshes general settings from file and applies hotkey bindings."""
        self.g_settings = read_settings(self.settings_path, sys.platform)
        self.register_hotkeys()
        if self.g_settings.logging:
            msg = "Logging is enabled after an application restart."
            show_message_dialog(msg, "Info")

    def CreatePopupMenu(self):
        """Method called by WX library when user right clicks tray icon. Opens tray menu."""
        menu = wx.Menu()
        create_menu_item(menu, "Open Config Folder", self.open_config)
        create_menu_item(menu, "Wallpaper Configuration", self.configure_wallpapers)
        create_menu_item(menu, "Settings", self.configure_settings)
        create_menu_item(menu, "Reload Profiles", self.reload_profiles)
        menu.AppendSeparator()
        for item in self.list_of_profiles:
            create_menu_item(menu, item.name, self.start_profile, item)
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
        result = desktop.open_folder(self.paths.config)
        if not result.ok:
            sp_logging.G_LOGGER.error("open_config failed for %s: %s", self.paths.config, result.problem)
            show_message_dialog("There was an error trying to open the config folder.")

    def configure_wallpapers(self, event):
        """Opens wallpaper configuration panel."""
        try:
            ConfigFrame(self)
        except Exception as e:
            sp_logging.G_LOGGER.error("configure_wallpapers error: %s", e, exc_info=True)

    def configure_settings(self, event):
        """Opens general settings panel."""
        SettingsFrame(self)

    def reload_profiles(self, event):
        """Reloads profiles from disk."""
        self.list_of_profiles = list_profiles(self.paths)
        # Re-point active_profile at the freshly loaded instance (matched by
        # identity) so consumers that read tray.active_profile -- e.g. the settings
        # dialog when it reopens -- see the saved state instead of a stale
        # detached object (was causing edits like span mode to appear reverted).
        if self.active_profile is not None:
            refreshed = self.get_profile_by_id(self.active_profile.profile_id)
            if refreshed is not None:
                self.active_profile = refreshed
            else:
                with self.job_lock:
                    if self.repeating_timer is not None and self.repeating_timer.is_running:
                        self.repeating_timer.stop()
                    self.repeating_timer = None
                    self.active_profile = None
                    wpproc.G_ACTIVE_PROFILE = None

    def refresh_displays(self):
        """Detect the displays and load their saved layout; later wallpaper changes use it.

        A change already under way keeps the layout it started with, so this never
        waits for one. If detection fails, the previous layout stays in use.
        """
        self.display_system = displays.DisplaySystem(self.paths.config)

    def change_wallpaper(self, profile, *, force=False, advance=False, skip_if_busy=False, display_system=None):
        """Start one wallpaper change for ``profile``, with the settings and displays as they are now.

        The slideshow timer calls this on every tick, so a changed custom command or
        display layout applies from the next tick on. ``display_system`` renders for
        another layout instead, such as the editor's unsaved one.
        """
        return change_wallpaper_job(
            profile,
            self.paths,
            display_system=display_system if display_system is not None else self.display_system,
            set_command=self.g_settings.set_command,
            force=force,
            advance=advance,
            skip_if_busy=skip_if_busy,
        )

    def _run_profile(self, profile, *, startup=False):
        """Run ``profile`` on freshly detected displays: see run_profile_job."""
        self.refresh_displays()
        return run_profile_job(profile, self.change_wallpaper, startup=startup)

    def rearm_active_timer(self):
        """Re-arm the slideshow timer for the active profile.

        Used after the active profile's settings change in the settings dialog
        (slideshow toggled, delay edited) so the change takes effect without
        restarting the app. The current wallpaper is kept (startup=True), only
        the repeating timer is rebuilt; if the profile is no longer a slideshow
        the timer is simply stopped.
        """
        with self.job_lock:
            if self.repeating_timer is not None and self.repeating_timer.is_running:
                self.repeating_timer.stop()
            if self.active_profile is not None:
                # Keep the global active-profile name in sync with the (possibly
                # renamed) active profile; the wallpaper setter only applies when
                # profile.name matches it, so a stale name silently blocks every
                # slideshow tick and manual change after a rename/save.
                wpproc.G_ACTIVE_PROFILE = self.active_profile.name
                self.repeating_timer, _thrd = self._run_profile(self.active_profile, startup=True)
                if self.is_paused and self.repeating_timer is not None:
                    # Editing a paused slideshow must not resume it.
                    self.repeating_timer.stop()

    def start_prev_profile(self, profile, apply_now=False):
        """Checks if a previously running profile has been recorded and starts it.

        When ``apply_now`` is True (an explicit CLI ``--profile`` launch) the
        wallpaper is rendered and applied immediately. Otherwise the last shown
        wallpaper is restored without cycling and only the slideshow timer is
        armed, so a normal daemon restart does not re-cycle on every launch.
        """
        with self.job_lock:
            if profile is None:
                sp_logging.G_LOGGER.info("No previous profile was found.")
            elif apply_now:
                # Render and apply the requested profile now, then arm the
                # slideshow timer (if the profile is a slideshow).
                self.repeating_timer, thrd = self._run_profile(profile, startup=False)
            else:
                # Show the last wallpaper again without cycling, then arm the slideshow
                # timer (if any); cycling only happens later on the timer's schedule. With
                # no earlier render to show, the current wallpaper is rendered now.
                restored = quick_profile_job(
                    profile,
                    display_system=self.display_system,
                    paths=self.paths,
                    set_command=self.g_settings.set_command,
                )
                self.repeating_timer, thrd = self._run_profile(profile, startup=restored)

    def start_profile(self, event, profile, force_reload=False):
        """
        Starts a profile job, i.e. runs a slideshow or a one time wallpaper change.

        If the input profile is the currently active profile, initiate a wallpaper change.
        """
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("Start profile: %s", profile.name)
        if profile is None:
            sp_logging.G_LOGGER.info(
                "start_profile: profile is None. \
                Do you have any profiles in /profiles?"
            )
        elif self.active_profile is not None:
            if profile.name == self.active_profile.name and not force_reload:
                self.next_wallpaper(event)
                return 0
            else:
                with self.job_lock:
                    if self.repeating_timer is not None and self.repeating_timer.is_running:
                        self.repeating_timer.stop()
                    self.active_profile = profile
                    wpproc.G_ACTIVE_PROFILE = self.active_profile.name
                    if sp_logging.DEBUG:
                        sp_logging.G_LOGGER.info("Starting timed profile job with profile: %s", profile.name)
                    self.repeating_timer, thrd = self._run_profile(profile)
                    write_active_profile(self.paths.cache, profile.profile_id)
                    return thrd
        else:
            with self.job_lock:
                if self.repeating_timer is not None and self.repeating_timer.is_running:
                    self.repeating_timer.stop()
                self.active_profile = profile
                wpproc.G_ACTIVE_PROFILE = self.active_profile.name
                if sp_logging.DEBUG:
                    sp_logging.G_LOGGER.info("Starting timed profile job with profile: %s", profile.name)
                self.repeating_timer, thrd = self._run_profile(profile)
                write_active_profile(self.paths.cache, profile.profile_id)
                return thrd

    def next_wallpaper(self, event):
        """Calls the next wallpaper changer method of the running profile."""
        with self.job_lock:
            if self.repeating_timer is not None and self.repeating_timer.is_running:
                self.repeating_timer.stop()
                self.change_wallpaper(self.active_profile, advance=True)
                self.repeating_timer.start()
            else:
                self.change_wallpaper(self.active_profile, advance=True)

    def rt_stop(self):
        """Stops running slideshow timer if one is active."""
        if self.repeating_timer is not None and self.repeating_timer.is_running:
            self.repeating_timer.stop()

    def pause_timer(self, event):
        """Check if a slideshow timer is running and if it is, then try to stop/start."""
        if self.repeating_timer is not None and self.repeating_timer.is_running:
            self.repeating_timer.stop()
            self.is_paused = True
            if sp_logging.DEBUG:
                sp_logging.G_LOGGER.info("Paused timer")
        elif self.repeating_timer is not None and not self.repeating_timer.is_running:
            self.repeating_timer.start()
            self.is_paused = False
            if sp_logging.DEBUG:
                sp_logging.G_LOGGER.info("Resumed timer")
        else:
            sp_logging.G_LOGGER.info("Current profile isn't using a timer.")

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
        # info.AddDocWriter('Doc Writer')
        # info.AddTranslator('Tran Slator')
        wx.adv.AboutBox(info)

    def on_exit(self, event):
        """Exits Superpaper."""
        self.rt_stop()
        if self._sni_tray is not None:
            try:
                self._sni_tray.remove()
            except Exception as exc:
                sp_logging.G_LOGGER.info("SNI tray cleanup failed: %s", exc)
        wx.CallAfter(self.Destroy)
        self.frame.Close()


class App(wx.App):
    """wx base class for tray icon."""

    def __init__(self, paths: AppPaths, settings: Settings, startup_profile: ProfileId | None):
        # wx.App.__init__ runs OnInit, which builds the tray icon from these.
        self._paths = paths
        self._settings = settings
        self._startup_profile = startup_profile
        super().__init__(False)

    def OnInit(self):
        """Starts tray icon loop."""
        self.SetAppName("Superpaper")
        self.SetAppDisplayName("Superpaper")
        frame = wx.Frame(None)
        # self.locale = wx.Locale(wx.LANGUAGE_DEFAULT) # this has been causing errors?
        self.SetTopWindow(frame)
        TaskBarIcon(frame, self._paths, self._settings, self._startup_profile)
        return True

    def InitLocale(self):
        """Override with nothing (or impliment local if actually needed)"""
