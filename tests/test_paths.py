"""Where Superpaper's files live: the overrides here, the per-OS defaults in tests/desktop."""

import os

import pytest

from superpaper import paths as paths_module
from superpaper.paths import AppPaths, ensure_dirs, install_dir, resolve_paths


def resolved(tmp_path, desktop, **environ):
    """resolve_paths for a scratch home and installation, as paths relative to tmp_path."""
    env = {"HOME": str(tmp_path / "home"), **{key: value.format(root=tmp_path) for key, value in environ.items()}}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(paths_module, "install_dir", lambda: tmp_path / "app")
        paths = resolve_paths(env, desktop)
    return {name: os.path.relpath(getattr(paths, name), tmp_path) for name in ("config", "profiles", "cache")}


def expected(config, cache):
    return {"config": config, "profiles": os.path.join(config, "profiles"), "cache": cache}


def test_the_directories_default_to_the_desktops(tmp_path, desktop):
    assert resolved(tmp_path, desktop) == expected("app/config", "app/cache")


def test_overrides_name_the_directories(tmp_path, desktop):
    paths = resolved(
        tmp_path,
        desktop,
        SUPERPAPER_CONFIG_HOME="{root}/mine/config",
        SUPERPAPER_CACHE_HOME="{root}/mine/cache",
        SNAP_USER_DATA="{root}/data",
    )

    assert paths == expected("mine/config", "mine/cache")


def test_overrides_are_independent(tmp_path, desktop):
    assert resolved(tmp_path, desktop, SUPERPAPER_CACHE_HOME="{root}/scratch") == expected("app/config", "scratch")
    assert resolved(tmp_path, desktop, SUPERPAPER_CONFIG_HOME="{root}/mine") == expected("mine", "app/cache")


def test_resolving_creates_nothing(tmp_path, desktop):
    resolved(tmp_path, desktop)

    assert list(tmp_path.iterdir()) == []


def app_paths_under(root):
    config = root / "home" / ".config" / "superpaper"
    return AppPaths(config=config, profiles=config / "profiles", cache=root / "home" / ".cache" / "superpaper" / "temp")


def test_first_run_creates_missing_parents_and_seeds_the_examples(tmp_path):
    paths = app_paths_under(tmp_path)

    ensure_dirs(paths)

    assert paths.cache.is_dir()
    examples = sorted(path.name for path in (install_dir() / "superpaper" / "resources" / "example_profiles").iterdir())
    assert examples
    assert sorted(path.name for path in paths.profiles.iterdir()) == examples


def test_an_existing_profiles_directory_is_left_alone(tmp_path):
    paths = app_paths_under(tmp_path)
    paths.profiles.mkdir(parents=True)

    ensure_dirs(paths)

    assert list(paths.profiles.iterdir()) == []
    assert paths.cache.is_dir()
