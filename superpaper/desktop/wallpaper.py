"""What the desktop is handed: a spanned image, or that image cut into one piece per display."""

from dataclasses import dataclass


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
