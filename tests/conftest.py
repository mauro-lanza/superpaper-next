from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch, tmp_path):
    config_home = tmp_path / "config"
    cache_home = tmp_path / "cache"
    config_home.mkdir()
    cache_home.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    for name in ("DESKTOP_SESSION", "KDE_FULL_SESSION", "XDG_SESSION_DESKTOP"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def profile_modules(monkeypatch):
    from superpaper import data
    from superpaper import wallpaper_processing as wpproc

    monkeypatch.setattr(wpproc, "NUM_DISPLAYS", 2)
    monkeypatch.setattr(wpproc, "RESOLUTION_ARRAY", [(1920, 1080), (1280, 1024)])
    monkeypatch.setattr(wpproc, "DISPLAY_OFFSET_ARRAY", [(0, 0), (1920, 0)])
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: None)
    return data, wpproc


def write_profile(path: Path, *, spanmode="single", sources=(), selected=()):
    lines = ["name=test", f"spanmode={spanmode}", "slideshow=false", "sortmode=alphabetical"]
    lines.extend(f"display{i}paths={source}" for i, source in enumerate(sources))
    if selected:
        lines.append("selected=" + ";".join(map(str, selected)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class ManualTimer:
    def __init__(self, clock, interval, callback):
        self.clock = clock
        self.interval = interval
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self, *, even_if_cancelled=False):
        if not self.cancelled or even_if_cancelled:
            self.callback()


class ManualClock:
    def __init__(self):
        self.timers = []

    def timer(self, interval, callback):
        timer = ManualTimer(self, interval, callback)
        self.timers.append(timer)
        return timer


@pytest.fixture
def manual_clock(monkeypatch):
    from superpaper import wallpaper_processing as wpproc

    clock = ManualClock()
    monkeypatch.setattr(wpproc, "Timer", clock.timer)
    return clock


@pytest.fixture
def slideshow_profile():
    return SimpleNamespace(name="slides", slideshow=True, delay_list=[12.5])
