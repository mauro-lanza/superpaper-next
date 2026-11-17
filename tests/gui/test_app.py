import subprocess
import sys
import time
from dataclasses import replace

import pytest

import superpaper.desktop.process as process
from superpaper.desktop.linux import UNKNOWN_DESKTOP
from superpaper.displays import SIZE_HINT
from superpaper.paths import ensure_dirs, resolve_paths
from superpaper.profile_id import ProfileId
from superpaper.settings import read_settings
from tests.conftest import monitor


def slideshow_armed(superpaper):
    return superpaper.session._deadline is not None


def test_first_run_seeds_the_example_profiles(gui_env, tmp_path):
    environ = {
        "SUPERPAPER_CONFIG_HOME": str(tmp_path / "fresh" / "config"),
        "SUPERPAPER_CACHE_HOME": str(tmp_path / "fresh" / "cache"),
    }
    paths = resolve_paths(environ, sys.platform)
    ensure_dirs(paths)
    assert sorted(path.name for path in paths.profiles.iterdir()) == ["example.profile", "example_multi.profile"]


def test_tray_starts_with_nothing_running_and_hotkeys_off(superpaper):
    assert superpaper.session.running is None
    assert superpaper.hotkeys is None


def test_tray_asks_once_about_a_profile_that_cant_be_loaded_and_yes_deletes_it(gui_env):
    superpaper = gui_env.start()
    asked = [dialog for dialog in gui_env.shown() if "Broken.profile" in dialog[2]]
    assert asked == [("app", "Error", "There was an error when loading profile 'Broken.profile'.")]
    assert not gui_env.profile_file("Broken").exists()
    assert gui_env.saved(superpaper, "Broken") is None


def test_work_runs_as_a_slideshow(running_work):
    assert running_work.session.running.profile.name == "Work"
    assert slideshow_armed(running_work)


def test_the_render_and_the_running_pointer_are_in_the_cache_directory(gui_env, running_work):
    cache = gui_env.paths.cache
    assert (cache / "Work-a.png").is_file()
    assert (cache / "running_profile").read_text() == "Work"


def test_the_custom_command_from_the_settings_set_the_wallpaper(gui_env, running_work):
    assert ["true", str(gui_env.paths.cache / "Work-a.png")] in gui_env.commands


def test_starting_another_profile_while_paused_runs_it(gui_env, running_work):
    running_work.tray.pause_timer(None)
    gui_env.settle(running_work)
    gui_env.start_profile(running_work, "Home")
    assert running_work.session.running.profile.name == "Home"
    assert not running_work.tray.is_paused


def test_a_profile_runs_again_unpaused_after_another_one_ran_while_paused(gui_env, running_work):
    running_work.tray.pause_timer(None)
    gui_env.settle(running_work)
    gui_env.start_profile(running_work, "Home")
    gui_env.start_profile(running_work, "Work")
    assert running_work.session.running.profile.name == "Work"
    assert slideshow_armed(running_work)


def test_open_config_folder_runs_xdg_open_and_reports_its_failure(gui_env, superpaper, monkeypatch):
    opened = []

    def failing_xdg_open(command, **options):
        opened.append(list(command))
        return subprocess.CompletedProcess(command, 4, stdout=None, stderr="no file manager\n")

    gui_env.shown()
    monkeypatch.setattr(process.subprocess, "run", failing_xdg_open)
    superpaper.tray.open_config(None)
    assert opened == [["xdg-open", str(gui_env.paths.config)]]
    assert gui_env.shown() == [("tray", "Info", "There was an error trying to open the config folder.")]


def test_an_unknown_desktop_is_reported_once_at_startup_and_nothing_is_run(gui_env, monkeypatch):
    gui_env.profile_file("Broken").unlink()
    first = gui_env.start()
    gui_env.start_profile(first, "Work")
    gui_env.quit(first)
    gui_env.shown()
    gui_env.commands.clear()
    monkeypatch.setenv("DESKTOP_SESSION", "unknown")
    no_command = replace(read_settings(gui_env.settings_path, sys.platform), set_command="")
    second = gui_env.start(settings=no_command)
    gui_env.settle(second)
    assert gui_env.shown() == [("app", "Error", UNKNOWN_DESKTOP)]
    assert gui_env.commands == []


def test_undetected_display_sizes_are_mentioned_once_at_startup(gui_env, monkeypatch):
    gui_env.profile_file("Broken").unlink()
    without_sizes = [monitor(0, 0, 1920, 1080, None, None), monitor(1920, 0, 1280, 1024, None, None)]
    monkeypatch.setattr("superpaper.displays.get_monitors", lambda: without_sizes)
    superpaper = gui_env.start()
    gui_env.settle(superpaper)
    assert gui_env.shown() == [("app", "Info", SIZE_HINT)]


@pytest.fixture
def restarted_after_sweep(gui_env):
    """Superpaper started again after Work ran and left a stale cache behind."""
    first = gui_env.start()
    gui_env.start_profile(first, "Work")
    gui_env.quit(first)
    cache = gui_env.paths.cache
    for render_file in cache.glob("Work-*.png"):
        render_file.unlink()
    for name in ("Gone-a.png", "Gone-a-crop-0.png", "notes.txt"):
        (cache / name).write_bytes(b"")
    (cache / "selections" / "Gone.json").write_text("[]", encoding="utf-8")
    second = gui_env.start()
    gui_env.settle(second)
    return second


def test_startup_sweeps_the_renders_of_a_profile_that_is_gone_and_nothing_else(gui_env, restarted_after_sweep):
    top_level = sorted(path.name for path in gui_env.paths.cache.iterdir())
    assert "Gone-a.png" not in top_level
    assert "Gone-a-crop-0.png" not in top_level
    assert "notes.txt" in top_level


def test_startup_renders_the_running_profile_when_it_has_no_render_to_show_again(gui_env, restarted_after_sweep):
    assert any(gui_env.paths.cache.glob("Work-?.png"))


def test_startup_forgets_the_selection_of_a_profile_that_is_gone_and_keeps_the_running_ones(
    gui_env, restarted_after_sweep
):
    selections = sorted(path.name for path in (gui_env.paths.cache / "selections").iterdir())
    assert "Gone.json" not in selections
    assert "Work.json" in selections


def test_a_start_with_a_profile_runs_it_and_remembers_it(gui_env):
    superpaper = gui_env.start(startup_profile=ProfileId("Home"))
    gui_env.settle(superpaper)
    assert superpaper.session.running.profile.name == "Home"
    assert (gui_env.paths.cache / "running_profile").read_text(encoding="utf-8") == "Home"


def test_quitting_doesnt_wait_when_nothing_is_under_way(gui_env, superpaper):
    started = time.monotonic()
    gui_env.quit(superpaper)
    assert time.monotonic() - started < 1
