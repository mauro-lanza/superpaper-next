"""Tray applet for Superpaper."""
# from configuration_dialogs import * # Katso ensin että tuleeko tästä liian pitkä dialogien kanssa.

import os
import subprocess
import sys
from threading import Lock

import superpaper.sp_logging as sp_logging
import superpaper.sp_paths as sp_paths
import superpaper.wallpaper_processing as wpproc
from superpaper.__version__ import __version__
from superpaper.configuration_dialogs import HelpFrame, SettingsFrame
from superpaper.data import (
    GeneralSettingsData,
    list_profiles,
    read_active_profile,
    write_active_profile,
)
from superpaper.gui import ConfigFrame
from superpaper.message_dialog import show_message_dialog
from superpaper.sp_platform import IS_MACOS, IS_WINDOWS
from superpaper.wallpaper_processing import (
    change_wallpaper_job,
    quick_profile_job,
    run_profile_job,
)

try:
    import wx
    import wx.adv
except ImportError as import_e:
    sp_logging.G_LOGGER.info("Failed to define tray applet classes. Is wxPython installed?")
    sp_logging.G_LOGGER.info(import_e)
    exit()


# Constants
TRAY_TOOLTIP = "Superpaper"
TRAY_ICON = os.path.join(sp_paths.PATH, "superpaper/resources/superpaper.png")
STARTUP_PROFILE = None


def tray_loop(profile=None):
    """Runs the tray applet."""
    global STARTUP_PROFILE
    if not os.path.isdir(sp_paths.PROFILES_PATH):
        os.mkdir(sp_paths.PROFILES_PATH)
    if "wx" in sys.modules:
        # On Linux (wxGTK) the tray icon (StatusNotifierItem) title is derived
        # from the program name, i.e. the basename of sys.argv[0]. When launched
        # via "python -m superpaper" this becomes "__main__.py", so normalize it
        # to a clean application name before the wx.App is created.
        sys.argv[0] = "Superpaper"
        if profile:
            STARTUP_PROFILE = profile
            sp_logging.G_LOGGER.info(f"Startup profile: {profile}")
        app = App(False)
        app.MainLoop()
    else:
        print(
            "ERROR: Module 'wx' import has failed. Is it installed? \
GUI unavailable, exiting."
        )
        sp_logging.G_LOGGER.error(
            "ERROR: Module 'wx' import has failed. Is it installed? \
GUI unavailable, exiting."
        )
        exit()


# Tray applet definitions
def create_menu_item(menu, label, func, *args, **kwargs):
    """Helper function to create menu items for the tray menu."""
    item = wx.MenuItem(menu, -1, label, **kwargs)
    menu.Bind(wx.EVT_MENU, lambda event: func(event, *args), id=item.GetId())
    menu.Append(item)
    return item


class TaskBarIcon(wx.adv.TaskBarIcon):
    """Taskbar icon and menu class."""

    def __init__(self, frame):
        self.g_settings = GeneralSettingsData()

        self.frame = frame
        super().__init__()
        self.set_icon(TRAY_ICON)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.configure_wallpapers)
        self.Bind(wx.adv.EVT_TASKBAR_RIGHT_DOWN, self.on_right_down)
        # Initialize display data
        # get_display_data()
        wpproc.refresh_display_data()
        # profile initialization
        self.job_lock = Lock()
        self.repeating_timer = None
        self.pause_item = None
        self.is_paused = False
        # if sp_logging.DEBUG:
        # sp_logging.G_LOGGER.info("START Listing profiles for menu.")
        self.list_of_profiles = list_profiles()
        # if sp_logging.DEBUG:
        # sp_logging.G_LOGGER.info("END Listing profiles for menu.")
        # Should now return an object if a previous profile was written or
        # None if no previous data was found
        if STARTUP_PROFILE:
            self.active_profile = self.get_profile_by_name(STARTUP_PROFILE)
        else:
            prev_active_prof = read_active_profile()
            if prev_active_prof:
                self.active_profile = self.get_profile_by_name(prev_active_prof.name)
            else:
                self.active_profile = None
        if self.active_profile:
            wpproc.G_ACTIVE_PROFILE = self.active_profile.name
        self.start_prev_profile(self.active_profile)
        # if self.active_profile is None:
        #     sp_logging.G_LOGGER.info("Starting up the first profile found.")
        #     self.start_profile(wx.EVT_MENU, self.list_of_profiles[0])

        # self.hk = None
        # self.hk2 = None
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
                self.seen_binding = set()
                self.register_hotkeys()
            except ImportError as excep:
                sp_logging.G_LOGGER.info(
                    "WARNING: Could not import keyboard hotkey hook library, \
hotkeys will not work. Exception: %s",
                    excep,
                )
        if self.g_settings.show_help is True:
            config_frame = ConfigFrame(self)  # noqa: F841
            help_frame = HelpFrame()  # noqa: F841
        elif wpproc.running_kde():
            # KDE Plasma 6 workaround: tray icon clicks don't work with wxPython
            # Automatically open the config GUI on startup
            sp_logging.G_LOGGER.info("KDE Plasma detected: Auto-opening configuration GUI")
            wx.CallAfter(self.configure_wallpapers, None)

    def register_hotkeys(self):
        """Registers system-wide hotkeys for profiles and application interaction."""
        if self.g_settings.use_hotkeys is True:
            if "system_hotkey" not in sys.modules:
                try:
                    # import keyboard # https://github.com/boppreh/keyboard
                    # This import allows access to the specific errors in this method.
                    from system_hotkey import (
                        InvalidKeyError,  # noqa: F401
                        SystemHotkey,  # noqa: F401
                        SystemHotkeyError,  # noqa: F401
                        SystemRegisterError,  # noqa: F401
                        UnregisterError,  # noqa: F401
                    )
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
                            self.hk.register(
                                self.g_settings.hk_binding_next,
                                callback=lambda x: self.next_wallpaper(wx.EVT_MENU),
                                overwrite=False,
                            )
                            self.seen_binding.add(self.g_settings.hk_binding_next)
                        # except (SystemHotkeyError, SystemRegisterError, InvalidKeyError):
                        except:  # noqa: E722
                            msg = f"Error: could not register hotkey {self.g_settings.hk_binding_next}. \
Check that it is formatted properly and valid keys."
                            sp_logging.G_LOGGER.warning(msg)
                            sp_logging.G_LOGGER.warning(sys.exc_info()[0])
                            if not wpproc.running_kde():
                                show_message_dialog(msg, "Error")
                    if self.g_settings.hk_binding_pause not in self.seen_binding:
                        try:
                            self.hk.register(
                                self.g_settings.hk_binding_pause,
                                callback=lambda x: self.pause_timer(wx.EVT_MENU),
                                overwrite=False,
                            )
                            self.seen_binding.add(self.g_settings.hk_binding_pause)
                        # except (SystemHotkeyError, SystemRegisterError, InvalidKeyError):
                        except:  # noqa: E722
                            msg = f"Error: could not register hotkey {self.g_settings.hk_binding_pause}. \
Check that it is formatted properly and valid keys."
                            sp_logging.G_LOGGER.warning(msg)
                            sp_logging.G_LOGGER.warning(sys.exc_info()[0])
                            if not wpproc.running_kde():
                                show_message_dialog(msg, "Error")
                    # try:
                    # self.hk.register(('control', 'super', 'shift', 'q'),
                    #  callback=lambda x: self.on_exit(wx.EVT_MENU))
                    # except (SystemHotkeyError, SystemRegisterError, InvalidKeyError):
                    # pass

                    # register profile specific bindings
                    self.list_of_profiles = list_profiles()
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
                                self.hk2.register(profile.hk_binding, profile, overwrite=False)
                                self.seen_binding.add(profile.hk_binding)
                            # except (SystemHotkeyError, SystemRegisterError, InvalidKeyError):
                            except:  # noqa: E722
                                msg = f"Error: could not register hotkey {profile.hk_binding}. \
Check that it is formatted properly and valid keys."
                                sp_logging.G_LOGGER.warning(msg)
                                sp_logging.G_LOGGER.warning(sys.exc_info()[0])
                                if not wpproc.running_kde():
                                    show_message_dialog(msg, "Error")
                        elif profile.hk_binding in self.seen_binding:
                            msg = f"Could not register hotkey: '{profile.hk_binding}' for profile: '{profile.name}'.\n\
It is already registered for another action."
                            sp_logging.G_LOGGER.warning(msg)
                            if not wpproc.running_kde():
                                show_message_dialog(msg, "Error")
                # except (SystemHotkeyError, SystemRegisterError, UnregisterError, InvalidKeyError):
                except:  # noqa: E722
                    if sp_logging.DEBUG:
                        sp_logging.G_LOGGER.info("Coulnd't register hotkeys, exception:")
                        sp_logging.G_LOGGER.info(sys.exc_info()[0])

    def update_hotkey(self, profile_name, old_hotkey, new_hotkey):
        if new_hotkey:
            new_hotkey = tuple(new_hotkey.split("+"))
        else:
            return
        if old_hotkey == new_hotkey:
            return
        profile = self.get_profile_by_name(profile_name)
        if old_hotkey is not None:
            self.hk2.unregister(old_hotkey)
            self.seen_binding.remove(old_hotkey)
        if new_hotkey is not None and profile is not None:
            try:
                self.hk2.register(new_hotkey, profile, overwrite=False)
                self.seen_binding.add(new_hotkey)
            except:  # noqa: E722
                msg = f"Error: could not register hotkey {profile.hk_binding}. \
Check that it is formatted properly and valid keys."
                sp_logging.G_LOGGER.warning(msg)
                sp_logging.G_LOGGER.warning(sys.exc_info()[0])
                if not wpproc.running_kde():
                    show_message_dialog(msg, "Error")

    def get_profile_by_name(self, name):
        for prof in self.list_of_profiles:
            if prof.name == name:
                return prof
        return None

    def profile_consumer(self, event, hotkey, profile):
        """Hotkey bindable method that starts up a profile."""
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("Profile object is: %s", profile)
        self.start_profile(wx.EVT_MENU, profile[0][0])

    def read_general_settings(self):
        """Refreshes general settings from file and applies hotkey bindings."""
        self.g_settings = GeneralSettingsData()
        try:
            self.seen_binding
        except NameError:
            self.seen_binding = set()
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
        """Opens Superpaper config folder, CONFIG_PATH."""
        if IS_WINDOWS:
            try:
                # os.startfile is Windows-only; the branch is IS_WINDOWS-guarded.
                os.startfile(sp_paths.CONFIG_PATH)  # pyright: ignore[reportAttributeAccessIssue]
            except BaseException:
                show_message_dialog("There was an error trying to open the config folder.")
        elif IS_MACOS:
            try:
                subprocess.check_call(["open", sp_paths.CONFIG_PATH])
            except subprocess.CalledProcessError:
                show_message_dialog("There was an error trying to open the config folder.")
        else:
            try:
                subprocess.check_call(["xdg-open", sp_paths.CONFIG_PATH])
            except subprocess.CalledProcessError:
                show_message_dialog("There was an error trying to open the config folder.")

    def configure_wallpapers(self, event):
        """Opens wallpaper configuration panel."""
        try:
            config_frame = ConfigFrame(self)  # noqa: F841
        except Exception as e:
            sp_logging.G_LOGGER.error("configure_wallpapers error: %s", e, exc_info=True)

    def configure_settings(self, event):
        """Opens general settings panel."""
        setting_frame = SettingsFrame(self)  # noqa: F841

    def reload_profiles(self, event):
        """Reloads profiles from disk."""
        self.list_of_profiles = list_profiles()

    def start_prev_profile(self, profile):
        """Checks if a previously running profile has been recorded and starts it."""
        with self.job_lock:
            if profile is None:
                sp_logging.G_LOGGER.info("No previous profile was found.")
            else:
                # Restore the last rendered wallpaper without cycling, then arm
                # the slideshow timer (if any). The wallpaper is not changed on
                # launch; cycling only happens later on the timer's schedule.
                quick_profile_job(profile)
                self.repeating_timer, thrd = run_profile_job(profile, startup=True)

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
            # if sp_logging.DEBUG:
            # sp_logging.G_LOGGER.info(
            #     "Check if the starting profile is already running: %s",
            #     profile.name)
            # sp_logging.G_LOGGER.info(
            #     "name check: %s, %s",
            #     profile.name, self.active_profile.name)
            if profile.name == self.active_profile.name and not force_reload:
                self.next_wallpaper(event)
                return 0
            else:
                with self.job_lock:
                    if self.repeating_timer is not None and self.repeating_timer.is_running:
                        self.repeating_timer.stop()
                    if sp_logging.DEBUG:
                        sp_logging.G_LOGGER.info("Running quick profile job with profile: %s", profile.name)
                    self.active_profile = profile
                    wpproc.G_ACTIVE_PROFILE = self.active_profile.name
                    quick_profile_job(profile)
                    if sp_logging.DEBUG:
                        sp_logging.G_LOGGER.info("Starting timed profile job with profile: %s", profile.name)
                    self.repeating_timer, thrd = run_profile_job(profile)
                    write_active_profile(profile.name)
                    # if sp_logging.DEBUG:
                    #     sp_logging.G_LOGGER.info("Wrote active profile: %s",
                    #                              profile.name)
                    return thrd
        else:
            with self.job_lock:
                if self.repeating_timer is not None and self.repeating_timer.is_running:
                    self.repeating_timer.stop()
                if sp_logging.DEBUG:
                    sp_logging.G_LOGGER.info("Running quick profile job with profile: %s", profile.name)
                self.active_profile = profile
                wpproc.G_ACTIVE_PROFILE = self.active_profile.name
                quick_profile_job(profile)
                if sp_logging.DEBUG:
                    sp_logging.G_LOGGER.info("Starting timed profile job with profile: %s", profile.name)
                self.repeating_timer, thrd = run_profile_job(profile)
                write_active_profile(profile.name)
                # if sp_logging.DEBUG:
                #     sp_logging.G_LOGGER.info("Wrote active profile: %s",
                #                              profile.name)
                return thrd

    def next_wallpaper(self, event):
        """Calls the next wallpaper changer method of the running profile."""
        with self.job_lock:
            if self.repeating_timer is not None and self.repeating_timer.is_running:
                self.repeating_timer.stop()
                change_wallpaper_job(self.active_profile, advance=True)
                self.repeating_timer.start()
            else:
                change_wallpaper_job(self.active_profile, advance=True)

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
            + "manager for Unix and Windows operating systems.\n"
            + "Features include setting a single or multiple image\n"
            + "wallpaper, pixel per inch and bezel corrections,\n"
            + "manual pixel offsets for tuning, slideshow with\n"
            + "configurable file order, multiple path support and more."
        )
        licence = (
            "Superpaper is free software; you can redistribute\n"
            + "it and/or modify it under the terms of the MIT"
            + " License.\n\n"
            + "Superpaper is distributed in the hope that it will"
            + " be useful,\n"
            + "but WITHOUT ANY WARRANTY; without even the implied"
            + " warranty of\n"
            + "MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.\n"
            + "See the MIT License for more details."
        )
        artists = "Icons kindly provided by Icons8 https://icons8.com"

        info = wx.adv.AboutDialogInfo()
        info.SetIcon(wx.Icon(TRAY_ICON, wx.BITMAP_TYPE_PNG))
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
        wx.CallAfter(self.Destroy)
        self.frame.Close()


class App(wx.App):
    """wx base class for tray icon."""

    def OnInit(self):
        """Starts tray icon loop."""
        self.SetAppName("Superpaper")
        self.SetAppDisplayName("Superpaper")
        frame = wx.Frame(None)
        # self.locale = wx.Locale(wx.LANGUAGE_DEFAULT) # this has been causing errors?
        self.SetTopWindow(frame)
        TaskBarIcon(frame)
        return True

    def InitLocale(self):
        """Override with nothing (or impliment local if actually needed)"""
        pass
