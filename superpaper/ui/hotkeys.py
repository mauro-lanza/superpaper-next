"""System-wide hotkeys: the next wallpaper, pausing the slideshow, and each profile's own.

system_hotkey calls back on a listener thread of its own; every action is handed to the
wx main loop before it runs.
"""

import logging

import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

from superpaper.desktop.linux import running_kde
from superpaper.ui.message import show_message_dialog

logger = logging.getLogger(__name__)

NEXT_WALLPAPER = "next wallpaper"
PAUSE = "pause"


class Hotkeys:
    """The system-wide hotkeys, and what each key combination is bound to: the next
    wallpaper, pause, or a saved profile, by its ProfileId.

    ``next_wallpaper()``, ``pause()`` and ``start_profile(profile_id)`` are run on the wx
    main loop when their keys are pressed. Raises ImportError if system_hotkey isn't
    installed.
    """

    def __init__(self, *, next_wallpaper, pause, start_profile):
        from system_hotkey import SystemHotkey  # ty:ignore[unresolved-import]

        self._actions = {NEXT_WALLPAPER: next_wallpaper, PAUSE: pause}
        self._start_profile = start_profile
        self._general = SystemHotkey(check_queue_interval=0.05)
        self._profiles = SystemHotkey(consumer=self._on_profile_hotkey, check_queue_interval=0.05)
        # Key combination -> NEXT_WALLPAPER, PAUSE or the ProfileId it starts.
        self._owners = {}

    def register_general(self, settings):
        """Bind the next-wallpaper and pause hotkeys of ``settings``. A changed one
        replaces the keys it had; one that isn't set is left unbound."""
        for action, keys in ((NEXT_WALLPAPER, settings.hk_binding_next), (PAUSE, settings.hk_binding_pause)):
            bound = next((bound for bound, owner in self._owners.items() if owner == action), None)
            if keys == bound or keys is None:
                continue
            if keys in self._owners:
                _report_taken(keys, action)
                continue
            try:
                self._general.register(keys, callback=lambda _event, run=self._actions[action]: wx.CallAfter(run))
            except Exception:
                _report_refused(keys)
                continue
            self._owners[keys] = action
            if bound is not None:
                self._release(self._general, bound)

    def register_profiles(self, profiles):
        """Bind each of the saved ``profiles``' own hotkey."""
        for stored in profiles:
            if stored.profile.hotkey is not None:
                self._bind_profile(stored)

    def profile_changed(self, before, after):
        """Rebind a profile's hotkey once the profile was saved, renamed or deleted:
        ``before`` is its record as it was (None for a new profile), ``after`` as it is
        now (None once deleted)."""
        old = (before.profile_id, before.profile.hotkey) if before is not None else None
        new = (after.profile_id, after.profile.hotkey) if after is not None else None
        if old == new:
            return
        if (
            before is not None
            and before.profile.hotkey is not None
            and self._owners.get(before.profile.hotkey) == before.profile_id
        ):
            self._release(self._profiles, before.profile.hotkey)
        if after is not None and after.profile.hotkey is not None:
            self._bind_profile(after)

    def _bind_profile(self, stored):
        keys = stored.profile.hotkey
        owner = self._owners.get(keys)
        if owner == stored.profile_id:
            return
        if owner is not None:
            _report_taken(keys, f"profile: '{stored.profile.name}'")
            return
        try:
            # Bind the identity, not the record: a profile edited later must start with its
            # current settings.
            self._profiles.register(keys, stored.profile_id, overwrite=False)
        except Exception:
            _report_refused(keys)
            return
        self._owners[keys] = stored.profile_id

    def _release(self, hotkeys, keys):
        del self._owners[keys]
        try:
            hotkeys.unregister(keys)
        except Exception as error:
            logger.warning("Could not unregister hotkey %s: %s", "+".join(keys), error)

    def _on_profile_hotkey(self, event, hotkey, bound_args):
        """system_hotkey's consumer: start the profile bound to ``hotkey``. Called on its
        listener thread with the arguments the keys were registered with."""
        profile_id = bound_args[0][0]
        wx.CallAfter(self._start_profile, profile_id)


def _report_taken(keys, wanted_for):
    _report(
        f"Could not register hotkey: '{'+'.join(keys)}' for {wanted_for}.\nIt is already registered for another action."
    )


def _report_refused(keys):
    _report(f"Error: could not register hotkey {'+'.join(keys)}. Check that it is formatted properly and valid keys.")


def _report(message):
    logger.warning("%s", message)
    # Hotkey errors have only been logged on KDE Plasma since per-activity wallpapers
    # came in; elsewhere they are shown too.
    if not running_kde():
        show_message_dialog(message, "Error")
