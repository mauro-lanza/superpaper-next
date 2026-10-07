"""Where Superpaper keeps its files.

Importing this module touches nothing. ``resolve_paths`` works out the directories from
the environment and ``ensure_dirs`` creates them; the entry points call both before
doing any work, and hand the result to whatever needs a directory.
"""

import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path

# Name Superpaper's two directories outright, for a portable setup or a scratch run.
CONFIG_OVERRIDE = "SUPERPAPER_CONFIG_HOME"
CACHE_OVERRIDE = "SUPERPAPER_CACHE_HOME"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """The directories Superpaper reads and writes."""

    config: Path
    """general_settings, display_systems.dat, the .persp files and run-after-wp-change.py."""
    profiles: Path
    """The saved .profile files."""
    cache: Path
    """Rendered wallpapers, the log, running_profile and the remembered selections."""


@cache
def install_dir() -> Path:
    """The directory that holds the superpaper package; for a frozen build, the
    parent of the directory that holds the executable."""
    anchor = sys.executable if getattr(sys, "frozen", False) else __file__
    return Path(os.path.realpath(anchor)).parent.parent


def resource(name: str) -> Path:
    """A file shipped in superpaper/resources, such as the tray icon."""
    return install_dir() / "superpaper" / "resources" / name


def resolve_paths(environ: Mapping[str, str], platform: str, install: Path | None = None) -> AppPaths:
    """Decide where Superpaper's files live, exactly as earlier versions did.

    Linux follows the XDG base directories, or Snap's. Windows keeps everything beside
    a writable (portable) installation and in %LOCALAPPDATA%\\Superpaper otherwise;
    macOS keeps everything beside the installation. SUPERPAPER_CONFIG_HOME and
    SUPERPAPER_CACHE_HOME override the two directories. Nothing is created.
    """
    install = install_dir() if install is None else install
    config = environ.get(CONFIG_OVERRIDE)
    cache = environ.get(CACHE_OVERRIDE)
    config_dir = Path(config) if config else _default_config(environ, platform, install)
    cache_dir = Path(cache) if cache else _default_cache(environ, platform, install)
    return AppPaths(config=config_dir, profiles=config_dir / "profiles", cache=cache_dir)


def ensure_dirs(paths: AppPaths) -> None:
    """Create Superpaper's directories. A new profiles directory gets the example profiles."""
    paths.config.mkdir(parents=True, exist_ok=True)
    paths.cache.mkdir(parents=True, exist_ok=True)
    if paths.profiles.is_dir():
        return
    paths.profiles.mkdir(parents=True)
    examples = install_dir() / "superpaper" / "profiles"
    if examples.is_dir():
        for example in examples.iterdir():
            shutil.copy(example, paths.profiles)


def _default_config(environ: Mapping[str, str], platform: str, install: Path) -> Path:
    if platform == "linux":
        snap = environ.get("SNAP_USER_DATA")
        return Path(snap) if snap else _xdg_home(environ, "XDG_CONFIG_HOME", ".config") / "superpaper"
    return _beside_installation(environ, platform, install)


def _default_cache(environ: Mapping[str, str], platform: str, install: Path) -> Path:
    if platform == "linux":
        snap = environ.get("SNAP_USER_COMMON")
        base = Path(snap) if snap else _xdg_home(environ, "XDG_CACHE_HOME", ".cache") / "superpaper"
        return base / "temp"
    return _beside_installation(environ, platform, install) / "temp"


def _xdg_home(environ: Mapping[str, str], variable: str, fallback: str) -> Path:
    """An XDG base directory; one that is unset or isn't a directory falls back to ~/<fallback>."""
    value = environ.get(variable)
    if value and os.path.isdir(value):
        return Path(value)
    return Path(environ.get("HOME") or os.path.expanduser("~")) / fallback


def _beside_installation(environ: Mapping[str, str], platform: str, install: Path) -> Path:
    """A portable install keeps its files beside the program. An installed Windows program
    can't write there, so it uses %LOCALAPPDATA%\\Superpaper."""
    if platform == "win32" and not _writable(install):
        return Path(environ.get("LOCALAPPDATA") or install) / "Superpaper"
    return install


def _writable(directory: Path) -> bool:
    """Whether a directory can be created in ``directory``: os.access can't tell on Windows."""
    try:
        probe = tempfile.mkdtemp(dir=directory)
    except OSError:
        return False
    os.rmdir(probe)
    return True
