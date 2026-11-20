"""Set the wallpaper on Linux: GNOME and its relatives, Cinnamon, MATE, XFCE, LXQt,
KDE Plasma, window managers through feh, or the user's own command."""

import logging
import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal, assert_never

import superpaper.desktop.linux.kde as kde
from superpaper.desktop.monitors import detect_monitors as detect_monitors
from superpaper.desktop.process import QUICK, Result, run
from superpaper.desktop.process import run_hook as run_hook
from superpaper.desktop.tray_menu import MenuEntry, TrayHandle
from superpaper.desktop.wallpaper import Pieces, ProfileWallpapers, Wallpaper

logger = logging.getLogger(__name__)

Setter = Literal["command", "feh", "gnome", "cinnamon", "mate", "xfce", "lxqt", "kde", "unknown"]

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


def setter(set_command: str) -> Setter:
    """How the wallpaper is set here: "command" is the user's own.

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


def default_dirs(environ: Mapping[str, str], install: Path) -> tuple[Path, Path]:
    """The XDG base directories, or Snap's."""
    snap_config = environ.get("SNAP_USER_DATA")
    config = Path(snap_config) if snap_config else _xdg_home(environ, "XDG_CONFIG_HOME", ".config") / "superpaper"
    snap_cache = environ.get("SNAP_USER_COMMON")
    cache = Path(snap_cache) if snap_cache else _xdg_home(environ, "XDG_CACHE_HOME", ".cache") / "superpaper"
    return config, cache / "temp"


def _xdg_home(environ: Mapping[str, str], variable: str, fallback: str) -> Path:
    """An XDG base directory; one that is unset or isn't a directory falls back to ~/<fallback>."""
    value = environ.get(variable)
    if value and os.path.isdir(value):
        return Path(value)
    return Path(environ.get("HOME") or os.path.expanduser("~")) / fallback


def hotkeys_by_default() -> bool:
    """Hotkeys are on."""
    return True


def render_extension() -> str:
    """Rendered wallpapers are PNG."""
    return "png"


def strict_profile_names() -> bool:
    """Only new profile names must follow the portable rules."""
    return False


def init_main_loop() -> None:
    """Route incoming D-Bus calls (the native tray) through wxGTK's GLib main loop."""
    try:
        from dbus.mainloop.glib import DBusGMainLoop  # ty:ignore[unresolved-import]
    except ImportError:
        return
    DBusGMainLoop(set_as_default=True)


def make_tray(
    *,
    menu: Callable[[], tuple[MenuEntry, ...]],
    call_soon: Callable[[Callable[[], None]], None],
    activate: Callable[[], None],
    secondary_activate: Callable[[], None],
    icon_path: str,
    title: str,
) -> TrayHandle | None:
    """The native StatusNotifierItem tray, if a watcher is running and it registers."""
    from superpaper.desktop.linux import sni_tray

    if not sni_tray.sni_supported():
        return None
    return sni_tray.build_tray(
        menu=menu,
        call_soon=call_soon,
        activate=activate,
        secondary_activate=secondary_activate,
        bus_name=f"org.kde.StatusNotifierItem-{os.getpid()}-1",
        icon_path=icon_path,
        title=title,
        tooltip=title,
    )


def wx_tray_clickable() -> bool:
    """wx's tray icon renders but is dead on KDE Plasma 6."""
    return not running_kde()


def hotkey_problems_in_dialog() -> bool:
    """On KDE they are only logged."""
    return not running_kde()


def takes_pieces(set_command: str) -> bool:
    """Whether the desktop sets one image per display, so a wallpaper is cut into pieces."""
    return setter(set_command) == "kde"


def keeps_wallpaper() -> bool:
    """Whether the desktop shows the last wallpaper again after a restart by itself."""
    return False


def setter_problem(set_command: str) -> str | None:
    """Why Superpaper can't set the wallpaper on this desktop, if it can't."""
    return UNKNOWN_DESKTOP if setter(set_command) == "unknown" else None


def open_folder(folder: Path) -> Result:
    """Show ``folder`` in the desktop's file manager."""
    return run(["xdg-open", os.fspath(folder)])


def set_wallpaper(wallpaper: Wallpaper, *, set_command: str, profiles: ProfileWallpapers) -> Result:
    """Show the image of ``wallpaper``; KDE Plasma shows its pieces, one image per display,
    instead."""
    image = wallpaper.image
    logger.info("Setting the wallpaper on Linux to %s", image)
    kind = setter(set_command)
    match kind:
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
            if not isinstance(wallpaper, Pieces):
                return Result("KDE Plasma needs the wallpaper cut into one image per display.")
            return kde.set_wallpaper(wallpaper.pieces, profiles)
        case "unknown":
            return Result(UNKNOWN_DESKTOP)
        case _:
            assert_never(kind)


def set_spanmode(set_command: str) -> Result:
    """Set the desktop to span one image across the displays, where that is a setting."""
    kind = setter(set_command)
    match kind:
        case "gnome":
            return gsettings("org.gnome.desktop.background", "picture-options", "spanned")
        case "cinnamon":
            return gsettings("org.cinnamon.desktop.background", "picture-options", "spanned")
        case "mate":
            return gsettings("org.mate.background", "picture-options", "spanned")
        case "lxqt":
            return pcmanfm("--wallpaper-mode=stretch")
        case "command" | "feh" | "xfce" | "kde" | "unknown":
            return Result()  # no such setting, or the desktop sets one image per display
        case _:
            assert_never(kind)


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
    query = ["xfconf-query", "-c", "xfce4-desktop"]
    listed = run([*query, "-p", "/backdrop", "-l"], timeout=QUICK, capture_output=True)
    if not listed.ok:
        return listed
    results = []
    for prop in listed.output.split("\n"):
        if "workspace0/image-style" in prop:
            results.append(run([*query, "-p", prop, "-s", "6"], timeout=QUICK))
        elif "workspace0/last-image" in prop:
            results.append(run([*query, "-p", prop, "-s", image], timeout=QUICK))
    return next((result for result in results if not result.ok), Result())
