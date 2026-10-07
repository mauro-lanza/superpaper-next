"""Handing the wallpaper to the desktop: the Linux setters, the user's own command, the
hook, and how host programs are run."""

import subprocess
from pathlib import Path

import pytest

import superpaper.desktop as desktop
from superpaper.desktop import linux, process
from superpaper.desktop.kde import Activities
from superpaper.desktop.spanmode import set_spanmode

IMAGE = "/tmp/wallpaper.png"
# Only KDE Plasma looks at activities.
NO_ACTIVITIES = Activities(current_profile=None, cached_pieces=lambda name: [], state_dir=Path("unused"))


@pytest.fixture
def ran(monkeypatch):
    """Record the host programs run; they all succeed unless a test says otherwise."""
    calls = []

    def run(command, **options):
        calls.append((list(command), options))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(process.subprocess, "run", run)
    return calls


def set_wallpaper(set_command="", image=IMAGE):
    return linux.set_wallpaper(image, None, set_command=set_command, activities=NO_ACTIVITIES)


def test_custom_command_runs_once_in_known_session(monkeypatch, ran):
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")

    result = set_wallpaper("setter --image {image}", image="/tmp/wallpaper with spaces.png")

    assert result.ok
    assert [command for command, _ in ran] == [["setter", "--image", "/tmp/wallpaper with spaces.png"]]
    assert ran[0][1]["env"] == process.host_spawn_env()


def test_custom_command_runs_once_in_unknown_session(monkeypatch, ran):
    monkeypatch.setenv("DESKTOP_SESSION", "unknown")

    assert set_wallpaper("setter {image}").ok

    assert [command for command, _ in ran] == [["setter", IMAGE]]
    assert "shell" not in ran[0][1]
    # The user's own program runs for as long as it needs.
    assert ran[0][1]["timeout"] is None


def test_feh_override_is_exclusive(monkeypatch, ran):
    monkeypatch.setenv("DESKTOP_SESSION", "i3")

    set_wallpaper("feh")

    assert [command for command, _ in ran] == [["feh", "--bg-scale", "--no-xinerama", IMAGE]]


def test_no_custom_command_preserves_native_dispatch(monkeypatch, ran):
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")

    set_wallpaper()

    assert [command for command, _ in ran] == [
        ["/usr/bin/gsettings", "set", "org.gnome.desktop.background", "picture-uri-dark", "file://" + IMAGE],
        ["/usr/bin/gsettings", "set", "org.gnome.desktop.background", "picture-uri", "file://" + IMAGE],
    ]
    assert all(options["timeout"] == process.QUICK for _, options in ran)


def test_gnome_without_a_dark_style_wallpaper_still_takes_the_wallpaper(monkeypatch):
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")

    def run(command, **options):
        if "picture-uri-dark" in command:  # GNOME before 42
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="No such key “picture-uri-dark”\n")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(process.subprocess, "run", run)

    assert set_wallpaper().ok


def test_an_unknown_desktop_is_reported_not_guessed(monkeypatch, ran):
    monkeypatch.setenv("DESKTOP_SESSION", "unknown")

    result = set_wallpaper()

    assert result.problem == linux.UNKNOWN_DESKTOP
    assert ran == []
    assert desktop.setter_problem("") == linux.UNKNOWN_DESKTOP
    assert desktop.setter_problem("setter {image}") is None


def test_a_custom_command_may_only_use_the_image_placeholder(monkeypatch, ran):
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")

    result = set_wallpaper("setter --colour={red} {image}")

    assert "{image}" in result.problem
    assert ran == []


def test_custom_command_receives_host_environment(monkeypatch, ran):
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")
    monkeypatch.setenv("SUPERPAPER_HOSTENV_XDG_DATA_DIRS", "/host/data")

    set_wallpaper("setter {image}")

    received_env = ran[0][1]["env"]
    assert received_env["XDG_DATA_DIRS"] == "/host/data"
    assert not any(key.startswith("SUPERPAPER_HOSTENV_") for key in received_env)


def test_lxqt_falls_back_to_pcmanfm_qt(monkeypatch, ran):
    monkeypatch.setenv("DESKTOP_SESSION", "lxqt")
    monkeypatch.setattr(
        linux.shutil, "which", lambda program: f"/usr/bin/{program}" if program == "pcmanfm-qt" else None
    )

    set_wallpaper()

    assert [command for command, _ in ran] == [["pcmanfm-qt", "-w", IMAGE]]


def test_xfce_sets_every_first_workspace_backdrop(monkeypatch, ran):
    monkeypatch.setenv("DESKTOP_SESSION", "xfce")
    listing = "/backdrop/screen0/monitor0/workspace0/last-image\n/backdrop/screen0/monitor0/workspace0/image-style\n"

    def run(command, **options):
        ran.append((list(command), options))
        return subprocess.CompletedProcess(command, 0, stdout=listing if "-l" in command else "", stderr="")

    monkeypatch.setattr(process.subprocess, "run", run)

    assert set_wallpaper().ok

    assert [command[-2:] for command, _ in ran[1:]] == [["-s", IMAGE], ["-s", "6"]]


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (FileNotFoundError("setter"), "setter is not installed."),
        (PermissionError(13, "Permission denied"), "setter could not be run: [Errno 13] Permission denied"),
        (subprocess.TimeoutExpired("setter", 30), "setter did not finish within 30 seconds."),
        (
            subprocess.CompletedProcess(["setter"], 2, stdout="", stderr="no such display\n"),
            "setter failed with exit status 2: no such display",
        ),
    ],
)
def test_a_failed_program_is_reported_not_raised(monkeypatch, failure, message):
    def run(command, **options):
        if isinstance(failure, BaseException):
            raise failure
        return failure

    monkeypatch.setattr(process.subprocess, "run", run)

    assert process.run(["/usr/bin/setter", IMAGE], timeout=30).problem == message


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

    set_spanmode()

    assert [command for command, _ in ran] == [["/usr/bin/gsettings", "set", schema, "picture-options", "spanned"]]


@pytest.mark.parametrize("session", ["plasma", "xfce", "i3", None])
def test_span_mode_leaves_desktops_without_the_setting_alone(monkeypatch, ran, session):
    if session:
        monkeypatch.setenv("DESKTOP_SESSION", session)

    set_spanmode()

    assert ran == []
