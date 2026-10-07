"""Where Superpaper's files live.

The expected directories were recorded by running the import-time resolution that
``resolve_paths`` replaced (superpaper/sp_paths.py) for each of these environments.
"""

import os
import stat
import sys

import pytest

from superpaper.paths import AppPaths, ensure_dirs, install_dir, resolve_paths


def resolved(tmp_path, platform="linux", **environ):
    """resolve_paths for a scratch home and installation, as paths relative to tmp_path."""
    env = {"HOME": str(tmp_path / "home"), **{key: value.format(root=tmp_path) for key, value in environ.items()}}
    paths = resolve_paths(env, platform, install=tmp_path / "app")
    return {name: os.path.relpath(getattr(paths, name), tmp_path) for name in ("config", "profiles", "cache")}


def expected(config, cache):
    return {"config": config, "profiles": os.path.join(config, "profiles"), "cache": cache}


XDG_DEFAULT = expected("home/.config/superpaper", "home/.cache/superpaper/temp")


def test_linux_defaults_to_the_xdg_fallbacks_in_home(tmp_path):
    assert resolved(tmp_path) == XDG_DEFAULT


def test_linux_uses_xdg_directories_that_exist(tmp_path):
    (tmp_path / "xc").mkdir()
    (tmp_path / "xk").mkdir()

    paths = resolved(tmp_path, XDG_CONFIG_HOME="{root}/xc", XDG_CACHE_HOME="{root}/xk")

    assert paths == expected("xc/superpaper", "xk/superpaper/temp")


@pytest.mark.parametrize("kind", ["missing", "file", "empty"])
def test_linux_ignores_xdg_values_that_are_not_directories(tmp_path, kind):
    if kind == "file":
        (tmp_path / "xc").write_text("")
        (tmp_path / "xk").write_text("")
    value = "" if kind == "empty" else "{root}/x"

    paths = resolved(tmp_path, XDG_CONFIG_HOME=value.replace("x", "xc"), XDG_CACHE_HOME=value.replace("x", "xk"))

    assert paths == XDG_DEFAULT


def test_snap_uses_its_own_directories(tmp_path):
    paths = resolved(tmp_path, SNAP_USER_DATA="{root}/data", SNAP_USER_COMMON="{root}/common")

    assert paths == expected("data", "common/temp")


def test_snap_config_and_cache_are_independent(tmp_path):
    assert resolved(tmp_path, SNAP_USER_DATA="{root}/data") == expected("data", "home/.cache/superpaper/temp")


def test_windows_portable_install_keeps_files_beside_the_program(tmp_path):
    (tmp_path / "app").mkdir()

    assert resolved(tmp_path, "win32", LOCALAPPDATA="{root}/lad") == expected("app", "app/temp")
    assert sorted(os.listdir(tmp_path / "app")) == []  # the write probe cleans up


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs a directory this user can't write")
def test_windows_installed_program_uses_local_appdata(tmp_path):
    install = tmp_path / "app"
    install.mkdir()
    install.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        paths = resolved(tmp_path, "win32", LOCALAPPDATA="{root}/lad")
    finally:
        install.chmod(stat.S_IRWXU)

    assert paths == expected("lad/Superpaper", "lad/Superpaper/temp")


def test_macos_keeps_files_beside_the_program(tmp_path):
    assert resolved(tmp_path, "darwin") == expected("app", "app/temp")


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_overrides_name_the_directories(tmp_path, platform):
    paths = resolved(
        tmp_path,
        platform,
        SUPERPAPER_CONFIG_HOME="{root}/mine/config",
        SUPERPAPER_CACHE_HOME="{root}/mine/cache",
        SNAP_USER_DATA="{root}/data",
    )

    assert paths == expected("mine/config", "mine/cache")


def test_overrides_are_independent(tmp_path):
    assert resolved(tmp_path, SUPERPAPER_CACHE_HOME="{root}/scratch") == expected("home/.config/superpaper", "scratch")


def test_resolving_creates_nothing(tmp_path):
    resolved(tmp_path)

    assert list(tmp_path.iterdir()) == []


def app_paths_under(root):
    config = root / "home" / ".config" / "superpaper"
    return AppPaths(config=config, profiles=config / "profiles", cache=root / "home" / ".cache" / "superpaper" / "temp")


def test_first_run_creates_missing_parents_and_seeds_the_examples(tmp_path):
    paths = app_paths_under(tmp_path)

    ensure_dirs(paths)

    assert paths.cache.is_dir()
    examples = sorted(path.name for path in (install_dir() / "superpaper" / "profiles").iterdir())
    assert examples
    assert sorted(path.name for path in paths.profiles.iterdir()) == examples


def test_an_existing_profiles_directory_is_left_alone(tmp_path):
    paths = app_paths_under(tmp_path)
    paths.profiles.mkdir(parents=True)

    ensure_dirs(paths)

    assert list(paths.profiles.iterdir()) == []
    assert paths.cache.is_dir()
