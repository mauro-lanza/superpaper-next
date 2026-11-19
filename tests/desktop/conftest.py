import subprocess
from pathlib import Path

import pytest

from superpaper.desktop import linux, process
from superpaper.desktop.kde import Activities
from superpaper.desktop.wallpaper import Spanned

IMAGE = "/tmp/wallpaper.png"
# Only KDE Plasma looks at activities.
NO_ACTIVITIES = Activities(current_profile=None, cached_pieces=lambda name: [], state_dir=Path("unused"))


@pytest.fixture
def ran(monkeypatch):
    """Record the host programs run; they all succeed unless a test says otherwise."""
    calls = []

    def run(command, **options):
        calls.append((list(command), options))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(process.subprocess, "run", run)
    return calls


def set_wallpaper(set_command="", image=IMAGE):
    return linux.set_wallpaper(Spanned(image), set_command=set_command, activities=NO_ACTIVITIES)
