"""The general_settings file: Superpaper's application-wide settings.

Reading and writing have no side effects beyond the file itself. Logging, hotkeys and
the wallpaper setter are configured by their owners from the returned value.
"""

import locale
from dataclasses import dataclass, replace
from pathlib import Path

from superpaper.files import write_atomically

SETTINGS_FILE = "general_settings"


@dataclass(frozen=True, slots=True)
class Settings:
    """Application-wide settings. A file that leaves a setting out gets these values."""

    logging: bool = False
    use_hotkeys: bool = True
    hk_binding_next: tuple[str, ...] | None = None
    hk_binding_pause: tuple[str, ...] | None = None
    set_command: str = ""
    browse_default_dir: str = ""
    show_help: bool = True
    warn_large_img: bool = True


def first_run_settings(platform: str) -> Settings:
    """The settings a new installation starts with. Hotkeys are off by default on macOS."""
    return Settings(
        use_hotkeys=platform != "darwin",
        hk_binding_next=("control", "super", "w"),
        hk_binding_pause=("control", "super", "shift", "p"),
    )


def read_settings(path: Path, platform: str) -> Settings:
    """The settings saved at ``path``, or the first-run settings if there is no file yet."""
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return first_run_settings(platform)
    settings = Settings()
    for line in content.decode(_encoding()).splitlines():
        key, _, value = line.strip().partition("=")
        key, value = key.strip(), value.strip()
        match key:
            case "logging":
                settings = replace(settings, logging=value.lower() == "true")
            case "use hotkeys":
                settings = replace(settings, use_hotkeys=value.lower() == "true")
            case "next wallpaper hotkey":
                settings = replace(settings, hk_binding_next=tuple(value.split("+")) if value else None)
            case "pause wallpaper hotkey":
                settings = replace(settings, hk_binding_pause=tuple(value.split("+")) if value else None)
            case "set_command":
                settings = replace(settings, set_command=value)
            case "browse_default_dir":
                settings = replace(settings, browse_default_dir=value)
            case "show_help_at_start":
                settings = replace(settings, show_help=value.lower() != "false")
            case "warn_large_img":
                settings = replace(settings, warn_large_img=value.lower() != "false")
            case _:
                pass  # blank lines, and settings of other versions
    return settings


def write_settings(path: Path, settings: Settings) -> None:
    """Replace the file at ``path`` with ``settings``, in the format every version reads."""
    lines = [
        f"logging={_flag(settings.logging)}",
        f"use hotkeys={_flag(settings.use_hotkeys)}",
    ]
    if settings.hk_binding_next:
        lines.append("next wallpaper hotkey=" + "+".join(settings.hk_binding_next))
    if settings.hk_binding_pause:
        lines.append("pause wallpaper hotkey=" + "+".join(settings.hk_binding_pause))
    lines += [
        f"show_help_at_start={_flag(settings.show_help)}",
        f"set_command={settings.set_command}",
        f"browse_default_dir={settings.browse_default_dir}",
        f"warn_large_img={_flag(settings.warn_large_img)}",
    ]
    write_atomically(path, "\n".join(lines).encode(_encoding()))


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _encoding() -> str:
    """The encoding earlier versions used for this file: Python's default text encoding,
    which is the ANSI code page on Windows."""
    return locale.getpreferredencoding(False)
