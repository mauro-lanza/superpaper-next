import os
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from tests.conftest import write_profile


def cli_subprocess_env(tmp_path):
    home = tmp_path / "home"
    config = tmp_path / "config"
    cache = tmp_path / "cache"
    home.mkdir(exist_ok=True)
    config.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(config), XDG_CACHE_HOME=str(cache))
    for name in ("DESKTOP_SESSION", "KDE_FULL_SESSION", "XDG_SESSION_DESKTOP", "SNAP_USER_DATA", "SNAP_USER_COMMON"):
        env.pop(name, None)
    return env


def run_module_cli(tmp_path, *args):
    script = (
        "import runpy, sys, types; "
        "spanmode = types.ModuleType('superpaper.spanmode'); "
        "spanmode.set_spanmode = lambda: None; "
        "sys.modules['superpaper.spanmode'] = spanmode; "
        f"sys.argv = {['superpaper', *args]!r}; "
        "runpy.run_module('superpaper', run_name='__main__')"
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=cli_subprocess_env(tmp_path),
    )


def test_import_cli_does_not_load_tray_or_gui(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import superpaper.cli; assert 'superpaper.tray' not in sys.modules; "
                "assert 'superpaper.gui' not in sys.modules; "
                "assert 'superpaper.configuration_dialogs' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=cli_subprocess_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr


def test_module_help_succeeds_headlessly(tmp_path):
    result = run_module_cli(tmp_path, "--help")

    assert result.returncode == 0
    assert "usage:" in result.stdout
    assert "--setimages" in result.stdout
    assert "--profile" in result.stdout


def test_module_unknown_argument_is_argparse_error(tmp_path):
    result = run_module_cli(tmp_path, "--unknown-option")

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


@pytest.mark.xfail(strict=True, reason="Known CLI bug: missing profiles currently exit with status 0")
def test_module_missing_profile_exits_nonzero(tmp_path):
    result = run_module_cli(tmp_path, "--profile", "missing")

    assert result.returncode != 0


def test_main_dispatches_cli_after_spanmode(monkeypatch):
    from superpaper import __main__ as entrypoint

    calls = []
    cli = ModuleType("superpaper.cli")
    cli.cli_logic = lambda: calls.append("cli")
    monkeypatch.setitem(sys.modules, "superpaper.cli", cli)
    monkeypatch.setattr(entrypoint, "set_spanmode", lambda: calls.append("spanmode"))
    monkeypatch.setattr(sys, "argv", ["superpaper", "--help"])

    entrypoint.main()

    assert calls == ["spanmode", "cli"]


def test_main_dispatches_tray_after_spanmode(monkeypatch):
    from superpaper import __main__ as entrypoint

    calls = []
    tray = ModuleType("superpaper.tray")
    tray.tray_loop = lambda: calls.append("tray")
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    monkeypatch.setattr(entrypoint, "set_spanmode", lambda: calls.append("spanmode"))
    monkeypatch.setattr(sys, "argv", ["superpaper"])

    entrypoint.main()

    assert calls == ["spanmode", "tray"]


def test_setimages_dispatches_one_shot_render(monkeypatch, tmp_path):
    from superpaper import cli

    image = tmp_path / "wallpaper.png"
    image.touch()
    captured = {}
    profile = object()

    class Job:
        joined = False

        def join(self):
            self.joined = True

    job = Job()

    def refresh():
        captured["refreshes"] = captured.get("refreshes", 0) + 1

    def profile_factory(files, advanced, perspective, groups, offsets):
        captured["profile_args"] = (files, advanced, perspective, groups, offsets)
        return profile

    def render(profile, force=False):
        captured["render"] = (profile, force)
        return job

    monkeypatch.setattr(sys, "argv", ["superpaper", "--setimages", str(image)])
    monkeypatch.setattr(cli, "CLIProfileData", profile_factory)
    monkeypatch.setattr(cli, "refresh_display_data", refresh)
    monkeypatch.setattr(cli, "change_wallpaper_job", render)

    assert cli.cli_logic() == 0
    assert captured["profile_args"] == ([str(image)], False, None, None, None)
    assert captured["render"] == (profile, True)
    assert captured["refreshes"] == 1
    assert job.joined is True


def test_advanced_cli_arguments_are_preserved(monkeypatch, tmp_path):
    from superpaper import cli

    image = tmp_path / "wallpaper.png"
    image.touch()
    captured = {}
    profile = object()
    display_system = SimpleNamespace(perspective_dict={"desk": object()})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "superpaper",
            "--setimages",
            str(image),
            "--advanced",
            "--perspective",
            "desk",
            "--spangroups",
            "0",
            "12",
            "--offsets",
            "1",
            "2",
        ],
    )
    monkeypatch.setattr(cli.wpproc, "G_ACTIVE_DISPLAYSYSTEM", display_system)
    monkeypatch.setattr(cli, "refresh_display_data", lambda: None)

    def profile_factory(*args):
        captured["profile_args"] = args
        return profile

    monkeypatch.setattr(cli, "CLIProfileData", profile_factory)
    monkeypatch.setattr(
        cli, "change_wallpaper_job", lambda rendered_profile, force: captured.update(render=(rendered_profile, force))
    )

    assert cli.cli_logic() == 0
    assert captured["profile_args"] == ([str(image)], True, "desk", [[0], [1, 2]], ["1", "2"])
    assert captured["render"] == (profile, True)


def test_cli_help_exits_successfully(monkeypatch):
    from superpaper import cli

    monkeypatch.setattr(sys, "argv", ["superpaper", "--help"])

    with pytest.raises(SystemExit) as error:
        cli.cli_logic()

    assert error.value.code == 0


def test_profile_launch_returns_after_tray_loop(monkeypatch, tmp_path):
    from superpaper import cli

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile_path = write_profile(profiles / "saved.profile")
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace("name=test", "name=saved"), encoding="utf-8"
    )
    tray = ModuleType("superpaper.tray")
    tray_calls = []
    tray.tray_loop = lambda profile=None: tray_calls.append(profile)
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    monkeypatch.setattr("superpaper.data.sp_paths.PROFILES_PATH", str(profiles))
    monkeypatch.setattr(cli.wpproc, "NUM_DISPLAYS", 2)
    monkeypatch.setattr(cli.wpproc, "RESOLUTION_ARRAY", [(1920, 1080), (1280, 1024)])
    monkeypatch.setattr(cli, "refresh_display_data", lambda: None)
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", "saved"])

    assert cli.cli_logic() == 0
    assert [profile_id.value for profile_id in tray_calls] == ["saved"]


@pytest.mark.parametrize("profile_name", ["../saved", "/tmp/saved", r"folder\saved"])
def test_profile_lookup_rejects_path_input(monkeypatch, tmp_path, profile_name):
    from superpaper import cli

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr("superpaper.data.sp_paths.PROFILES_PATH", str(profiles))
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", profile_name])

    with pytest.raises(SystemExit) as error:
        cli.cli_logic()

    assert error.value.code is None


def test_invalid_profile_id_fails_before_inventory_or_display_data(monkeypatch, tmp_path):
    from superpaper import cli

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "existing.profile").write_text("name=existing\n", encoding="utf-8")
    monkeypatch.setattr("superpaper.data.sp_paths.PROFILES_PATH", str(profiles))
    monkeypatch.setattr(cli.wpproc, "NUM_DISPLAYS", 0)
    monkeypatch.setattr(cli.wpproc, "RESOLUTION_ARRAY", [])
    monkeypatch.setattr(cli, "refresh_display_data", lambda: pytest.fail("display data was requested"))
    monkeypatch.setattr(cli, "discover_profile_inventory", lambda: pytest.fail("inventory was constructed"))
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", "../invalid"])

    with pytest.raises(SystemExit):
        cli.cli_logic()


def test_profile_lookup_accepts_valid_unicode(monkeypatch, tmp_path):
    from superpaper import cli

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    profile_path = write_profile(profiles / "Työ.profile")
    profile_path.write_text(profile_path.read_text(encoding="utf-8").replace("name=test", "name=Työ"), encoding="utf-8")
    tray = ModuleType("superpaper.tray")
    calls = []

    def tray_loop(profile=None):
        calls.append(profile)
        raise SystemExit

    tray.tray_loop = tray_loop
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    monkeypatch.setattr("superpaper.data.sp_paths.PROFILES_PATH", str(profiles))
    monkeypatch.setattr(cli.wpproc, "NUM_DISPLAYS", 2)
    monkeypatch.setattr(cli.wpproc, "RESOLUTION_ARRAY", [(1920, 1080), (1280, 1024)])
    monkeypatch.setattr(cli, "refresh_display_data", lambda: None)
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", "Työ"])

    with pytest.raises(SystemExit):
        cli.cli_logic()
    assert [profile_id.value for profile_id in calls] == ["Työ"]


@pytest.mark.parametrize("failure", ["mismatch", "symlink", "collision"])
def test_profile_lookup_rejects_undiscoverable_target(monkeypatch, tmp_path, failure):
    from superpaper import cli

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    saved = profiles / "saved.profile"
    if failure == "mismatch":
        saved.write_text("name=other\n", encoding="utf-8")
    elif failure == "symlink":
        target = tmp_path / "target.profile"
        target.write_text("name=saved\n", encoding="utf-8")
        saved.symlink_to(target)
    else:
        saved.write_text("name=saved\n", encoding="utf-8")
        (profiles / "Saved.profile").write_text("name=Saved\n", encoding="utf-8")
    tray = ModuleType("superpaper.tray")
    calls = []
    tray.tray_loop = lambda profile=None: calls.append(profile)
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    monkeypatch.setattr("superpaper.data.sp_paths.PROFILES_PATH", str(profiles))
    monkeypatch.setattr(cli.wpproc, "NUM_DISPLAYS", 2)
    monkeypatch.setattr(cli.wpproc, "RESOLUTION_ARRAY", [(1920, 1080), (1280, 1024)])
    monkeypatch.setattr(cli, "refresh_display_data", lambda: None)
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", "saved"])

    with pytest.raises(SystemExit):
        cli.cli_logic()

    assert calls == []


@pytest.mark.parametrize(
    "setting",
    ["delay=not-a-number", "ppi=0;0", "diagonal_inches=0;24", "zoom=", "align="],
)
def test_profile_lookup_rejects_malformed_content_before_tray(monkeypatch, tmp_path, setting):
    from superpaper import cli

    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "saved.profile").write_text(f"name=saved\n{setting}\n", encoding="utf-8")
    tray = ModuleType("superpaper.tray")
    calls = []
    tray.tray_loop = lambda profile=None: calls.append(profile)
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    monkeypatch.setattr("superpaper.data.sp_paths.PROFILES_PATH", str(profiles))
    monkeypatch.setattr(cli.wpproc, "NUM_DISPLAYS", 2)
    monkeypatch.setattr(cli.wpproc, "RESOLUTION_ARRAY", [(1920, 1080), (1280, 1024)])
    monkeypatch.setattr(cli, "refresh_display_data", lambda: None)
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", "saved"])

    with pytest.raises(SystemExit):
        cli.cli_logic()

    assert calls == []


@pytest.mark.xfail(strict=True, reason="Known CLI bug: validation failures currently exit with status 0")
def test_missing_image_exits_nonzero(monkeypatch, tmp_path):
    from superpaper import cli

    missing = tmp_path / "missing.png"
    monkeypatch.setattr(sys, "argv", ["superpaper", "--setimages", str(missing)])

    try:
        status = cli.cli_logic()
    except SystemExit as error:
        status = error.code

    assert isinstance(status, int)
    assert status != 0
