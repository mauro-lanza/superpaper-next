"""Where Superpaper keeps its files.

Importing this module touches nothing. ``resolve_paths`` works out the directories from
the environment and ``ensure_dirs`` creates them; the entry points call both before
doing any work, and hand the result to whatever needs a directory.
"""

import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from superpaper.desktop.backend import Desktop

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


def resolve_paths(environ: Mapping[str, str], desktop: Desktop) -> AppPaths:
    """Decide where Superpaper's files live: the OS's default directories, unless
    SUPERPAPER_CONFIG_HOME and SUPERPAPER_CACHE_HOME name them. Nothing is created."""
    config = environ.get(CONFIG_OVERRIDE)
    cache = environ.get(CACHE_OVERRIDE)
    default_config, default_cache = desktop.default_dirs(environ, install_dir())
    config_dir = Path(config) if config else default_config
    cache_dir = Path(cache) if cache else default_cache
    return AppPaths(config=config_dir, profiles=config_dir / "profiles", cache=cache_dir)


def ensure_dirs(paths: AppPaths) -> None:
    """Create Superpaper's directories. A new profiles directory gets the example profiles."""
    paths.config.mkdir(parents=True, exist_ok=True)
    paths.cache.mkdir(parents=True, exist_ok=True)
    if paths.profiles.is_dir():
        return
    paths.profiles.mkdir(parents=True)
    examples = resource("example_profiles")
    if examples.is_dir():
        for example in examples.iterdir():
            shutil.copy(example, paths.profiles)
