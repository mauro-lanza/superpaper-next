"""Tray applet for Superpaper."""

import configparser
import os
import sys

import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]
import wx.adv  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

import superpaper.desktop as desktop
import superpaper.displays as displays
import superpaper.profile_store as profile_store
import superpaper.render_cache as render_cache
import superpaper.sp_logging as sp_logging
from superpaper.__version__ import __version__
from superpaper.desktop.linux import running_kde
from superpaper.paths import AppPaths, resource
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.profile_store import ProfileDiagnosticKind, ProfileStore
from superpaper.session import Session
from superpaper.settings import SETTINGS_FILE, Settings, read_settings
from superpaper.ui.editor import ConfigFrame
from superpaper.ui.help import HelpFrame
from superpaper.ui.message import show_message_dialog
from superpaper.ui.settings_dialog import SettingsFrame
from superpaper.ui.sni_tray import build_tray, sni_supported

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
        # The running profile, its slideshow and every wallpaper change, starting with the
        # displays as they are now.
        self.session = Session(
            self.paths,
            displays.DisplaySystem(self.paths.config),
            set_command=lambda: self.g_settings.set_command,
        )
        self.pause_item = None
        self.store = ProfileStore(self.paths)
        self._load_profiles()
        # Renders and selections of profiles deleted or renamed since the last start
        # aren't needed.
        stored = profile_store.stored_profile_ids(self.paths)
        if stored is not None:
            render_cache.sweep(self.paths.cache, stored)
            profile_store.sweep_selections(self.paths.cache, stored)
        self._run_at_startup(startup_profile)
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

    def _run_at_startup(self, startup_profile):
        """Run the profile asked for on the command line, or carry on with the one that ran
        when Superpaper last exited."""
        if startup_profile:
            # An explicit `--profile` launch runs the profile now, as the tray menu does.
            started = self.get_profile_by_id(startup_profile)
            if started is None:
                sp_logging.G_LOGGER.error(
                    "Startup profile '%s' could not be matched to a saved profile.", startup_profile.value
                )
            else:
                self.session.activate(started)
            return
        # A normal start shows the last wallpaper again, and the slideshow carries on from
        # there on its own schedule (issue #140).
        previous = self.store.active()
        if previous is None:
            sp_logging.G_LOGGER.info("No previous profile was found.")
        else:
            self.session.restore(previous)

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
                    for stored in self.list_of_profiles:
                        hotkey = stored.profile.hotkey
                        if sp_logging.DEBUG:
                            sp_logging.G_LOGGER.info(
                                "Registering binding: \
                                %s for profile: %s",
                                hotkey,
                                stored.profile.name,
                            )
                        if hotkey is not None and hotkey not in self.seen_binding:
                            try:
                                # Bind the identity, not the object: a profile edited later
                                # must start with its current settings.
                                hk2.register(hotkey, stored.profile_id, overwrite=False)
                                self.seen_binding.add(hotkey)
                            # except (SystemHotkeyError, SystemRegisterError, InvalidKeyError):
                            except Exception:
                                msg = f"Error: could not register hotkey {hotkey}. \
Check that it is formatted properly and valid keys."
                                sp_logging.G_LOGGER.warning(msg)
                                sp_logging.G_LOGGER.warning(sys.exc_info()[0])
                                if not running_kde():
                                    show_message_dialog(msg, "Error")
                        elif hotkey in self.seen_binding:
                            msg = f"Could not register hotkey: '{hotkey}' for profile: '{stored.profile.name}'.\n\
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
        """Rebind a profile's hotkey (a tuple of keys, or None) after the profile was saved
        with a different one."""
        if self.hk2 is None:
            return  # hotkeys are disabled or unavailable
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

    @property
    def list_of_profiles(self):
        """The saved profiles, in the order the menus show them."""
        return self.store.profiles

    @property
    def active_profile(self):
        """The running profile, if any."""
        return self.session.running

    @property
    def is_paused(self):
        return self.session.paused

    @property
    def display_system(self):
        """The display layout wallpaper changes are rendered for."""
        return self.session.display_system

    def get_profile_by_name(self, name):
        try:
            return self.get_profile_by_id(ProfileId.parse(name))
        except ProfileIdError:
            return None

    def get_profile_by_id(self, profile_id):
        return self.store.get(profile_id)

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
                sp_logging.G_LOGGER.warning("Ignoring %s: %s", diagnostic.path, diagnostic.detail)
                continue
            message = (
                f"There was an error when loading profile '{diagnostic.path.name}'.\n"
                "Would you like to delete it? Choosing 'No' will just ignore the profile."
            )
            sp_logging.G_LOGGER.info("%s %s", message, diagnostic.detail)
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
            sp_logging.G_LOGGER.warning("Keeping the previous display layout: %s", error)
            return
        self.session.use_displays(display_system)

    def apply_draft(self, profile, images, *, display_system=None, on_done=None):
        """Show ``images`` with ``profile``'s settings, which aren't a running profile's,
        such as the editor's unsaved ones: see Session.apply_draft."""
        self.session.apply_draft(profile, images, display_system=display_system, on_done=on_done)

    def start_profile(self, event, profile):
        """Run ``profile`` on the displays as they are now, or show its next image if it
        runs already."""
        if profile is None:
            sp_logging.G_LOGGER.info("start_profile: profile is None. Do you have any profiles in /profiles?")
            return
        self.refresh_displays()
        self.session.activate(profile)

    def next_wallpaper(self, event):
        """Show the running profile's next image."""
        self.session.next()

    def pause_timer(self, event):
        """Pause the running slideshow, or resume it."""
        self.session.toggle_pause()

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
        self.session.shutdown()
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
