"""Superpaper as it runs: the saved profiles, the session that runs them, the general
settings, the hotkeys and the tray icon, and what connects them. The windows and dialogs
are the UI's; they come in as a ``Shell``."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import superpaper.geometry.display_detection as display_detection
from superpaper.desktop.backend import Desktop
from superpaper.desktop.hotkeys import Hotkeys
from superpaper.paths import AppPaths
from superpaper.profile_actions import carry_on_running
from superpaper.profiles import profile_store
from superpaper.profiles.profile_id import ProfileId
from superpaper.profiles.profile_store import ProfileDiagnosticKind, ProfileStore, StoredProfile
from superpaper.rendering import render_cache
from superpaper.session import Session
from superpaper.settings import SETTINGS_FILE, Settings, write_settings

logger = logging.getLogger(__name__)


class Tray(Protocol):
    """The tray icon the UI makes."""

    @property
    def clickable(self) -> bool: ...

    def remove(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Shell:
    """What the UI does for Superpaper. The ``open_*`` and ``make_tray`` actions are given
    the running Superpaper to build their windows and icon from."""

    notify: Callable[[str, str], None]  # message, title
    confirm: Callable[[str], bool]
    call_soon: Callable[[Callable[[], None]], None]
    open_editor: Callable[[Superpaper], None]
    open_settings: Callable[[Superpaper], None]
    open_help: Callable[[Superpaper], None]
    make_tray: Callable[[Superpaper], Tray]
    close: Callable[[], None]
    settle_unsaved_changes: Callable[[], bool]  # False: the user kept the editor's unsaved changes open


class Superpaper:
    """The tray application as it runs; ``shell`` is the UI it runs in."""

    def __init__(
        self, shell: Shell, paths: AppPaths, desktop: Desktop, settings: Settings, startup_profile: ProfileId | None
    ):
        self._shell = shell
        self.desktop = desktop
        self.paths = paths
        self.settings_path = paths.config / SETTINGS_FILE
        self.settings = settings
        # The running profile, its slideshow and every wallpaper change, starting with the
        # displays as they are now. Wallpaper changes use the custom command as last saved.
        self.last_failure: str | None = None
        # The profile last loaded or saved in the editor, for it to open on when nothing runs.
        self.last_edited: ProfileId | None = None
        self._profile_watchers: list[Callable[[], None]] = []
        loaded = display_detection.detect_layout_or_default(paths.config, desktop)
        self._reported_layout_problem: str | None = None
        self._report_layout_problem(loaded.problem)
        self.session = Session(
            paths,
            desktop,
            loaded.layout,
            on_change=self._report_change,
            on_running_change=self._report_running_change,
            set_command=lambda: self.settings.set_command,
        )
        self.store = ProfileStore(paths, windows_names=desktop.strict_profile_names())
        self._load_profiles()
        # Renders and selections of profiles deleted or renamed since the last start
        # aren't needed.
        kept = self.store.sweep()
        if kept is not None:
            render_cache.sweep(paths.cache, [profile_id.value for profile_id in kept])
        self._run_at_startup(startup_profile)
        self.hotkeys = self._start_hotkeys()
        self.tray = shell.make_tray(self)
        self._show_at_start()

    def _report_change(self, problem: str | None) -> None:
        """Remember how the session's last change went, for the tray menu; called on the
        session's worker thread, so it is handed to the UI's."""

        def remember() -> None:
            self.last_failure = problem

        self._shell.call_soon(remember)

    def _report_running_change(self) -> None:
        """Tell the watchers that the running profile changed; called on the session's worker
        thread, so they are told on the UI's."""
        self._shell.call_soon(self._notify_profile_watchers)

    def _notify_profile_watchers(self) -> None:
        for watcher in list(self._profile_watchers):
            watcher()

    def watch_profiles(self, watcher: Callable[[], None]) -> Callable[[], None]:
        """Call ``watcher()``, on the UI thread, whenever the saved profiles are loaded again
        or the running profile changes; returns the function that stops that."""
        self._profile_watchers.append(watcher)
        return lambda: self._profile_watchers.remove(watcher)

    def _run_at_startup(self, startup_profile: ProfileId | None) -> None:
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
        # there on its own schedule.
        previous = self.store.active()
        if previous is None:
            logger.info("No previous profile was found.")
        else:
            self.session.restore(previous)

    def _start_hotkeys(self) -> Hotkeys | None:
        """The system-wide hotkeys, bound; None while they are off or unavailable. Hotkeys
        turned on or off in the settings apply after a restart."""
        if not self.settings.use_hotkeys:
            return None
        try:
            hotkeys = Hotkeys(
                next_wallpaper=self.session.next,
                pause=self.session.toggle_pause,
                start_profile=self.start_profile_by_id,
                call_soon=self._shell.call_soon,
                report=lambda message: self._shell.notify(message, "Error"),
                show_problems=self.desktop.hotkey_problems_in_dialog(),
            )
        except ImportError as error:
            logger.warning("Could not import keyboard hotkey hook library, hotkeys will not work. Exception: %s", error)
            return None
        hotkeys.register_general(self.settings)
        hotkeys.register_profiles(self.store.profiles)
        return hotkeys

    def _show_at_start(self) -> None:
        """Open the help and the configuration if they are to be shown at start, and say
        once if wallpapers can't be set here or the displays' sizes aren't known."""
        if self.settings.show_help:
            self.open_editor()
            self._shell.open_help(self)
        elif not self.tray.clickable:
            # KDE Plasma 6 workaround: clicks on the wx tray icon don't work there, so the
            # configuration opens at startup.
            logger.info("KDE Plasma without the native tray: auto-opening the configuration")
            self._shell.call_soon(self.open_editor)
        # Say once, now, if wallpapers can't be set here, rather than on every change.
        problem = self.desktop.setter_problem(self.settings.set_command)
        if problem:
            logger.error("%s", problem)
            self._shell.call_soon(lambda: self._shell.notify(problem, "Error"))
        size_hint = self.session.layout.size_hint()
        if size_hint:
            logger.warning("%s", size_hint)
            self._shell.call_soon(lambda: self._shell.notify(size_hint, "Info"))

    def open_editor(self) -> None:
        """Open the wallpaper configuration."""
        try:
            self._shell.open_editor(self)
        except Exception as error:
            logger.error("Could not open the wallpaper configuration: %s", error, exc_info=True)

    def open_settings(self) -> None:
        """Open the general settings."""
        self._shell.open_settings(self)

    def start_profile(self, stored: StoredProfile) -> None:
        """Run the saved profile ``stored`` on the displays as they are now; if it runs
        already, only unpause it and restart its countdown."""
        self.refresh_displays()
        self.session.activate(stored)

    def start_profile_by_id(self, profile_id: ProfileId) -> None:
        """Start the profile currently loaded under ``profile_id``, if it still exists."""
        stored = self.store.get(profile_id)
        if stored is None:
            logger.info("The profile bound to this hotkey, '%s', no longer exists.", profile_id.value)
            return
        self.start_profile(stored)

    def reload_profiles(self) -> None:
        """Load the profiles again and carry on running the profile that was running."""
        self._load_profiles()
        carry_on_running(self.store, self.session)
        self._notify_profile_watchers()

    def _load_profiles(self) -> None:
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
            if self._shell.confirm(message):
                profile_store.delete_malformed(diagnostic)

    def refresh_displays(self) -> None:
        """Detect the displays again and load their saved layout; later wallpaper changes
        use it. If detection fails, the previous layout stays in use. A saved layout that
        can't be used is replaced by the default arrangement, and the user told once.

        Displays are detected here, on the main thread, never by the session's worker:
        see display_detection.detect_displays.
        """
        try:
            loaded = display_detection.detect_layout_or_default(self.paths.config, self.desktop)
        except (display_detection.DisplayDetectionError, OSError) as error:
            logger.warning("Keeping the previous display layout: %s", error)
            return
        self._report_layout_problem(loaded.problem)
        self.session.use_displays(loaded.layout)

    def _report_layout_problem(self, problem: str | None) -> None:
        """Tell the user why the saved layout isn't used, unless they were told already."""
        if problem is not None and problem != self._reported_layout_problem:
            logger.warning("%s", problem)
            self._shell.call_soon(lambda: self._shell.notify(problem, "Error"))
        self._reported_layout_problem = problem

    def rebind_hotkey(self, before: StoredProfile | None, after: StoredProfile | None) -> None:
        """Rebind a profile's hotkey once it was saved, renamed or deleted: see
        Hotkeys.profile_changed."""
        if self.hotkeys is not None:
            self.hotkeys.profile_changed(before, after)

    def update_settings(self, settings: Settings) -> bool:
        """Save ``settings`` as the general settings; windows and wallpaper changes use them
        from now on. If they can't be written the user is told and nothing changes; returns
        whether they were saved. The one writer of the settings file while running."""
        try:
            write_settings(self.settings_path, settings)
        except OSError as error:
            logger.exception("Could not save the settings")
            self._shell.notify(f"The settings could not be saved: {error}", "Error")
            return False
        self.settings = settings
        return True

    def apply_settings(self, settings: Settings) -> bool:
        """Save the general settings from the settings window and apply them to the hotkeys;
        returns whether they were saved."""
        if not self.update_settings(settings):
            return False
        # Hotkeys turned on or off apply after a restart.
        if self.hotkeys is not None and settings.use_hotkeys:
            self.hotkeys.register_general(settings)
        if settings.logging:
            self._shell.notify("Logging is enabled after an application restart.", "Info")
        return True

    def quit(self) -> None:
        """Stop the session, take the tray icon away and close the application, unless the
        user keeps unsaved changes in the editor open."""
        if not self._shell.settle_unsaved_changes():
            return
        self.session.shutdown()
        self.tray.remove()
        self._shell.close()
