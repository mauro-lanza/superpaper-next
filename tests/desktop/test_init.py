"""What the desktop package decides for the platform: the span setting, the hook, the config folder."""

import subprocess

import pytest

import superpaper.desktop as desktop
from superpaper.desktop import linux, process
from tests.desktop.conftest import IMAGE


def test_the_setter_problem_is_the_unknown_desktop_unless_the_user_has_a_command(monkeypatch):
    monkeypatch.setenv("DESKTOP_SESSION", "unknown")

    assert desktop.setter_problem("") == linux.UNKNOWN_DESKTOP
    assert desktop.setter_problem("setter {image}") is None


def test_post_change_script_receives_each_source_as_an_argument(ran, tmp_path):
    script = tmp_path / "run-after-wp-change.py"

    assert desktop.run_hook(script, IMAGE, ["/a.png", "/b c.png"]).ok

    assert ran[-1][0] == ["python3", str(script), IMAGE, "/a.png", "/b c.png"]


def test_missing_python_for_the_post_change_script_is_reported_not_raised(monkeypatch, tmp_path):
    def run(command, **options):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(process.subprocess, "run", run)

    assert desktop.run_hook(tmp_path / "script.py", IMAGE, ["/a.png"]).problem == "python3 is not installed."


def test_the_config_folder_opens_in_the_file_manager(ran, tmp_path):
    assert desktop.open_folder(tmp_path).ok

    assert [command for command, _ in ran] == [["xdg-open", str(tmp_path)]]


@pytest.mark.parametrize(
    ("session", "set_command", "takes_pieces"),
    [("plasma", "", True), ("plasma", "setter {image}", False), ("gnome", "", False)],
)
def test_only_kde_takes_one_image_per_display(monkeypatch, session, set_command, takes_pieces):
    monkeypatch.setenv("DESKTOP_SESSION", session)

    assert desktop.takes_pieces(set_command) is takes_pieces


@pytest.mark.parametrize(
    ("session", "schema"),
    [
        ("zorin", "org.gnome.desktop.background"),
        ("cinnamon-wayland", "org.cinnamon.desktop.background"),
        ("mate", "org.mate.background"),
    ],
)
def test_span_mode_spans_one_image_across_the_displays(monkeypatch, ran, session, schema):
    monkeypatch.setenv("DESKTOP_SESSION", session)

    assert desktop.set_spanmode("").ok

    assert [command for command, _ in ran] == [["/usr/bin/gsettings", "set", schema, "picture-options", "spanned"]]


@pytest.mark.parametrize("session", ["plasma", "xfce", "i3", None])
def test_span_mode_leaves_desktops_without_the_setting_alone(monkeypatch, ran, session):
    if session:
        monkeypatch.setenv("DESKTOP_SESSION", session)

    assert desktop.set_spanmode("").ok

    assert ran == []


@pytest.mark.parametrize("set_command", ["setter {image}", "feh"])
def test_span_mode_leaves_the_desktop_alone_when_the_user_sets_the_wallpaper(monkeypatch, ran, set_command):
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")

    assert desktop.set_spanmode(set_command).ok

    assert ran == []


def test_span_mode_reports_what_the_desktop_refused(monkeypatch):
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")
    monkeypatch.setattr(
        process.subprocess,
        "run",
        lambda command, **options: subprocess.CompletedProcess(command, 1, stdout="", stderr="no schema\n"),
    )

    result = desktop.set_spanmode("")

    assert result.problem == "gsettings failed with exit status 1: no schema"
