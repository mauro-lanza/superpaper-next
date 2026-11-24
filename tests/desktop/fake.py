from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from superpaper.desktop.process import Result
from superpaper.desktop.tray_menu import MenuEntry, TrayHandle
from superpaper.desktop.wallpaper import ProfileWallpapers, Wallpaper


class FakeDesktop:
    """A Desktop that records what it is asked and answers as its fields say."""

    def __init__(self):
        self.pieces_taken = False
        self.native_tray = None
        self.wx_tray_is_clickable = True
        self.tray_requests: list[dict] = []
        self.main_loops_initialised = 0
        self.wallpaper_kept = False
        self.problem: str | None = None
        self.span_answer = Result()
        self.answer = Result()
        self.hook_answer = Result()
        self.folder_answer = Result()
        self.spanned: list[str] = []
        self.handed: list[Wallpaper] = []
        self.profiles: ProfileWallpapers | None = None
        self.hooks: list[tuple[Path, str, list[str]]] = []
        self.opened: list[Path] = []
        self.monitors: list = []
        self.watches_displays = True
        self.display_watchers: list[Callable[[], None]] = []

    def init_main_loop(self) -> None:
        self.main_loops_initialised += 1

    def make_tray(
        self,
        *,
        menu: Callable[[], tuple[MenuEntry, ...]],
        call_soon: Callable[[Callable[[], None]], None],
        activate: Callable[[], None],
        secondary_activate: Callable[[], None],
        icon_path: str,
        title: str,
    ) -> TrayHandle | None:
        self.tray_requests.append(
            {"menu": menu, "call_soon": call_soon, "activate": activate, "secondary_activate": secondary_activate}
        )
        return self.native_tray

    def wx_tray_clickable(self) -> bool:
        return self.wx_tray_is_clickable

    def takes_pieces(self, set_command: str) -> bool:
        return self.pieces_taken

    def keeps_wallpaper(self) -> bool:
        return self.wallpaper_kept

    def setter_problem(self, set_command: str) -> str | None:
        return self.problem

    def set_spanmode(self, set_command: str) -> Result:
        self.spanned.append(set_command)
        return self.span_answer

    def set_wallpaper(self, wallpaper: Wallpaper, *, set_command: str, profiles: ProfileWallpapers) -> Result:
        self.handed.append(wallpaper)
        self.profiles = profiles
        return self.answer

    def run_hook(self, script: Path, image: str, sources: Sequence[str]) -> Result:
        self.hooks.append((script, image, list(sources)))
        return self.hook_answer

    def open_folder(self, folder: Path) -> Result:
        self.opened.append(folder)
        return self.folder_answer

    def detect_monitors(self) -> list:
        return self.monitors

    def watch_displays(self, on_change: Callable[[], None]) -> bool:
        self.display_watchers.append(on_change)
        return self.watches_displays

    def change_displays(self) -> None:
        """The OS reports a display change, as often as it would."""
        for on_change in self.display_watchers:
            on_change()

    def default_dirs(self, environ: Mapping[str, str], install: Path) -> tuple[Path, Path]:
        return install / "config", install / "cache"

    def render_extension(self) -> str:
        return "png"

    def strict_profile_names(self) -> bool:
        return False
