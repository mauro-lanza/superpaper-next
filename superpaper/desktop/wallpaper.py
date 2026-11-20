"""What the desktop is handed: a spanned image, or that image cut into one piece per display."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Spanned:
    """One image across all displays."""

    image: str


@dataclass(frozen=True, slots=True)
class Pieces:
    """``image`` cut into one piece per display, in Superpaper's display order."""

    image: str
    pieces: tuple[str, ...]


Wallpaper = Spanned | Pieces


@dataclass(frozen=True, slots=True)
class ProfileWallpapers:
    """What a desktop may need to show other profiles' wallpapers than the one being set."""

    current_profile: str | None
    """The running profile."""
    cached_pieces: Callable[[str], list[str]]
    """The per-display images last rendered for the profile of a given name, if any."""
    state_dir: Path
    """Where the desktop may keep state."""
