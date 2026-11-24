"""Where Superpaper's files live: the overrides here, the per-OS defaults in tests/desktop."""

import os

from superpaper.paths import AppPaths, ensure_dirs, install_dir, resolve_paths


def resolved(tmp_path, **environ):
    """resolve_paths with defaults app/config and app/cache, as paths relative to tmp_path."""
    env = {key: value.format(root=tmp_path) for key, value in environ.items()}
    paths = resolve_paths(env, (tmp_path / "app" / "config", tmp_path / "app" / "cache"))
    return {name: os.path.relpath(getattr(paths, name), tmp_path) for name in ("config", "profiles", "cache")}


def expected(config, cache):
    return {"config": config, "profiles": os.path.join(config, "profiles"), "cache": cache}


def test_the_directories_default_to_the_desktops(tmp_path):
    assert resolved(tmp_path) == expected("app/config", "app/cache")


def test_overrides_name_the_directories(tmp_path):
    paths = resolved(tmp_path, SUPERPAPER_CONFIG_HOME="{root}/mine/config", SUPERPAPER_CACHE_HOME="{root}/mine/cache")

    assert paths == expected("mine/config", "mine/cache")


def test_overrides_are_independent(tmp_path):
    assert resolved(tmp_path, SUPERPAPER_CACHE_HOME="{root}/scratch") == expected("app/config", "scratch")
    assert resolved(tmp_path, SUPERPAPER_CONFIG_HOME="{root}/mine") == expected("mine", "app/cache")


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
