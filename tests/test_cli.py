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
        # One fake monitor, so that runs on headless machines reach the code under test.
        "import screeninfo; "
        "screeninfo.get_monitors = lambda: [types.SimpleNamespace("
        "x=0, y=0, width=1920, height=1080, width_mm=527, height_mm=296, name='fake')]; "
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
    # Asking for help sets nothing up.
    assert list((tmp_path / "config").iterdir()) == []
    assert list((tmp_path / "cache").iterdir()) == []


def test_module_unknown_argument_is_argparse_error(tmp_path):
    result = run_module_cli(tmp_path, "--unknown-option")

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_module_missing_profile_exits_nonzero(tmp_path):
    result = run_module_cli(tmp_path, "--profile", "missing")

    assert result.returncode == 1
    assert "No profile was found by the given name: missing" in result.stderr


def test_missing_wxpython_is_explained(tmp_path):
    script = (
        "import runpy, sys, types; "
        "spanmode = types.ModuleType('superpaper.spanmode'); "
        "spanmode.set_spanmode = lambda: None; "
        "sys.modules['superpaper.spanmode'] = spanmode; "
        "sys.modules['wx'] = None; "
        "sys.argv = ['superpaper']; "
        "runpy.run_module('superpaper', run_name='__main__')"
    )
    env = cli_subprocess_env(tmp_path)

    result = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True, env=env)

    assert result.returncode == 1
    assert "need wxPython" in result.stderr


def test_main_leaves_span_mode_to_the_cli(monkeypatch):
    from superpaper import __main__ as entrypoint

    calls = []
    cli = ModuleType("superpaper.cli")
    cli.cli_logic = lambda paths: calls.append("cli")
    monkeypatch.setitem(sys.modules, "superpaper.cli", cli)
    monkeypatch.setattr(entrypoint, "set_spanmode", lambda: calls.append("spanmode"))
    monkeypatch.setattr(sys, "argv", ["superpaper", "--help"])

    entrypoint.main()

    assert calls == ["cli"]


def test_main_dispatches_tray_after_spanmode(monkeypatch):
    from superpaper import __main__ as entrypoint

    calls = []
    tray = ModuleType("superpaper.tray")
    tray.tray_loop = lambda paths, settings, profile=None: calls.append("tray")
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    monkeypatch.setattr(entrypoint, "set_spanmode", lambda: calls.append("spanmode"))
    monkeypatch.setattr(sys, "argv", ["superpaper"])

    entrypoint.main()

    assert calls == ["spanmode", "tray"]


def fake_tray(monkeypatch):
    """Replace the wx tray with a recorder of what it was started with."""
    tray = ModuleType("superpaper.tray")
    started = []
    tray.tray_loop = lambda paths, settings, profile=None: started.append((paths, settings, profile))
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    return started


def test_first_tray_start_writes_the_default_settings(monkeypatch, app_paths):
    from superpaper import cli
    from superpaper.settings import first_run_settings, read_settings

    started = fake_tray(monkeypatch)

    cli.start_tray(app_paths)

    defaults = first_run_settings(sys.platform)
    assert started == [(app_paths, defaults, None)]
    assert read_settings(app_paths.config / "general_settings", sys.platform) == defaults


def test_tray_logs_to_the_cache_when_logging_is_on(monkeypatch, app_paths):
    from superpaper import cli, sp_logging

    fake_tray(monkeypatch)
    settings_file = app_paths.config / "general_settings"
    settings_file.write_text("logging=true\n", encoding="utf-8")
    try:
        cli.start_tray(app_paths)

        files = [handler.baseFilename for handler in sp_logging.G_LOGGER.handlers if hasattr(handler, "baseFilename")]
        assert files == [str(app_paths.cache / "log")]
        assert sp_logging.DEBUG is True
        assert settings_file.read_text(encoding="utf-8") == "logging=true\n"
    finally:
        sp_logging.configure_logging(debug=False)


def test_setimages_dispatches_one_shot_render(monkeypatch, tmp_path, app_paths):
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

    def refresh(config_dir):
        assert config_dir == app_paths.config
        captured["refreshes"] = captured.get("refreshes", 0) + 1

    def profile_factory(files, advanced, perspective, groups, offsets):
        captured["profile_args"] = (files, advanced, perspective, groups, offsets)
        return profile

    def render(profile, paths, *, set_command, force):
        captured["render"] = (profile, paths, set_command, force)
        return job

    monkeypatch.setattr(sys, "argv", ["superpaper", "--setimages", str(image)])
    monkeypatch.setattr(cli, "CLIProfileData", profile_factory)
    monkeypatch.setattr(cli, "refresh_display_data", refresh)
    monkeypatch.setattr(cli, "change_wallpaper_job", render)

    assert cli.cli_logic(app_paths) == 0
    assert captured["profile_args"] == ([str(image)], False, None, None, None)
    assert captured["render"] == (profile, app_paths, "", True)
    assert captured["refreshes"] == 1
    assert job.joined is True


def test_advanced_cli_arguments_are_preserved(monkeypatch, tmp_path, app_paths):
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
            "--command",
            "setter {image}",
        ],
    )
    monkeypatch.setattr(cli, "refresh_display_data", lambda config_dir: display_system)

    def profile_factory(*args):
        captured["profile_args"] = args
        return profile

    monkeypatch.setattr(cli, "CLIProfileData", profile_factory)
    monkeypatch.setattr(
        cli,
        "change_wallpaper_job",
        lambda rendered_profile, paths, *, set_command, force: captured.update(
            render=(rendered_profile, paths, set_command, force)
        ),
    )

    assert cli.cli_logic(app_paths) == 0
    assert captured["profile_args"] == ([str(image)], True, "desk", [[0], [1, 2]], ["1", "2"])
    assert captured["render"] == (profile, app_paths, "setter {image}", True)


def test_cli_help_exits_successfully(monkeypatch, tmp_path):
    from superpaper import cli
    from superpaper.paths import AppPaths

    paths = AppPaths(config=tmp_path / "config", profiles=tmp_path / "config" / "profiles", cache=tmp_path / "cache")
    monkeypatch.setattr(sys, "argv", ["superpaper", "--help"])

    with pytest.raises(SystemExit) as error:
        cli.cli_logic(paths)

    assert error.value.code == 0
    assert list(tmp_path.iterdir()) == []


def test_profile_launch_returns_after_tray_loop(monkeypatch, app_paths):
    from superpaper import cli

    profiles = app_paths.profiles
    profile_path = write_profile(profiles / "saved.profile")
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace("name=test", "name=saved"), encoding="utf-8"
    )
    tray = ModuleType("superpaper.tray")
    tray_calls = []
    tray.tray_loop = lambda paths, settings, profile=None: tray_calls.append(profile)
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    monkeypatch.setattr(cli.wpproc, "NUM_DISPLAYS", 2)
    monkeypatch.setattr(cli.wpproc, "RESOLUTION_ARRAY", [(1920, 1080), (1280, 1024)])
    monkeypatch.setattr(cli, "refresh_display_data", lambda config_dir: None)
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", "saved"])

    assert cli.cli_logic(app_paths) == 0
    assert [profile_id.value for profile_id in tray_calls] == ["saved"]


@pytest.mark.parametrize("profile_name", ["../saved", "/tmp/saved", r"folder\saved"])
def test_profile_lookup_rejects_path_input(monkeypatch, app_paths, profile_name):
    from superpaper import cli

    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", profile_name])

    with pytest.raises(SystemExit) as error:
        cli.cli_logic(app_paths)

    assert error.value.code == 1


def test_invalid_profile_id_fails_before_inventory_or_display_data(monkeypatch, app_paths):
    from superpaper import cli

    profiles = app_paths.profiles
    (profiles / "existing.profile").write_text("name=existing\n", encoding="utf-8")
    monkeypatch.setattr(cli.wpproc, "NUM_DISPLAYS", 0)
    monkeypatch.setattr(cli.wpproc, "RESOLUTION_ARRAY", [])
    monkeypatch.setattr(cli, "refresh_display_data", lambda config_dir: pytest.fail("display data was requested"))
    monkeypatch.setattr(cli, "discover_profile_inventory", lambda paths: pytest.fail("inventory was constructed"))
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", "../invalid"])

    with pytest.raises(SystemExit):
        cli.cli_logic(app_paths)


def test_profile_lookup_accepts_valid_unicode(monkeypatch, app_paths):
    from superpaper import cli

    profiles = app_paths.profiles
    profile_path = write_profile(profiles / "Työ.profile")
    profile_path.write_text(profile_path.read_text(encoding="utf-8").replace("name=test", "name=Työ"), encoding="utf-8")
    tray = ModuleType("superpaper.tray")
    calls = []

    def tray_loop(paths, settings, profile=None):
        calls.append(profile)
        raise SystemExit

    tray.tray_loop = tray_loop
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    monkeypatch.setattr(cli.wpproc, "NUM_DISPLAYS", 2)
    monkeypatch.setattr(cli.wpproc, "RESOLUTION_ARRAY", [(1920, 1080), (1280, 1024)])
    monkeypatch.setattr(cli, "refresh_display_data", lambda config_dir: None)
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", "Työ"])

    with pytest.raises(SystemExit):
        cli.cli_logic(app_paths)
    assert [profile_id.value for profile_id in calls] == ["Työ"]


@pytest.mark.parametrize("variant", ["name line differs", "symlink", "case variant"])
def test_profile_launch_accepts_profiles_saved_by_older_versions(monkeypatch, tmp_path, app_paths, variant):
    from superpaper import cli

    profiles = app_paths.profiles
    saved = profiles / "saved.profile"
    if variant == "name line differs":
        saved.write_text("name=other\n", encoding="utf-8")
    elif variant == "symlink":
        target = tmp_path / "target.profile"
        target.write_text("name=saved\n", encoding="utf-8")
        saved.symlink_to(target)
    else:
        saved.write_text("name=saved\n", encoding="utf-8")
        (profiles / "Saved.profile").write_text("name=Saved\n", encoding="utf-8")
    tray = ModuleType("superpaper.tray")
    calls = []
    tray.tray_loop = lambda paths, settings, profile=None: calls.append(profile)
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    monkeypatch.setattr(cli.wpproc, "NUM_DISPLAYS", 2)
    monkeypatch.setattr(cli.wpproc, "RESOLUTION_ARRAY", [(1920, 1080), (1280, 1024)])
    monkeypatch.setattr(cli, "refresh_display_data", lambda config_dir: None)
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", "saved"])

    assert cli.cli_logic(app_paths) == 0
    assert [profile_id.value for profile_id in calls] == ["saved"]


@pytest.mark.parametrize(
    "setting",
    ["delay=not-a-number", "diagonal_inches=0;24", "zoom=", "align="],
)
def test_profile_lookup_rejects_malformed_content_before_tray(monkeypatch, app_paths, setting):
    from superpaper import cli

    profiles = app_paths.profiles
    (profiles / "saved.profile").write_text(f"name=saved\n{setting}\n", encoding="utf-8")
    tray = ModuleType("superpaper.tray")
    calls = []
    tray.tray_loop = lambda paths, settings, profile=None: calls.append(profile)
    monkeypatch.setitem(sys.modules, "superpaper.tray", tray)
    monkeypatch.setattr(cli.wpproc, "NUM_DISPLAYS", 2)
    monkeypatch.setattr(cli.wpproc, "RESOLUTION_ARRAY", [(1920, 1080), (1280, 1024)])
    monkeypatch.setattr(cli, "refresh_display_data", lambda config_dir: None)
    monkeypatch.setattr(sys, "argv", ["superpaper", "--profile", "saved"])

    with pytest.raises(SystemExit):
        cli.cli_logic(app_paths)

    assert calls == []


def test_missing_image_exits_nonzero(monkeypatch, tmp_path, app_paths):
    from superpaper import cli

    missing = tmp_path / "missing.png"
    monkeypatch.setattr(sys, "argv", ["superpaper", "--setimages", str(missing)])

    try:
        status = cli.cli_logic(app_paths)
    except SystemExit as error:
        status = error.code

    assert isinstance(status, int)
    assert status != 0
