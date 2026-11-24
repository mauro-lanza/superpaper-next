"""Set the wallpaper on KDE Plasma: one image per display, through Plasma's scripting
interface over D-Bus, with each activity showing the profile named after it."""

import json
import logging
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from string import Template
from typing import Any

from superpaper.desktop.process import Result, run
from superpaper.desktop.wallpaper import ProfileWallpapers
from superpaper.files import write_atomically

logger = logging.getLogger(__name__)

# Which desktop belongs to which activity, as learned so far (Plasma only tells for the
# current activity). Kept in the config directory.
MAPPING_FILE = "kde_desktop_mapping.json"

# Seconds an activity manager query may take.
ACTIVITY_MANAGER_TIMEOUT = 5

# Lists every desktop as "id,screen,current;". "current" is 1 for the desktop the current
# activity shows on a screen that exists. Since Plasma 6.8 a desktop of another activity
# keeps its screen, as does one of a removed screen (an index past screenCount); before
# that, a desktop of an activity that isn't showing is on screen -1.
DESKTOPS_SCRIPT = """
var allDesktops = desktops();
var result = [];
for(var i = 0; i < allDesktops.length; i++) {
    var screen = allDesktops[i].screen;
    var shown = screen >= 0 && screen < screenCount ? desktopForScreen(screen) : null;
    var isCurrent = shown && shown.id == allDesktops[i].id ? 1 : 0;
    result.push(allDesktops[i].id + ',' + screen + ',' + isCurrent);
}
print(result.join(';'));
"""

# Gives each desktop the image for its screen. The screens the current activity shows a
# desktop on, sorted by their left and then top edge, order the screens the way Superpaper
# orders the displays. A desktop on no screen (-1), of an activity that isn't showing, is
# guessed to be on the screen its position in the list suggests; one on a screen that no
# longer exists is left alone.
WALLPAPER_SCRIPT = Template("""
var imagesByDesktop = ${images_by_desktop};
var defaultImages = ${default_images};

var allDesktops = desktops();

var screenOrder = [];
for(var i = 0; i < screenCount; i++) {
    if(desktopForScreen(i)) {
        screenOrder.push(i);
    }
}
screenOrder.sort(function(a, b) {
    var ga = screenGeometry(a);
    var gb = screenGeometry(b);
    return (ga.left - gb.left) || (ga.top - gb.top);
});

for(var idx = 0; idx < allDesktops.length; idx++) {
    var desktop = allDesktops[idx];
    var imageArray = imagesByDesktop[desktop.id] || defaultImages;
    if(!imageArray) {
        continue;
    }
    var screenId = desktop.screen;
    if(screenId == -1 && screenOrder.length > 0) {
        screenId = screenOrder[idx % screenOrder.length];
    }
    var imageIndex = screenOrder.indexOf(screenId);
    if(imageIndex >= 0 && imageIndex < imageArray.length) {
        desktop.wallpaperPlugin = "org.kde.image";
        desktop.currentConfigGroup = Array("Wallpaper", "org.kde.image", "General");
        desktop.writeConfig("Image", imageArray[imageIndex]);
    }
}

for(var idx = 0; idx < allDesktops.length; idx++) {
    allDesktops[idx].reloadConfig();
}
""")


class PlasmaScriptingUnavailable(RuntimeError):
    """dbus-python, which KDE wallpaper scripting needs, is not installed."""


def set_wallpaper(pieces: Sequence[str], profiles: ProfileWallpapers) -> Result:
    """Show ``pieces``, one image per display in Superpaper's display order.

    With activities, each activity shows the last wallpaper of the profile named after
    it, or else ``pieces``, which the running profile's activity always gets.
    """
    try:
        return _show(pieces, profiles)
    except PlasmaScriptingUnavailable as error:
        return Result(str(error))


def _show(pieces: Sequence[str], profiles: ProfileWallpapers) -> Result:
    listed = _list_activities()
    if listed is None:
        return _evaluate(wallpaper_script({}, pieces))
    qdbus, activity_ids = listed
    names = activity_names(qdbus, activity_ids)
    if not names:
        return _evaluate(wallpaper_script({}, pieces))
    images = {activity: _activity_images(name, pieces, profiles) for activity, name in names.items()}
    desktops = desktop_activities(profiles.state_dir, qdbus, activity_ids)
    if not desktops:
        return Result("Failed to get desktop-activity mapping, cannot set wallpapers")
    by_desktop = {desktop: images[activity] for desktop, activity in desktops.items() if activity in images}
    return _evaluate(wallpaper_script(by_desktop, None))


def wallpaper_script(images_by_desktop: Mapping[int, Sequence[str]], default_images: Sequence[str] | None) -> str:
    """The Plasma script that gives each desktop its images, or ``default_images``."""
    by_desktop = {str(desktop): _file_urls(images) for desktop, images in images_by_desktop.items()}
    default = None if default_images is None else _file_urls(default_images)
    return WALLPAPER_SCRIPT.substitute(images_by_desktop=json.dumps(by_desktop), default_images=json.dumps(default))


def activity_names(qdbus: str, activity_ids: Sequence[str]) -> dict[str, str]:
    """The KDE activities, id to name."""
    names = {}
    for activity_id in activity_ids:
        named = _activity_manager(qdbus, "ActivityName", activity_id)
        if named.ok:
            names[activity_id] = named.output.strip()
    logger.info("KDE Activities found: %s", names)
    return names


def desktop_activities(state_dir: Path, qdbus: str, activity_ids: Sequence[str]) -> dict[int, str]:
    """Which activity each Plasma desktop belongs to, desktop id to activity id.

    Plasma only tells which desktops belong to the current activity, so what was learned
    before is remembered in ``state_dir``, and desktops never seen are guessed: the
    other activities' desktops are taken to follow each other, one per screen.
    """
    remembered = _load_mapping(state_dir)
    current = _activity_manager(qdbus, "CurrentActivity")
    current_activity_id = current.output.strip() if current.ok else None
    plasma_shell = _plasma_shell()
    try:
        desktop_info = plasma_shell.evaluateScript(DESKTOPS_SCRIPT)
        logger.info("Desktop info from plasma: %s", desktop_info)
        all_desktop_ids, active_desktop_ids = _parse_desktops(desktop_info or "")
    except Exception:  # Plasma answered something else
        logger.exception("Failed to get desktop-activity mapping")
        return {}
    if not active_desktop_ids or not current_activity_id:
        logger.error("Could not determine active desktops or current activity")
        return remembered

    learned = _assign_activities(remembered, all_desktop_ids, active_desktop_ids, current_activity_id, activity_ids)
    if learned != remembered:
        _save_mapping(state_dir, learned)
    logger.info("Current activity: %s", current_activity_id)
    logger.info("Active desktops: %s", active_desktop_ids)
    logger.info("Desktop to activity mapping: %s", learned)
    return learned


def _parse_desktops(desktop_info: str) -> tuple[list[int], list[int]]:
    """The ids of all desktops and of those the current activity shows, from DESKTOPS_SCRIPT's answer."""
    all_ids = []
    active_ids = []
    for item in desktop_info.split(";"):
        if "," not in item:
            continue
        desktop_id, _, is_current = (int(part) for part in item.split(","))
        all_ids.append(desktop_id)
        if is_current:
            active_ids.append(desktop_id)
    return all_ids, active_ids


def _assign_activities(
    remembered: Mapping[int, str],
    all_ids: Sequence[int],
    active_ids: Sequence[int],
    current_activity_id: str,
    activity_ids: Sequence[str],
) -> dict[int, str]:
    """``remembered`` plus the desktops on screen now, which belong to the current
    activity, plus a guess for the ones never seen."""
    mapping = dict(remembered)
    for desktop_id in active_ids:
        mapping[desktop_id] = current_activity_id
    if len(activity_ids) < 2:
        return mapping
    unmapped_ids = [desktop_id for desktop_id in all_ids if desktop_id not in mapping]
    other_activities = [activity for activity in activity_ids if activity != current_activity_id]
    for position, desktop_id in enumerate(unmapped_ids):
        activity_position = position // len(active_ids)
        if activity_position < len(other_activities):
            mapping[desktop_id] = other_activities[activity_position]
    return mapping


def _activity_images(name: str, pieces: Sequence[str], profiles: ProfileWallpapers) -> list[str]:
    if profiles.current_profile and name == profiles.current_profile:
        logger.info("Activity '%s' matched profile '%s'", name, profiles.current_profile)
        return list(pieces)
    cached = profiles.cached_pieces(name)
    if cached:
        logger.info("Activity '%s' using cached wallpapers from profile '%s'", name, name)
        return cached
    logger.info("Activity '%s' using fallback wallpapers from profile '%s'", name, profiles.current_profile)
    return list(pieces)


def _file_urls(paths: Sequence[str]) -> list[str]:
    return [Path(path).absolute().as_uri() for path in paths]


def _evaluate(script: str) -> Result:
    try:
        _plasma_shell().evaluateScript(script)
    except PlasmaScriptingUnavailable:
        raise
    except Exception as error:  # D-Bus failures come in many types
        return Result(f"Plasma did not take the wallpaper: {error}")
    return Result()


def _list_activities() -> tuple[str, list[str]] | None:
    """The qdbus command and the ids of the KDE activities; None when they can't be listed."""
    qdbus = _qdbus()
    if not qdbus:
        logger.error("Neither qdbus6 nor qdbus found")
        return None
    listed = _activity_manager(qdbus, "ListActivities")
    if not listed.ok:
        return None
    return qdbus, [line.strip() for line in listed.output.splitlines() if line.strip()]


def _qdbus() -> str | None:
    """The available qdbus command (qdbus6 for Plasma 6, qdbus otherwise)."""
    return next((command for command in ("qdbus6", "qdbus") if shutil.which(command)), None)


def _activity_manager(qdbus: str, method: str, *arguments: str) -> Result:
    return run(
        [qdbus, "org.kde.ActivityManager", "/ActivityManager/Activities", method, *arguments],
        timeout=ACTIVITY_MANAGER_TIMEOUT,
        capture_output=True,
    )


def _plasma_shell() -> Any:
    """Return the PlasmaShell D-Bus interface that evaluates wallpaper scripts.

    dbus-python is optional and builds from source, so it is imported here, at the
    point of use: without it Superpaper still starts and only KDE wallpaper setting
    fails, with an explanation.
    """
    try:
        import dbus  # ty:ignore[unresolved-import]
    except ImportError as error:
        message = (
            "Setting the wallpaper on KDE Plasma needs dbus-python. Install your distribution's "
            "python-dbus package, or install Superpaper with the [linux] extra."
        )
        raise PlasmaScriptingUnavailable(message) from error
    session_bus = dbus.SessionBus()
    return dbus.Interface(
        session_bus.get_object("org.kde.plasmashell", "/PlasmaShell"),
        dbus_interface="org.kde.PlasmaShell",
    )


def _load_mapping(state_dir: Path) -> dict[int, str]:
    """The remembered desktop-to-activity mapping."""
    path = state_dir / MAPPING_FILE
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        logger.warning("Failed to load desktop mapping cache: %s", error)
        return {}
    if not isinstance(data, dict):
        logger.warning("Invalid cache format, expected dict, got %s", type(data).__name__)
        return {}
    mapping = {}
    for key, value in data.items():
        try:
            mapping[int(key)] = str(value)
        except ValueError:
            logger.warning("Skipping invalid cache entry: %s -> %s", key, value)
    return mapping


def _save_mapping(state_dir: Path, mapping: dict[int, str]) -> None:
    path = state_dir / MAPPING_FILE
    try:
        write_atomically(path, json.dumps(mapping, indent=2).encode())
    except OSError as error:
        logger.warning("Failed to save desktop mapping cache: %s", error)
        return
    logger.info("Saved desktop mapping cache to %s", path)
