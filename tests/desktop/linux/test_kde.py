"""Setting the wallpaper on KDE Plasma, where each activity shows the profile named after it."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from superpaper.desktop import process
from superpaper.desktop.linux import kde
from superpaper.desktop.wallpaper import ProfileWallpapers

PIECES = ["/cache/home-a-crop-0.png", "/cache/home-a-crop-1.png"]
WORK_PIECES = ["/cache/work-b-crop-0.png", "/cache/work-b-crop-1.png"]
ACTIVITIES = {"act-home": "home", "act-work": "work", "act-play": "play"}


def declared(script, name):
    """The value ``script`` gives the JavaScript variable ``name``."""
    prefix = f"var {name} = "
    line = next(line for line in script.splitlines() if line.startswith(prefix))
    return json.loads(line.removeprefix(prefix).removesuffix(";"))


def urls(paths):
    return [Path(path).as_uri() for path in paths]


def running(profile, state_dir, cached=None):
    """KDE's view of Superpaper while ``profile`` runs; ``cached`` has other profiles' pieces."""
    cached = cached or {}
    return ProfileWallpapers(
        current_profile=profile, cached_pieces=lambda name: cached.get(name, []), state_dir=state_dir
    )


@pytest.fixture
def activity_manager(monkeypatch):
    """KDE's activity manager, as qdbus6 reports it, with "home" the current activity.

    A test makes a call fail by setting its answer to None, or to an exception to raise.
    """
    answers = {
        "ListActivities": "\n".join(ACTIVITIES),
        "CurrentActivity": "act-home",
        **{f"ActivityName {activity}": name for activity, name in ACTIVITIES.items()},
    }

    def run(command, **options):
        assert command[:3] == ["qdbus6", "org.kde.ActivityManager", "/ActivityManager/Activities"]
        answer = answers[" ".join(command[3:])]
        if isinstance(answer, BaseException):
            raise answer
        if answer is None:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="The name is not activatable\n")
        return subprocess.CompletedProcess(command, 0, stdout=answer + "\n", stderr="")

    monkeypatch.setattr(kde.shutil, "which", lambda program: f"/usr/bin/{program}" if program == "qdbus6" else None)
    monkeypatch.setattr(process.subprocess, "run", run)
    return answers


def test_each_activity_shows_the_profile_named_after_it(plasma, activity_manager, tmp_path):
    activities = running("home", tmp_path, cached={"work": WORK_PIECES})

    assert kde.set_wallpaper(PIECES, activities).ok

    # "play" has no wallpaper of its own yet, so it shows the new one.
    [script] = plasma.scripts
    assert declared(script, "imagesByDesktop") == {
        "1": urls(PIECES),
        "2": urls(PIECES),
        "3": urls(WORK_PIECES),
        "4": urls(WORK_PIECES),
        "5": urls(PIECES),
        "6": urls(PIECES),
    }
    assert declared(script, "defaultImages") is None
    # Plasma only tells which desktops the current activity has; the rest are guessed,
    # one per display for each other activity in turn, and remembered.
    remembered = json.loads((tmp_path / kde.MAPPING_FILE).read_text())
    assert remembered == {
        "1": "act-home",
        "2": "act-home",
        "3": "act-work",
        "4": "act-work",
        "5": "act-play",
        "6": "act-play",
    }


def test_a_remembered_desktop_keeps_its_activity(plasma, activity_manager, tmp_path):
    (tmp_path / kde.MAPPING_FILE).write_text(json.dumps({"3": "act-play", "4": "act-play"}))

    kde.set_wallpaper(PIECES, running("home", tmp_path, cached={"work": WORK_PIECES}))

    images = declared(plasma.scripts[0], "imagesByDesktop")
    assert [images[desktop] for desktop in ("3", "4", "5", "6")] == [urls(PIECES)] * 2 + [urls(WORK_PIECES)] * 2


@pytest.mark.parametrize("failure", [None, subprocess.TimeoutExpired("qdbus6", 5)])
def test_without_the_current_activity_the_remembered_desktops_are_used(plasma, activity_manager, tmp_path, failure):
    activity_manager["CurrentActivity"] = failure
    (tmp_path / kde.MAPPING_FILE).write_text(json.dumps({"1": "act-work", "2": "act-work"}))

    assert kde.set_wallpaper(PIECES, running("home", tmp_path, cached={"work": WORK_PIECES})).ok

    assert declared(plasma.scripts[0], "imagesByDesktop") == {"1": urls(WORK_PIECES), "2": urls(WORK_PIECES)}


def test_an_unreadable_memory_of_desktops_is_started_over(plasma, activity_manager, tmp_path):
    (tmp_path / kde.MAPPING_FILE).write_text("{not json")

    assert kde.set_wallpaper(PIECES, running("home", tmp_path)).ok

    assert len(json.loads((tmp_path / kde.MAPPING_FILE).read_text())) == 6


def test_without_activities_every_desktop_shows_the_new_wallpaper(plasma, activity_manager, tmp_path):
    activity_manager["ListActivities"] = None

    assert kde.set_wallpaper(PIECES, running("home", tmp_path)).ok

    [script] = plasma.scripts
    assert declared(script, "imagesByDesktop") == {}
    assert declared(script, "defaultImages") == urls(PIECES)
    assert not (tmp_path / kde.MAPPING_FILE).exists()


def test_a_wallpaper_plasma_refuses_is_reported_not_raised(plasma, activity_manager, tmp_path):
    plasma.failure = RuntimeError("org.freedesktop.DBus.Error.ServiceUnknown")

    result = kde.set_wallpaper(PIECES, running("home", tmp_path))

    assert result.problem == "Plasma did not take the wallpaper: org.freedesktop.DBus.Error.ServiceUnknown"


@pytest.mark.parametrize("with_activities", [False, True])
def test_without_dbus_python_the_reason_is_reported(monkeypatch, request, tmp_path, with_activities):
    if with_activities:
        request.getfixturevalue("activity_manager")
    else:
        monkeypatch.setattr(kde.shutil, "which", lambda program: None)
    monkeypatch.setitem(sys.modules, "dbus", None)

    result = kde.set_wallpaper(PIECES, running("home", tmp_path))

    assert "needs dbus-python" in result.problem


def test_image_paths_reach_plasma_as_data_not_code():
    awkward = '/home/me/it\'s "quoted" ${default_images}\\ and\nsplit.png'

    script = kde.wallpaper_script({7: [awkward]}, None)

    assert declared(script, "imagesByDesktop") == {"7": urls([awkward])}
    assert len(script.splitlines()) == len(kde.WALLPAPER_SCRIPT.template.splitlines())


def test_plasma_6_8_other_activities_keep_their_learned_desktops(plasma, activity_manager, tmp_path):
    # Two activities on two screens: every desktop keeps a screen, and desktop 9 is on a removed one.
    plasma.desktops = "1,0,1;2,1,1;24,0,0;25,1,0;9,2,0"
    (tmp_path / kde.MAPPING_FILE).write_text(json.dumps({"24": "act-work", "25": "act-work"}))

    desktops = kde.desktop_activities(tmp_path, "qdbus6", ["act-home", "act-work"])

    assert desktops[1] == desktops[2] == "act-home"
    assert desktops[24] == desktops[25] == "act-work"
    assert json.loads((tmp_path / kde.MAPPING_FILE).read_text())["24"] == "act-work"


def test_a_desktop_on_a_removed_screen_is_not_active(plasma, activity_manager, tmp_path):
    plasma.desktops = "1,0,1;9,2,0"

    desktops = kde.desktop_activities(tmp_path, "qdbus6", ["act-home"])

    assert desktops[1] == "act-home"
    assert 9 not in desktops


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the script")
def test_plasma_6_8_every_screen_gets_its_image_whatever_the_activity():
    fake_plasma = """
const screens = [{left: 0, top: 0}, {left: 1920, top: 0}];
const log = [];
const make = (id, screen) => ({id, screen, writeConfig: (key, value) => log.push([id, value]), reloadConfig() {}});
const all = [make(1, 0), make(2, 1), make(24, 0), make(25, 1), make(9, 2)];
globalThis.screenCount = 2;
globalThis.desktops = () => all;
globalThis.desktopForScreen = (i) => all[i];
globalThis.screenGeometry = (i) => screens[i];
"""
    program = fake_plasma + kde.wallpaper_script({}, ["/a.png", "/b.png"]) + "\nconsole.log(JSON.stringify(log));"

    output = subprocess.run(["node", "-e", program], capture_output=True, text=True, check=True).stdout

    assert json.loads(output) == [
        [1, "file:///a.png"],
        [2, "file:///b.png"],
        [24, "file:///a.png"],
        [25, "file:///b.png"],
    ]
