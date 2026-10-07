"""Set the wallpaper on KDE Plasma: one image per display, through Plasma's scripting
interface over D-Bus, with each activity showing the profile named after it."""

import json
import logging
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template

from superpaper.desktop.process import Result, run
from superpaper.files import write_atomically

logger = logging.getLogger(__name__)

# Which desktop belongs to which activity, as learned so far (Plasma only tells for the
# current activity). Kept in the config directory.
MAPPING_FILE = "kde_desktop_mapping.json"

# Lists every desktop as "id,screen;"; a desktop of an activity that isn't showing is on
# screen -1.
DESKTOPS_SCRIPT = """
var allDesktops = desktops();
var result = [];
for(var i = 0; i < allDesktops.length; i++) {
    result.push(allDesktops[i].id + ',' + allDesktops[i].screen);
}
print(result.join(';'));
"""

# Gives each desktop the image for its screen. The desktops on a screen now, sorted by
# their screen's top and then (deciding) its left edge, order the screens the way
# Superpaper orders the displays. A desktop without a screen, of an activity that isn't
# showing, is guessed to be on the screen its position in the list suggests.
WALLPAPER_SCRIPT = Template("""
var imagesByDesktop = ${images_by_desktop};
var defaultImages = ${default_images};

var allDesktops = desktops();

var activeDesktops = [];
for(var idx = 0; idx < allDesktops.length; idx++) {
    if(allDesktops[idx].screen != -1) {
        activeDesktops.push(allDesktops[idx]);
    }
}

var i = 1;
while(i < activeDesktops.length) {
    var j = i;
    while(j > 0 && screenGeometry(activeDesktops[j-1].screen).top > screenGeometry(activeDesktops[j].screen).top) {
        var temp = activeDesktops[j];
        activeDesktops[j] = activeDesktops[j-1];
        activeDesktops[j-1] = temp;
        j = j-1;
    }
    i = i+1;
}

i = 1;
while(i < activeDesktops.length) {
    var j = i;
    while(j > 0 && screenGeometry(activeDesktops[j-1].screen).left > screenGeometry(activeDesktops[j].screen).left) {
        var temp = activeDesktops[j];
        activeDesktops[j] = activeDesktops[j-1];
        activeDesktops[j-1] = temp;
        j = j-1;
    }
    i = i+1;
}

var screenOrder = [];
for(var k = 0; k < activeDesktops.length; k++) {
    screenOrder.push(activeDesktops[k].screen);
}

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
    var imageIndex = -1;
    for(var s = 0; s < screenOrder.length; s++) {
        if(screenOrder[s] == screenId) {
            imageIndex = s;
            break;
        }
    }
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


@dataclass(frozen=True, slots=True)
class Activities:
    """What it takes to give each KDE activity the wallpaper of the profile named after it."""

    current_profile: str | None
    """The running profile: the activity with its name gets the new wallpaper."""
    cached_pieces: Callable[[str], list[str]]
    """The per-display images last rendered for the profile of a given name, if any."""
    state_dir: Path
    """Where which desktop belongs to which activity is remembered."""


class PlasmaScriptingUnavailable(RuntimeError):
    """dbus-python, which KDE wallpaper scripting needs, is not installed."""


def set_wallpaper(pieces: Sequence[str], activities: Activities) -> Result:
    """Show ``pieces``, one image per display in Superpaper's display order.

    With activities, each activity shows the last wallpaper of the profile named after
    it, or else ``pieces``, which the running profile's activity always gets.
    """
    names = activity_names()
    if not names:
        return _evaluate(wallpaper_script({}, pieces))
    images = {activity: _activity_images(name, pieces, activities) for activity, name in names.items()}
    desktops = desktop_activities(activities.state_dir)
    if not desktops:
        return Result("Failed to get desktop-activity mapping, cannot set wallpapers")
    by_desktop = {desktop: images[activity] for desktop, activity in desktops.items() if activity in images}
    return _evaluate(wallpaper_script(by_desktop, None))


def wallpaper_script(images_by_desktop: Mapping[int, Sequence[str]], default_images: Sequence[str] | None) -> str:
    """The Plasma script that gives each desktop its images, or ``default_images``."""
    by_desktop = {str(desktop): _file_urls(images) for desktop, images in images_by_desktop.items()}
    default = None if default_images is None else _file_urls(default_images)
    return WALLPAPER_SCRIPT.substitute(images_by_desktop=json.dumps(by_desktop), default_images=json.dumps(default))


def activity_names() -> dict[str, str]:
    """The KDE activities, id to name; empty when they can't be listed."""
    qdbus = _qdbus()
    if not qdbus:
        logger.error("Neither qdbus6 nor qdbus found")
        return {}
    listed = _activity_manager(qdbus, "ListActivities")
    if not listed.ok:
        return {}
    names = {}
    for activity_id in listed.output.strip().split("\n"):
        if activity_id:
            named = _activity_manager(qdbus, "ActivityName", activity_id)
            if named.ok:
                names[activity_id] = named.output.strip()
    logger.info("KDE Activities found: %s", names)
    return names


def desktop_activities(state_dir: Path) -> dict[int, str]:
    """Which activity each Plasma desktop belongs to, desktop id to activity id.

    Plasma only tells which desktops belong to the current activity, so what was learned
    before is remembered in ``state_dir``, and desktops never seen are guessed: the
    other activities' desktops are taken to follow each other, one per screen.
    """
    desktop_to_activity = _load_mapping(state_dir)
    qdbus = _qdbus()
    if not qdbus:
        logger.error("Neither qdbus6 nor qdbus found")
        return desktop_to_activity
    listed = _activity_manager(qdbus, "ListActivities")
    if not listed.ok:
        return desktop_to_activity
    activity_ids = [line.strip() for line in listed.output.strip().split("\n") if line.strip()]
    current = _activity_manager(qdbus, "CurrentActivity")
    current_activity_id = current.output.strip() if current.ok else None
    try:
        desktop_info = _plasma_shell().evaluateScript(DESKTOPS_SCRIPT)
        logger.info("Desktop info from plasma: %s", desktop_info)
        all_desktop_ids = []
        active_desktop_ids = []
        for item in (desktop_info or "").split(";"):
            if "," in item:
                desktop_id, screen_id = (int(part) for part in item.split(",")[:2])
                all_desktop_ids.append(desktop_id)
                if screen_id != -1:
                    active_desktop_ids.append(desktop_id)
    except Exception:  # dbus-python is missing, or Plasma answered something else
        logger.exception("Failed to get desktop-activity mapping")
        return {}
    if not active_desktop_ids or not current_activity_id:
        logger.error("Could not determine active desktops or current activity")
        return desktop_to_activity

    # The desktops on screen now belong to the current activity.
    mapping_updated = False
    for desktop_id in active_desktop_ids:
        if desktop_to_activity.get(desktop_id) != current_activity_id:
            desktop_to_activity[desktop_id] = current_activity_id
            mapping_updated = True
    unmapped_desktop_ids = [d for d in all_desktop_ids if d not in desktop_to_activity]
    if unmapped_desktop_ids and len(activity_ids) > 1:
        other_activities = [a for a in activity_ids if a != current_activity_id]
        for idx, desktop_id in enumerate(unmapped_desktop_ids):
            activity_idx = idx // len(active_desktop_ids)
            if activity_idx < len(other_activities):
                desktop_to_activity[desktop_id] = other_activities[activity_idx]
                mapping_updated = True
    if mapping_updated:
        _save_mapping(state_dir, desktop_to_activity)
    logger.info("Current activity: %s", current_activity_id)
    logger.info("Active desktops: %s", active_desktop_ids)
    logger.info("Desktop to activity mapping: %s", desktop_to_activity)
    return desktop_to_activity


def _activity_images(name: str, pieces: Sequence[str], activities: Activities) -> list[str]:
    if activities.current_profile and name == activities.current_profile:
        logger.info("Activity '%s' matched profile '%s'", name, activities.current_profile)
        return list(pieces)
    cached = activities.cached_pieces(name)
    if cached:
        logger.info("Activity '%s' using cached wallpapers from profile '%s'", name, name)
        return cached
    logger.info("Activity '%s' using fallback wallpapers from profile '%s'", name, activities.current_profile)
    return list(pieces)


def _file_urls(paths: Sequence[str]) -> list[str]:
    return ["file://" + path for path in paths]


def _evaluate(script: str) -> Result:
    try:
        _plasma_shell().evaluateScript(script)
    except PlasmaScriptingUnavailable as error:
        return Result(str(error))
    except Exception as error:  # D-Bus failures come in many types
        return Result(f"Plasma did not take the wallpaper: {error}")
    return Result()


def _qdbus() -> str | None:
    """The available qdbus command (qdbus6 for Plasma 6, qdbus otherwise)."""
    return next((command for command in ("qdbus6", "qdbus") if shutil.which(command)), None)


def _activity_manager(qdbus: str, method: str, *arguments: str) -> Result:
    return run(
        [qdbus, "org.kde.ActivityManager", "/ActivityManager/Activities", method, *arguments],
        timeout=5,
        capture_output=True,
    )


def _plasma_shell():
    """Return the PlasmaShell D-Bus interface that evaluates wallpaper scripts.

    dbus-python is optional and builds from source, so it is imported here, at the
    point of use: without it Superpaper still starts and only KDE wallpaper setting
    fails, with an explanation.
    """
    try:
        import dbus  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]
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
        except ValueError, TypeError:
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
