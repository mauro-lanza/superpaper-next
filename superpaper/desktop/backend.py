"""What every operating system module under desktop/ provides."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from superpaper.desktop.monitors import Monitor
from superpaper.desktop.process import Result
from superpaper.desktop.tray_menu import MenuEntry, TrayHandle
from superpaper.desktop.wallpaper import ProfileWallpapers, Wallpaper


class Desktop(Protocol):
    """The OS interaction of one platform; each OS module satisfies it with module-level functions."""

    @staticmethod
    def init_main_loop() -> None:
        """Prepare the process for the GUI's main loop; called before the wx application and any D-Bus connection exist."""
        ...

    @staticmethod
    def make_tray(
        *,
        menu: Callable[[], tuple[MenuEntry, ...]],
        call_soon: Callable[[Callable[[], None]], None],
        activate: Callable[[], None],
        secondary_activate: Callable[[], None],
        icon_path: str,
        title: str,
    ) -> TrayHandle | None:
        """A tray icon the desktop draws itself, whose menu actions run through ``call_soon``; None to use wx's."""
        ...

    @staticmethod
    def wx_tray_clickable() -> bool:
        """Whether wx's own tray icon can be clicked on this desktop."""
        ...

    @staticmethod
    def hotkey_problems_in_dialog() -> bool:
        """Whether a hotkey that can't be registered is shown to the user, rather than only logged."""
        ...

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
    def set_wallpaper(wallpaper: Wallpaper, *, set_command: str, profiles: ProfileWallpapers) -> Result:
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

    @staticmethod
    def detect_monitors() -> list[Monitor]:
        """The connected monitors, in pixels from the desktop's top-left corner, in any order; only on the main thread."""
        ...

    @staticmethod
    def watch_displays(on_change: Callable[[], None]) -> bool:
        """Call ``on_change()`` whenever the OS reports that displays were added, removed, resized or rearranged, on any thread; returns whether the OS does. Without it, the displays are detected again at manual Next."""
        ...

    @staticmethod
    def default_dirs(environ: Mapping[str, str], install: Path) -> tuple[Path, Path]:
        """Where this OS keeps Superpaper's files unless told otherwise: the config and the cache directory."""
        ...

    @staticmethod
    def hotkeys_by_default() -> bool:
        """Whether global hotkeys are on in a new installation's settings."""
        ...

    @staticmethod
    def render_extension() -> str:
        """The file extension, without the dot, of rendered wallpapers."""
        ...

    @staticmethod
    def strict_profile_names() -> bool:
        """Whether every existing profile name must follow the filename rules of this OS, not only new ones."""
        ...
