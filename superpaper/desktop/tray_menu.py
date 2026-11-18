"""The tray menu as data: built by the wx tray, rendered by the wx menu and the native SNI menu."""

from collections.abc import Callable
from dataclasses import dataclass


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
