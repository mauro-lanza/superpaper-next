"""System-wide hotkeys: the next wallpaper, pausing the slideshow, and each profile's own.

system_hotkey calls back on a listener thread of its own; every action is handed to the
GUI's main loop with ``call_soon`` before it runs.
"""

import logging
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Protocol

from superpaper.desktop.linux import running_kde
from superpaper.profiles.profile_id import ProfileId
from superpaper.settings import Settings, format_hotkey

logger = logging.getLogger(__name__)

NEXT_WALLPAPER = "next wallpaper"
PAUSE = "pause"


class HotkeySetting(Protocol):
    """The part of a saved profile that a hotkey binds: its name and keys."""

    @property
    def name(self) -> str: ...

    @property
    def hotkey(self) -> tuple[str, ...] | None: ...


class HotkeyProfile(Protocol):
    """A saved profile as hotkeys see it: its identity and its settings."""

    @property
    def profile_id(self) -> ProfileId: ...

    @property
    def profile(self) -> HotkeySetting: ...


class Hotkeys:
    """The system-wide hotkeys, and what each key combination is bound to: the next
    wallpaper, pause, or a saved profile, by its ProfileId.

    ``next_wallpaper()``, ``pause()`` and ``start_profile(profile_id)`` are run through
    ``call_soon`` when their keys are pressed; ``report(message)`` shows the user a
    registration problem. Raises ImportError if system_hotkey isn't installed.
    """

    def __init__(
        self,
        *,
        next_wallpaper: Callable[[], None],
        pause: Callable[[], None],
        start_profile: Callable[[ProfileId], None],
        call_soon: Callable[[Callable[[], None]], None],
        report: Callable[[str], None],
    ) -> None:
        from system_hotkey import SystemHotkey  # ty:ignore[unresolved-import]

        self._call_soon = call_soon
        self._show = report
        self._actions = {NEXT_WALLPAPER: next_wallpaper, PAUSE: pause}
        self._start_profile = start_profile
        self._general = SystemHotkey(check_queue_interval=0.05)
        self._profiles = SystemHotkey(consumer=self._on_profile_hotkey, check_queue_interval=0.05)
        # Key combination -> NEXT_WALLPAPER, PAUSE or the ProfileId it starts.
        self._owners: dict[tuple[str, ...], str | ProfileId] = {}

    def register_general(self, settings: Settings) -> None:
        """Bind the next-wallpaper and pause hotkeys of ``settings``. A changed one
        replaces the keys it had; one that isn't set is left unbound."""
        for action, keys in ((NEXT_WALLPAPER, settings.hk_binding_next), (PAUSE, settings.hk_binding_pause)):
            bound = next((bound for bound, owner in self._owners.items() if owner == action), None)
            if keys is None:
                if bound is not None:
                    self._release(self._general, bound)
                continue
            if keys == bound:
                continue
            if keys in self._owners:
                self._report_taken(keys, action)
                continue
            try:
                self._general.register(keys, callback=lambda _event, run=self._actions[action]: self._call_soon(run))
            except Exception:
                self._report_refused(keys)
                continue
            self._owners[keys] = action
            if bound is not None:
                self._release(self._general, bound)

    def register_profiles(self, profiles: Iterable[HotkeyProfile]) -> None:
        """Bind each of the saved ``profiles``' own hotkey."""
        for stored in profiles:
            keys = stored.profile.hotkey
            if keys is not None:
                self._bind_profile(stored, keys)

    def profile_changed(self, before: HotkeyProfile | None, after: HotkeyProfile | None) -> None:
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
            self._bind_profile(after, after.profile.hotkey)

    def _bind_profile(self, stored: HotkeyProfile, keys: tuple[str, ...]) -> None:
        owner = self._owners.get(keys)
        if owner == stored.profile_id:
            return
        if owner is not None:
            self._report_taken(keys, f"profile: '{stored.profile.name}'")
            return
        try:
            # Bind the identity, not the record: a profile edited later must start with its
            # current settings.
            self._profiles.register(keys, stored.profile_id, overwrite=False)
        except Exception:
            self._report_refused(keys)
            return
        self._owners[keys] = stored.profile_id

    def _release(self, hotkeys: Any, keys: tuple[str, ...]) -> None:
        del self._owners[keys]
        try:
            hotkeys.unregister(keys)
        except Exception as error:
            logger.warning("Could not unregister hotkey %s: %s", format_hotkey(keys), error)

    def _on_profile_hotkey(self, event: Any, hotkey: Any, bound_args: Sequence[Sequence[ProfileId]]) -> None:
        """system_hotkey's consumer: start the profile bound to ``hotkey``. Called on its
        listener thread with the arguments the keys were registered with."""
        profile_id = bound_args[0][0]
        self._call_soon(lambda: self._start_profile(profile_id))

    def _report_taken(self, keys: tuple[str, ...], wanted_for: str) -> None:
        self._report(
            f"Could not register hotkey: '{format_hotkey(keys)}' for {wanted_for}.\nIt is already registered for another action."
        )

    def _report_refused(self, keys: tuple[str, ...]) -> None:
        self._report(
            f"Error: could not register hotkey {format_hotkey(keys)}. Check that it is formatted properly and valid keys."
        )

    def _report(self, message: str) -> None:
        logger.warning("%s", message)
        if not running_kde():
            self._show(message)
