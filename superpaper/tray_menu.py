"""The tray menu as data: built here, rendered by the wx menu and the native SNI menu."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from superpaper.profiles.profile_store import ProfileStore, StoredProfile
from superpaper.session import Session


@dataclass(frozen=True, slots=True)
class Item:
    label: str
    action: Callable[[], None]


@dataclass(frozen=True, slots=True)
class Check:
    label: str
    action: Callable[[], None]
    checked: bool


@dataclass(frozen=True, slots=True)
class Separator:
    pass


@dataclass(frozen=True, slots=True)
class Submenu:
    label: str
    items: tuple[Item, ...]


MenuEntry = Item | Check | Separator | Submenu


def build_menu(
    store: ProfileStore,
    session: Session,
    *,
    open_config: Callable[[], None],
    open_editor: Callable[[], None],
    open_settings: Callable[[], None],
    reload_profiles: Callable[[], None],
    start_profile: Callable[[StoredProfile], None],
    about: Callable[[], None],
    quit: Callable[[], None],
) -> tuple[MenuEntry, ...]:
    """The tray menu as it is now: the saved profiles in ``store`` to start, and whether
    ``session``'s slideshow is paused."""
    profiles = tuple(Item(stored.profile.name, partial(start_profile, stored)) for stored in store.profiles)
    return (
        Item("Open Config Folder", open_config),
        Item("Wallpaper Configuration", open_editor),
        Item("Settings", open_settings),
        Item("Reload Profiles", reload_profiles),
        Separator(),
        Submenu("Profiles", profiles),
        Separator(),
        Item("Next Wallpaper", session.next),
        Check("Pause Timer", session.toggle_pause, checked=session.paused),
        Separator(),
        Item("About", about),
        Item("Exit", quit),
    )
