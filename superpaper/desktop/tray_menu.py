"""The tray menu as data: built by the wx tray, rendered by the wx menu and the native SNI menu."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Protocol

from superpaper.profiles.profile_store import StoredProfile


@dataclass(frozen=True, slots=True)
class Item:
    label: str
    action: Callable[[], None]
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class Check:
    label: str
    action: Callable[[], None]
    checked: bool
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class Notice:
    """A disabled line of text."""

    label: str


@dataclass(frozen=True, slots=True)
class Separator:
    pass


@dataclass(frozen=True, slots=True)
class Submenu:
    label: str
    items: tuple[Item | Check | Notice, ...]


MenuEntry = Item | Check | Notice | Separator | Submenu


class TrayHandle(Protocol):
    """A tray icon the desktop draws itself."""

    def remove(self) -> None: ...


_MAX_REASON = 80


def failure_notice(reason: str) -> Notice:
    """The menu line for a wallpaper change that failed: the first line of ``reason``, cut short."""
    line = (reason.strip().splitlines() or [""])[0]
    if len(line) > _MAX_REASON:
        line = line[: _MAX_REASON - 1] + "…"
    return Notice(f"Last change failed: {line}")


def tray_menu(
    profiles: Sequence[StoredProfile],
    running: StoredProfile | None,
    *,
    paused: bool,
    last_failure: str | None,
    open_config_folder: Callable[[], None],
    open_editor: Callable[[], None],
    open_settings: Callable[[], None],
    reload_profiles: Callable[[], None],
    start_profile: Callable[[StoredProfile], None],
    next_wallpaper: Callable[[], None],
    toggle_pause: Callable[[], None],
    about: Callable[[], None],
    quit: Callable[[], None],
) -> tuple[MenuEntry, ...]:
    """The tray menu for the saved ``profiles``, the ``running`` one among them, and whether its slideshow is ``paused``."""
    profile_entries = tuple(
        Check(
            stored.profile.name,
            partial(start_profile, stored),
            checked=running is not None and running.profile_id == stored.profile_id,
        )
        for stored in profiles
    ) or (Notice("(no profiles)"),)
    failed = (failure_notice(last_failure), Separator()) if last_failure is not None else ()
    return (
        *failed,
        Item("Open Config Folder", open_config_folder),
        Item("Wallpaper Configuration", open_editor),
        Item("Settings", open_settings),
        Item("Reload Profiles", reload_profiles),
        Separator(),
        Submenu("Profiles", profile_entries),
        Separator(),
        Item("Next Wallpaper", next_wallpaper, enabled=running is not None),
        Check("Pause Timer", toggle_pause, checked=paused, enabled=running is not None and running.profile.slideshow),
        Separator(),
        Item("About", about),
        Item("Exit", quit),
    )
