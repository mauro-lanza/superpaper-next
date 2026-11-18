import logging
import os
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from superpaper.cli import configure_logging
from superpaper.desktop.process import Result
from superpaper.settings import read_settings
from tests.conftest import write_profile

module_logger = logging.getLogger("superpaper.test_logging")


@pytest.fixture
def unconfigured_logging():
    yield
    configure_logging(debug=False)


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


@pytest.fixture(autouse=True)
def spanned(monkeypatch):
    """Record the set commands the desktop is told to span for, instead of changing the desktop."""
    from superpaper import cli

    commands = []
    monkeypatch.setattr(cli.desktop, "set_spanmode", lambda set_command: commands.append(set_command) or Result())
    return commands


def test_import_cli_does_not_load_tray_or_gui(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import superpaper.cli; "
                "assert not [name for name in sys.modules if name.startswith('superpaper.ui')], sys.modules"
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
        "import runpy, sys; "
        "sys.modules['wx'] = None; "
        "sys.argv = ['superpaper']; "
        "runpy.run_module('superpaper', run_name='__main__')"
    )
    env = cli_subprocess_env(tmp_path)

    result = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True, env=env)

    assert result.returncode == 1
    assert "need wxPython" in result.stderr


def fake_tray(monkeypatch):
    """Replace the wx tray with a recorder of what it was started with."""
    app = ModuleType("superpaper.ui.app")
    started = []
    app.run = lambda paths, settings, profile=None: started.append((paths, settings, profile))
    monkeypatch.setitem(sys.modules, "superpaper.ui.app", app)
    return started


def test_no_arguments_start_the_tray_after_spanning_the_desktop(monkeypatch, app_paths, spanned):
    from superpaper import cli
    from superpaper.settings import first_run_settings

    started = fake_tray(monkeypatch)

    assert cli.run([], app_paths) == 0

    assert started == [(app_paths, first_run_settings(sys.platform), None)]
    assert spanned == [""]


def test_the_tray_spans_the_desktop_for_the_saved_set_command(monkeypatch, app_paths, spanned):
    from superpaper import cli

    fake_tray(monkeypatch)
    (app_paths.config / "general_settings").write_text("set_command=setter {image}\n", encoding="utf-8")

    assert cli.run([], app_paths) == 0

    assert spanned == ["setter {image}"]


def test_a_desktop_that_cant_span_is_reported_and_the_tray_still_starts(monkeypatch, app_paths, caplog):
    from superpaper import cli

    started = fake_tray(monkeypatch)
    monkeypatch.setattr(cli.desktop, "set_spanmode", lambda set_command: Result("no registry"))

    assert cli.run([], app_paths) == 0

    assert len(started) == 1
    assert "Could not set the desktop to span the displays: no registry" in caplog.text


def test_first_tray_start_writes_the_default_settings(monkeypatch, app_paths):
    from superpaper import cli
    from superpaper.settings import first_run_settings, read_settings

    started = fake_tray(monkeypatch)

    assert cli.run([], app_paths) == 0

    defaults = first_run_settings(sys.platform)
    assert started == [(app_paths, defaults, None)]
    assert read_settings(app_paths.config / "general_settings", sys.platform) == defaults


def test_tray_logs_to_the_cache_when_logging_is_on(monkeypatch, app_paths):
    from superpaper import cli

    fake_tray(monkeypatch)
    settings_file = app_paths.config / "general_settings"
    settings_file.write_text("logging=true\n", encoding="utf-8")
    try:
        assert cli.run([], app_paths) == 0

        logging.getLogger("superpaper.test").info("from a module")
        assert "from a module" in (app_paths.cache / "log").read_text(encoding="utf-8")
        assert settings_file.read_text(encoding="utf-8") == "logging=true\n"
    finally:
        cli.configure_logging(debug=False)


def test_the_debug_flag_alone_starts_the_tray_with_logging(monkeypatch, app_paths):
    from superpaper import cli

    started = fake_tray(monkeypatch)
    try:
        assert cli.run(["--debug"], app_paths) == 0

        assert [profile for _, _, profile in started] == [None]
        assert logging.getLogger("superpaper.test").isEnabledFor(logging.INFO)
    finally:
        cli.configure_logging(debug=False)


def test_without_debugging_nothing_is_configured(unconfigured_logging):
    configure_logging(debug=False)

    assert not module_logger.isEnabledFor(logging.INFO)
    assert sys.excepthook is sys.__excepthook__


def test_debugging_logs_to_the_console(unconfigured_logging, capsys):
    configure_logging(debug=True)

    module_logger.info("from a module")

    assert module_logger.isEnabledFor(logging.INFO)
    assert capsys.readouterr().err == "from a module\n"


def test_a_log_file_also_records_uncaught_exceptions(unconfigured_logging, tmp_path):
    log_file = tmp_path / "log"
    configure_logging(debug=False, log_file=log_file)

    module_logger.info("started")
    message = "boom"
    try:
        raise ValueError(message)  # noqa: TRY301
    except ValueError:
        sys.excepthook(*sys.exc_info())

    log = log_file.read_text(encoding="utf-8")
    assert "started" in log
    assert "ValueError: boom" in log


def test_configuring_again_replaces_the_handlers(unconfigured_logging, tmp_path, capsys):
    log_file = tmp_path / "log"
    for _ in range(3):
        configure_logging(debug=True, log_file=log_file)

    module_logger.info("once")

    assert capsys.readouterr().err == "once\n"
    assert log_file.read_text(encoding="utf-8") == "once\n"


def test_reading_settings_with_logging_on_adds_no_handlers(unconfigured_logging, tmp_path, capsys):
    settings_file = tmp_path / "general_settings"
    settings_file.write_text("logging=true\n", encoding="utf-8")

    for _ in range(3):
        assert read_settings(settings_file, "linux").logging is True

    module_logger.info("not shown")
    assert not module_logger.isEnabledFor(logging.INFO)
    assert capsys.readouterr().err == ""


def test_setimages_dispatches_one_shot_render(monkeypatch, tmp_path, app_paths, spanned):
    from superpaper import cli
    from superpaper.geometry.perspective import Disabled
    from superpaper.profiles.profile_file import Profile

    image = tmp_path / "wallpaper.png"
    image.touch()
    captured = {}
    layout = SimpleNamespace(name="detected")

    def detect(config_dir):
        assert config_dir == app_paths.config
        captured["detections"] = captured.get("detections", 0) + 1
        return layout

    def show(profile, images, paths, *, layout, set_command):
        captured["render"] = (profile, images, paths, layout, set_command)

    monkeypatch.setattr(cli, "detect_layout", detect)
    monkeypatch.setattr(cli, "show", show)

    assert cli.run(["--setimages", str(image)], app_paths) == 0
    # One image spans the displays, without a perspective.
    draft = Profile(name="cli", slideshow=False, sources=((str(image),),), perspective=Disabled())
    assert captured["render"] == (draft, [str(image)], app_paths, layout, "")
    assert captured["detections"] == 1
    assert spanned == [""]


def test_a_wallpaper_that_cant_be_shown_exits_with_an_error(monkeypatch, tmp_path, app_paths):
    from superpaper import cli

    image = tmp_path / "wallpaper.png"
    image.touch()
    monkeypatch.setattr(cli, "detect_layout", lambda config_dir: SimpleNamespace())
    # The problem is logged where it happens.
    monkeypatch.setattr(cli, "show", lambda *args, **kwargs: f"The image {image} can't be opened.")

    assert cli.run(["--setimages", str(image)], app_paths) == 1


def test_advanced_cli_arguments_are_preserved(monkeypatch, tmp_path, app_paths, spanned):
    from superpaper import cli
    from superpaper.geometry.perspective import Named
    from superpaper.profiles.profile_file import Profile

    image = tmp_path / "wallpaper.png"
    image.touch()
    captured = {}
    layout = SimpleNamespace(perspective_names=lambda: ["desk"], size_hint=lambda: None)
    monkeypatch.setattr(cli, "detect_layout", lambda config_dir: layout)
    monkeypatch.setattr(
        cli,
        "show",
        lambda rendered_profile, images, paths, *, layout, set_command: captured.update(
            render=(rendered_profile, paths, layout, set_command)
        ),
    )

    argv = [
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
    ]
    assert cli.run(argv, app_paths) == 0
    draft = Profile(
        name="cli",
        spanmode="advanced",
        spangroups=((0,), (1, 2)),
        slideshow=False,
        sources=((str(image),),),
        perspective=Named("desk"),
        corrections=(("offsets", ((1, 2),)),),
    )
    # The layout that knows the perspective is the one the wallpaper is rendered for.
    assert captured["render"] == (draft, app_paths, layout, "setter {image}")
    # The desktop spans for the command the wallpaper is set with.
    assert spanned == ["setter {image}"]


def test_offsets_must_be_whole_numbers(tmp_path, app_paths):
    from superpaper import cli

    image = tmp_path / "wallpaper.png"
    image.touch()

    assert cli.run(["--setimages", str(image), "--advanced", "--offsets", "1", "x"], app_paths) == 1


def test_invalid_arguments_set_nothing_up(tmp_path):
    from superpaper import cli
    from superpaper.paths import AppPaths

    paths = AppPaths(config=tmp_path / "config", profiles=tmp_path / "config" / "profiles", cache=tmp_path / "cache")
    image = tmp_path / "wallpaper.png"
    image.touch()

    assert cli.run(["--setimages", str(image), "--offsets", "1"], paths) == 1
    assert list(tmp_path.iterdir()) == [image]


def test_the_custom_command_must_be_in_quotes(tmp_path, app_paths, caplog):
    from superpaper import cli

    image = tmp_path / "wallpaper.png"
    image.touch()

    assert cli.run(["--setimages", str(image), "--command", "setter", "{image}"], app_paths) == 1
    assert "Remember to put the custom command in quotes." in caplog.text


def test_spangroups_must_be_display_numbers(tmp_path, app_paths, caplog):
    from superpaper import cli

    image = tmp_path / "wallpaper.png"
    image.touch()

    assert cli.run(["--setimages", str(image), "--spangroups", "0x"], app_paths) == 1
    assert "One of the display ids was not an integer: 0x" in caplog.text


def test_a_desktop_without_a_setter_is_reported_before_displays_are_used(monkeypatch, tmp_path, app_paths, caplog):
    from superpaper import cli

    image = tmp_path / "wallpaper.png"
    image.touch()
    monkeypatch.setenv("DESKTOP_SESSION", "unknown")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(cli, "show", lambda *args, **kwargs: pytest.fail("rendered"))

    assert cli.run(["--setimages", str(image)], app_paths) == 1
    assert "can't set the wallpaper" in caplog.text


@pytest.mark.parametrize(("advanced", "hinted"), [(True, True), (False, False)])
def test_an_undetected_display_size_is_mentioned_when_spanning_by_size(
    monkeypatch, tmp_path, app_paths, caplog, advanced, hinted
):
    from superpaper import cli

    image = tmp_path / "wallpaper.png"
    image.touch()
    arguments = ["--setimages", str(image), "--command", "setter {image}"]
    monkeypatch.setattr(cli, "detect_layout", lambda config_dir: SimpleNamespace(size_hint=lambda: "Enter its size."))
    monkeypatch.setattr(cli, "show", lambda *args, **kwargs: None)

    assert cli.run([*arguments, "--advanced"] if advanced else arguments, app_paths) == 0
    assert ("Enter its size." in caplog.text) is hinted


def test_cli_help_exits_successfully(tmp_path):
    from superpaper import cli
    from superpaper.paths import AppPaths

    paths = AppPaths(config=tmp_path / "config", profiles=tmp_path / "config" / "profiles", cache=tmp_path / "cache")

    with pytest.raises(SystemExit) as error:
        cli.run(["--help"], paths)

    assert error.value.code == 0
    assert list(tmp_path.iterdir()) == []


def test_images_and_a_profile_together_are_refused(tmp_path, app_paths, caplog):
    from superpaper import cli

    image = tmp_path / "wallpaper.png"
    image.touch()

    assert cli.run(["--setimages", str(image), "--profile", "saved"], app_paths) == 1
    assert "Pass either image(s)" in caplog.text


def test_profile_launch_returns_after_the_tray_quits(monkeypatch, app_paths, spanned):
    from superpaper import cli

    profiles = app_paths.profiles
    profile_path = write_profile(profiles / "saved.profile")
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8").replace("name=test", "name=saved"), encoding="utf-8"
    )
    app = ModuleType("superpaper.ui.app")
    tray_calls = []
    app.run = lambda paths, settings, profile=None: tray_calls.append(profile)
    monkeypatch.setitem(sys.modules, "superpaper.ui.app", app)
    monkeypatch.setattr(cli, "detect_layout", lambda config_dir: None)

    assert cli.run(["--profile", "saved"], app_paths) == 0
    assert [profile_id.value for profile_id in tray_calls] == ["saved"]
    assert spanned == [""]


@pytest.mark.parametrize("profile_name", ["../saved", "/tmp/saved", r"folder\saved"])
def test_profile_lookup_rejects_path_input(app_paths, profile_name):
    from superpaper import cli

    assert cli.run(["--profile", profile_name], app_paths) == 1


def test_invalid_profile_id_fails_before_inventory_or_display_data(monkeypatch, app_paths):
    from superpaper import cli

    profiles = app_paths.profiles
    (profiles / "existing.profile").write_text("name=existing\n", encoding="utf-8")
    monkeypatch.setattr(cli, "detect_layout", lambda config_dir: pytest.fail("display data was requested"))
    monkeypatch.setattr(cli.profile_store, "discover", lambda paths: pytest.fail("inventory was constructed"))

    assert cli.run(["--profile", "../invalid"], app_paths) == 1


def test_profile_lookup_accepts_valid_unicode(monkeypatch, app_paths):
    from superpaper import cli

    profiles = app_paths.profiles
    profile_path = write_profile(profiles / "Työ.profile")
    profile_path.write_text(profile_path.read_text(encoding="utf-8").replace("name=test", "name=Työ"), encoding="utf-8")
    app = ModuleType("superpaper.ui.app")
    calls = []

    def run(paths, settings, profile=None):
        calls.append(profile)
        raise SystemExit

    app.run = run
    monkeypatch.setitem(sys.modules, "superpaper.ui.app", app)
    monkeypatch.setattr(cli, "detect_layout", lambda config_dir: None)

    with pytest.raises(SystemExit):
        cli.run(["--profile", "Työ"], app_paths)
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
    app = ModuleType("superpaper.ui.app")
    calls = []
    app.run = lambda paths, settings, profile=None: calls.append(profile)
    monkeypatch.setitem(sys.modules, "superpaper.ui.app", app)
    monkeypatch.setattr(cli, "detect_layout", lambda config_dir: None)

    assert cli.run(["--profile", "saved"], app_paths) == 0
    assert [profile_id.value for profile_id in calls] == ["saved"]


@pytest.mark.parametrize(
    "setting",
    ["delay=not-a-number", "diagonal_inches=0;24", "ppi=96.5"],
)
def test_profile_lookup_rejects_malformed_content_before_tray(monkeypatch, app_paths, setting):
    from superpaper import cli

    profiles = app_paths.profiles
    (profiles / "saved.profile").write_text(f"name=saved\n{setting}\n", encoding="utf-8")
    app = ModuleType("superpaper.ui.app")
    calls = []
    app.run = lambda paths, settings, profile=None: calls.append(profile)
    monkeypatch.setitem(sys.modules, "superpaper.ui.app", app)
    monkeypatch.setattr(cli, "detect_layout", lambda config_dir: None)

    assert cli.run(["--profile", "saved"], app_paths) == 1

    assert calls == []


def test_missing_image_exits_nonzero(tmp_path, app_paths):
    from superpaper import cli

    assert cli.run(["--setimages", str(tmp_path / "missing.png")], app_paths) == 1


@pytest.mark.parametrize(
    ("filename", "content", "named"),
    [
        (
            "{key}.persp",
            "[desk]\ncentral_disp = 0\nviewer_pos = 0,0\nswivels = 0,0,0,0\ntilts = 0,0,0\n",
            "perspective 'desk'",
        ),
        ("display_systems.dat", "[{key}]\nppi_norm_offsets = 0,0\n", "layout {key}"),
    ],
)
def test_a_corrupt_saved_layout_exits_with_a_message_naming_the_file(
    monkeypatch, tmp_path, app_paths, caplog, filename, content, named
):
    from superpaper import cli
    from superpaper.geometry import display_detection

    image = tmp_path / "wallpaper.png"
    image.touch()
    monitors = [SimpleNamespace(x=0, y=0, width=1920, height=1080, width_mm=527, height_mm=296, name="A")]
    monkeypatch.setattr(display_detection, "get_monitors", lambda: monitors)
    key = display_detection.detect_layout(tmp_path / "none").key
    (app_paths.config / filename.format(key=key)).write_text(content.format(key=key), encoding="utf-8")
    monkeypatch.setattr(cli, "show", lambda *args, **kwargs: pytest.fail("rendered"))

    with caplog.at_level(logging.ERROR):
        assert cli.run(["--setimages", str(image)], app_paths) == 1

    message = next(record.getMessage() for record in caplog.records if "could not be read" in record.getMessage())
    assert filename.format(key=key) in message
    assert named.format(key=key) in message
