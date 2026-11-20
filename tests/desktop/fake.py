from collections.abc import Sequence
from pathlib import Path

from superpaper.desktop.linux.kde import Activities
from superpaper.desktop.process import Result
from superpaper.desktop.wallpaper import Wallpaper


class FakeDesktop:
    """A Desktop that records what it is asked and answers as its fields say."""

    def __init__(self):
        self.pieces_taken = False
        self.wallpaper_kept = False
        self.problem: str | None = None
        self.span_answer = Result()
        self.answer = Result()
        self.hook_answer = Result()
        self.folder_answer = Result()
        self.spanned: list[str] = []
        self.handed: list[Wallpaper] = []
        self.activities: Activities | None = None
        self.hooks: list[tuple[Path, str, list[str]]] = []
        self.opened: list[Path] = []

    def takes_pieces(self, set_command: str) -> bool:
        return self.pieces_taken

    def keeps_wallpaper(self) -> bool:
        return self.wallpaper_kept

    def setter_problem(self, set_command: str) -> str | None:
        return self.problem

    def set_spanmode(self, set_command: str) -> Result:
        self.spanned.append(set_command)
        return self.span_answer

    def set_wallpaper(self, wallpaper: Wallpaper, *, set_command: str, activities: Activities) -> Result:
        self.handed.append(wallpaper)
        self.activities = activities
        return self.answer

    def run_hook(self, script: Path, image: str, sources: Sequence[str]) -> Result:
        self.hooks.append((script, image, list(sources)))
        return self.hook_answer

    def open_folder(self, folder: Path) -> Result:
        self.opened.append(folder)
        return self.folder_answer
