from pathlib import Path

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
