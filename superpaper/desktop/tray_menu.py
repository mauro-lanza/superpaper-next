"""The tray menu as data: built by the wx tray, rendered by the wx menu and the native SNI menu."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


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
class Notice:
    """A disabled line of text."""

    label: str


@dataclass(frozen=True, slots=True)
class Separator:
    pass


@dataclass(frozen=True, slots=True)
class Submenu:
    label: str
    items: tuple[Item, ...]


MenuEntry = Item | Check | Notice | Separator | Submenu


class TrayHandle(Protocol):
    """A tray icon the desktop draws itself."""

    def remove(self) -> None: ...


MAX_REASON = 80


def failure_notice(reason: str) -> Notice:
    """The menu line for a wallpaper change that failed: the first line of ``reason``, cut short."""
    line = (reason.strip().splitlines() or [""])[0]
    if len(line) > MAX_REASON:
        line = line[: MAX_REASON - 1] + "…"
    return Notice(f"Last change failed: {line}")
