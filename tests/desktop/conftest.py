import inspect
import subprocess
from pathlib import Path

import pytest

from superpaper.desktop import linux, process
from superpaper.desktop.backend import Desktop
from superpaper.desktop.linux.kde import Activities
from superpaper.desktop.wallpaper import Spanned

IMAGE = "/tmp/wallpaper.png"
# Only KDE Plasma looks at activities.
NO_ACTIVITIES = Activities(current_profile=None, cached_pieces=lambda name: [], state_dir=Path("unused"))


def assert_satisfies_desktop(module):
    """Check ``module`` has every Desktop function, with the same parameters."""
    for name, member in vars(Desktop).items():
        if name.startswith("_") or not callable(member):
            continue
        expected = list(inspect.signature(member).parameters.values())
        actual = list(inspect.signature(getattr(module, name)).parameters.values())
        assert [(p.name, p.kind, p.annotation) for p in actual] == [(p.name, p.kind, p.annotation) for p in expected], (
            name
        )


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
