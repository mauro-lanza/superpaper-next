"""Set the wallpaper on Linux: GNOME and its relatives, Cinnamon, MATE, XFCE, LXQt,
KDE Plasma, window managers through feh, or the user's own command."""

import logging
import os
import shutil
from collections.abc import Sequence

from superpaper.desktop import kde
from superpaper.desktop.process import QUICK, Result, run

logger = logging.getLogger(__name__)

GNOME_SESSIONS = (
    "gnome",
    "gnome-wayland",
    "gnome-xorg",
    "unity",
    "ubuntu",
    "pantheon",
    "budgie-desktop",
    "pop",
    "zorin",
)
XFCE_SESSIONS = ("xfce", "xubuntu", "ubuntustudio")
UNKNOWN_DESKTOP = (
    "Your desktop environment could not be detected, so Superpaper can't set the wallpaper. "
    "Set a Custom command in Settings, or pass one with -c on the command line."
)


def running_kde() -> bool:
    """Detect if running in a KDE session."""
    d_ses = os.environ.get("DESKTOP_SESSION")
    if d_ses and ("plasma" in d_ses or "kde" in d_ses):
        return True
    kde_f_ses = os.environ.get("KDE_FULL_SESSION")
    xdg_ses_dtop = os.environ.get("XDG_SESSION_DESKTOP")
    return bool(kde_f_ses == "true" or xdg_ses_dtop == "KDE")


def setter(set_command: str) -> str:
    """How the wallpaper is set here: "command" (the user's own), "feh", "gnome",
    "cinnamon", "mate", "xfce", "lxqt", "kde", or "unknown".

    The DESKTOP_SESSION variable names the desktop. Window managers such as i3 often
    leave it unset, and then feh is used.
    """
    if set_command:
        return "feh" if set_command == "feh" else "command"
    desk_env = os.environ.get("DESKTOP_SESSION")
    if not desk_env:
        return "kde" if running_kde() else "feh"
    if desk_env in GNOME_SESSIONS:
        return "gnome"
    if desk_env == "cinnamon" or "cinnamon" in desk_env.lower():
        return "cinnamon"
    if desk_env == "mate":
        return "mate"
    if desk_env in XFCE_SESSIONS:
        return "xfce"
    if desk_env.lower() == "lubuntu" or "lxqt" in desk_env.lower():
        return "lxqt"
    if running_kde():
        return "kde"
    if "i3" in desk_env or desk_env == "/usr/share/xsessions/bspwm":
        return "feh"
    return "unknown"


def set_wallpaper(image: str, pieces: Sequence[str] | None, *, set_command: str, activities: kde.Activities) -> Result:
    """Show ``image``; KDE Plasma shows ``pieces``, one image per display, instead."""
    logger.info("Setting the wallpaper on Linux to %s", image)
    match setter(set_command):
        case "command":
            return _custom_command(set_command, image)
        case "feh":
            return run(["feh", "--bg-scale", "--no-xinerama", image], timeout=QUICK)
        case "gnome":
            dark = gsettings("org.gnome.desktop.background", "picture-uri-dark", "file://" + image)
            if not dark.ok:  # GNOME before 42 has no wallpaper for the dark style
                logger.info("No dark-style wallpaper set: %s", dark.problem)
            return gsettings("org.gnome.desktop.background", "picture-uri", "file://" + image)
        case "cinnamon":
            return gsettings("org.cinnamon.desktop.background", "picture-uri", "file://" + image)
        case "mate":
            return gsettings("org.mate.background", "picture-filename", image)
        case "xfce":
            return _xfce(image)
        case "lxqt":
            return pcmanfm("-w", image)
        case "kde":
            if not pieces:
                return Result("KDE Plasma needs the wallpaper cut into one image per display.")
            return kde.set_wallpaper(pieces, activities)
        case _:
            return Result(UNKNOWN_DESKTOP)


def gsettings(schema: str, key: str, value: str) -> Result:
    """Set a GSettings key, as GNOME and its relatives store their wallpaper settings."""
    return run(["/usr/bin/gsettings", "set", schema, key, value], timeout=QUICK)


def pcmanfm(*arguments: str) -> Result:
    """Run LXDE's and LXQt's desktop, pcmanfm or else pcmanfm-qt, with ``arguments``."""
    for program in ("pcmanfm", "pcmanfm-qt"):
        if shutil.which(program):
            return run([program, *arguments])
    return Result("Neither pcmanfm nor pcmanfm-qt is installed.")


def _custom_command(set_command: str, image: str) -> Result:
    """Run the user's command, with {image} replaced by the wallpaper image."""
    try:
        command = [term.format(image=image) for term in set_command.split()]
    except (KeyError, IndexError, ValueError) as error:
        return Result(f"The custom command '{set_command}' may only use {{image}} in braces ({error}).")
    logger.info("Formatted custom command is: '%s'", command)
    return run(command)


def _xfce(image: str) -> Result:
    """Set the image of every XFCE backdrop of the first workspace."""
    listed = run(["xfconf-query", "-c", "xfce4-desktop", "-p", "/backdrop", "-l"], timeout=QUICK, capture_output=True)
    if not listed.ok:
        return listed
    results = []
    for prop in listed.output.split("\n"):
        if "workspace0/image-style" in prop:
            results.append(run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", "6"], timeout=QUICK))
        elif "workspace0/last-image" in prop:
            results.append(run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", image], timeout=QUICK))
    return next((result for result in results if not result.ok), Result())
