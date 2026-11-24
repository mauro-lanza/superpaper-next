"""The Linux wallpaper setters, the user's own command and the desktop facts around them."""

import os
import subprocess

import pytest

from superpaper.desktop import linux, process
from superpaper.desktop.linux import sni_tray
from superpaper.desktop.process import Result
from superpaper.desktop.wallpaper import Pieces, Spanned
from tests.desktop.conftest import IMAGE, NO_PROFILES, set_wallpaper

TRAY_ARGUMENTS = {
    "menu": lambda: (),
    "call_soon": lambda action: action(),
    "activate": lambda: None,
    "secondary_activate": lambda: None,
    "icon_path": "icon.png",
    "title": "Superpaper",
}


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


def default_dirs(tmp_path, **environ):
    """linux.default_dirs for a scratch home, as paths relative to tmp_path."""
    env = {"HOME": str(tmp_path / "home"), **{key: value.format(root=tmp_path) for key, value in environ.items()}}
    return tuple(os.path.relpath(path, tmp_path) for path in linux.default_dirs(env, tmp_path / "app"))


XDG_DEFAULT = ("home/.config/superpaper", "home/.cache/superpaper/temp")


def test_dirs_default_to_the_xdg_fallbacks_in_home(tmp_path):
    assert default_dirs(tmp_path) == XDG_DEFAULT


def test_dirs_use_xdg_directories_that_exist(tmp_path):
    (tmp_path / "xc").mkdir()
    (tmp_path / "xk").mkdir()

    assert default_dirs(tmp_path, XDG_CONFIG_HOME="{root}/xc", XDG_CACHE_HOME="{root}/xk") == (
        "xc/superpaper",
        "xk/superpaper/temp",
    )


@pytest.mark.parametrize("kind", ["missing", "file", "empty"])
def test_dirs_ignore_xdg_values_that_are_not_directories(tmp_path, kind):
    if kind == "file":
        (tmp_path / "xc").write_text("")
        (tmp_path / "xk").write_text("")
    value = "" if kind == "empty" else "{root}/x"

    assert default_dirs(
        tmp_path, XDG_CONFIG_HOME=value.replace("x", "xc"), XDG_CACHE_HOME=value.replace("x", "xk")
    ) == (XDG_DEFAULT)


def test_snap_uses_its_own_directories(tmp_path):
    assert default_dirs(tmp_path, SNAP_USER_DATA="{root}/data", SNAP_USER_COMMON="{root}/common") == (
        "data",
        "common/temp",
    )


def test_snap_config_and_cache_are_independent(tmp_path):
    assert default_dirs(tmp_path, SNAP_USER_DATA="{root}/data") == ("data", "home/.cache/superpaper/temp")


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


def test_kde_needs_the_wallpaper_cut_into_pieces(monkeypatch):
    monkeypatch.setenv("DESKTOP_SESSION", "plasma")
    shown = []
    monkeypatch.setattr(linux.kde, "set_wallpaper", lambda pieces, profiles: shown.append(pieces) or Result())

    uncut = linux.set_wallpaper(Spanned(IMAGE), set_command="", profiles=NO_PROFILES)
    cut = linux.set_wallpaper(Pieces(IMAGE, ("/a.png", "/b.png")), set_command="", profiles=NO_PROFILES)

    assert uncut.problem == "KDE Plasma needs the wallpaper cut into one image per display."
    assert cut.ok
    assert shown == [("/a.png", "/b.png")]


def test_the_setter_problem_is_the_unknown_desktop_unless_the_user_has_a_command(monkeypatch):
    monkeypatch.setenv("DESKTOP_SESSION", "unknown")

    assert linux.setter_problem("") == linux.UNKNOWN_DESKTOP
    assert linux.setter_problem("setter {image}") is None


def test_the_config_folder_opens_in_the_file_manager(ran, tmp_path):
    assert linux.open_folder(tmp_path).ok

    assert [command for command, _ in ran] == [["xdg-open", str(tmp_path)]]


def test_linux_keeps_no_wallpaper_across_restarts():
    assert linux.keeps_wallpaper() is False


@pytest.mark.parametrize(
    ("session", "set_command", "takes_pieces"),
    [("plasma", "", True), ("plasma", "setter {image}", False), ("gnome", "", False)],
)
def test_only_kde_takes_one_image_per_display(monkeypatch, session, set_command, takes_pieces):
    monkeypatch.setenv("DESKTOP_SESSION", session)

    assert linux.takes_pieces(set_command) is takes_pieces


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

    assert linux.set_spanmode("").ok

    assert [command for command, _ in ran] == [["/usr/bin/gsettings", "set", schema, "picture-options", "spanned"]]


@pytest.mark.parametrize("session", ["plasma", "xfce", "i3", None])
def test_span_mode_leaves_desktops_without_the_setting_alone(monkeypatch, ran, session):
    if session:
        monkeypatch.setenv("DESKTOP_SESSION", session)

    assert linux.set_spanmode("").ok

    assert ran == []


@pytest.mark.parametrize("set_command", ["setter {image}", "feh"])
def test_span_mode_leaves_the_desktop_alone_when_the_user_sets_the_wallpaper(monkeypatch, ran, set_command):
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")

    assert linux.set_spanmode(set_command).ok

    assert ran == []


def test_span_mode_reports_what_the_desktop_refused(monkeypatch):
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")
    monkeypatch.setattr(
        process.subprocess,
        "run",
        lambda command, **options: subprocess.CompletedProcess(command, 1, stdout="", stderr="no schema\n"),
    )

    result = linux.set_spanmode("")

    assert result.problem == "gsettings failed with exit status 1: no schema"


@pytest.mark.parametrize(("session", "on_kde"), [("plasma", True), ("kde", True), ("gnome", False)])
def test_kde_sessions_log_hotkey_problems_and_cannot_click_the_wx_tray(monkeypatch, session, on_kde):
    monkeypatch.setenv("DESKTOP_SESSION", session)

    assert linux.hotkey_problems_in_dialog() is not on_kde
    assert linux.wx_tray_clickable() is not on_kde


def test_no_native_tray_without_a_status_notifier_watcher(monkeypatch):
    monkeypatch.setattr(sni_tray, "sni_supported", lambda: False)
    monkeypatch.setattr(sni_tray, "build_tray", lambda **kwargs: pytest.fail("built a tray"))

    assert linux.make_tray(**TRAY_ARGUMENTS) is None


def test_the_native_tray_is_built_for_this_process_when_a_watcher_runs(monkeypatch):
    built = []
    native_tray = object()
    monkeypatch.setattr(sni_tray, "sni_supported", lambda: True)
    monkeypatch.setattr(sni_tray, "build_tray", lambda **kwargs: built.append(kwargs) or native_tray)

    assert linux.make_tray(**TRAY_ARGUMENTS) is native_tray
    assert built[0]["bus_name"] == f"org.kde.StatusNotifierItem-{os.getpid()}-1"
    assert built[0]["title"] == "Superpaper"
