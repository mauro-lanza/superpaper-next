"""What every operating system module under desktop/ provides."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from superpaper.desktop.linux.kde import Activities
from superpaper.desktop.process import Result
from superpaper.desktop.wallpaper import Wallpaper


class Desktop(Protocol):
    """The OS interaction of one platform; each OS module satisfies it with module-level functions."""

    @staticmethod
    def takes_pieces(set_command: str) -> bool:
        """Whether the desktop sets one image per display, so a wallpaper is cut into pieces."""
        ...

    @staticmethod
    def keeps_wallpaper() -> bool:
        """Whether the desktop shows the last wallpaper again after a restart by itself."""
        ...

    @staticmethod
    def setter_problem(set_command: str) -> str | None:
        """Why Superpaper can't set the wallpaper on this desktop, if it can't."""
        ...

    @staticmethod
    def set_spanmode(set_command: str) -> Result:
        """Make the desktop span one wallpaper image across all displays, where that is a setting."""
        ...

    @staticmethod
    def set_wallpaper(wallpaper: Wallpaper, *, set_command: str, activities: Activities) -> Result:
        """Show ``wallpaper``: its pieces on desktops that take those, else its image."""
        ...

    @staticmethod
    def run_hook(script: Path, image: str, sources: Sequence[str]) -> Result:
        """Run the user's script after a wallpaper change."""
        ...

    @staticmethod
    def open_folder(folder: Path) -> Result:
        """Show ``folder`` in the desktop's file manager."""
        ...
