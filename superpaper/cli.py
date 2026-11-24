"""CLI for Superpaper. --help switch prints usage."""

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from superpaper.desktop.backend import Desktop
from superpaper.geometry.display_detection import DisplayDetectionError, detect_layout_or_default
from superpaper.geometry.displays import Layout
from superpaper.geometry.perspective import Named
from superpaper.paths import AppPaths, ensure_dirs
from superpaper.profiles import profile_file, profile_store
from superpaper.profiles.profile_id import ProfileId, ProfileIdError
from superpaper.settings import SETTINGS_FILE, Settings, read_settings, write_settings
from superpaper.user_input import Offset, OffsetError
from superpaper.wallpaper_change import show

logger = logging.getLogger(__name__)
_PACKAGE_LOGGER = logging.getLogger("superpaper")


def parse_offset_args(args: Sequence[str]) -> tuple[Offset, ...]:
    """The offsets of command line ``args``: an x and a y in pixels for each display."""
    if len(args) % 2:
        message = (
            "Number of offset pixels not even. If passing manual offsets, give width and height offset "
            "for each display, even if not actually offsetting every display."
        )
        raise OffsetError(message)
    try:
        pixels = [int(arg) for arg in args]
    except ValueError:
        message = f"The offsets must be whole numbers of pixels: {' '.join(args)}"
        raise OffsetError(message) from None
    return tuple(zip(pixels[::2], pixels[1::2], strict=True))


class CliError(Exception):
    """What the command line asked for can't be done; the message tells the user why."""


@dataclass(frozen=True, slots=True)
class StartTray:
    profile_id: ProfileId | None
    debug: bool


@dataclass(frozen=True, slots=True)
class SetImages:
    images: tuple[str, ...]
    advanced: bool
    perspective: str | None
    spangroups: tuple[tuple[int, ...], ...] | None
    offsets: tuple[Offset, ...]
    set_command: str
    debug: bool


Request = StartTray | SetImages


def run(argv: Sequence[str], paths: AppPaths, desktop: Desktop) -> int:
    """Do what the command line ``argv`` (without the program name) asks; returns the exit status.

    Superpaper's directories are created, and the desktop set to span, only on the way to
    setting a wallpaper, so that `--help` or a mistyped option changes nothing.
    """
    try:
        request = parse_arguments(argv, windows_names=desktop.strict_profile_names())
        match request:
            case StartTray():
                if request.profile_id is not None:
                    _check_profile_exists(paths, desktop, request.profile_id)
                _start_tray(paths, desktop, request.profile_id, debug=request.debug)
                return 0
            case SetImages():
                return _set_images(request, paths, desktop)
            case _:
                assert_never(request)
    except CliError as error:
        logger.error("%s", error)  # noqa: TRY400  # the message is the whole report
        return 1


def parse_arguments(argv: Sequence[str], *, windows_names: bool) -> Request:
    """The request the command line ``argv`` makes. Raises CliError if it can't be met."""
    if not argv:
        return StartTray(profile_id=None, debug=False)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s",
        "--setimages",
        nargs="*",
        help=(
            "List of images to set as wallpaper, starting from the left most monitor. "
            "If a single image is given, it is spanned across all monitors."
        ),
    )
    parser.add_argument(
        "-a",
        "--advanced",
        action="store_true",
        help=(
            "Span an image across all displays using advanced settings. "
            "These must be configured in the graphical interface."
        ),
    )
    parser.add_argument(
        "--perspective",
        help=(
            "Select an existing perspective profile to be used with advanced spanning. "
            "Configure settings in application."
        ),
    )
    parser.add_argument(
        "--spangroups",
        nargs="*",
        help=(
            "Span groups to use with advanced spanning. With this you can span wallpapers on groups of displays. "
            "Syntax is: 0 12 35 4 6, i.e. separate groups by spaces. "
            "If display numbering is unclear, check in the application."
        ),
    )
    parser.add_argument(
        "-p",
        "--profile",
        help=(
            "Start Superpaper by running an existing wallpaper profile. "
            "Name must match the one configured in the application."
        ),
    )
    parser.add_argument(
        "-o",
        "--offsets",
        nargs="*",
        help="List of wallpaper offsets. Only supported by advanced span mode.",
    )
    parser.add_argument(
        "-c",
        "--command",
        nargs="*",
        help="Custom command to set the wallpaper. Substitute /path/to/image.jpg by '{image}'. Must be in quotes.",
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Run the full application with debugging.")
    args = parser.parse_args(argv)

    if args.debug and len(argv) == 1:
        return StartTray(profile_id=None, debug=True)
    if args.profile and not args.setimages:
        try:
            return StartTray(profile_id=ProfileId.parse(args.profile, windows_names=windows_names), debug=args.debug)
        except ProfileIdError as error:
            message = f"Invalid profile name: {error}"
            raise CliError(message) from error
    if not args.setimages or args.profile:
        message = (
            "Pass either image(s) to set as the wallpaper with '-s' or '--setimages', "
            "or a profile to start Superpaper with using '-p' or '--profile'."
        )
        raise CliError(message)
    for filename in args.setimages:
        if not filename:
            message = "An image name passed with '-s' or '--setimages' was empty."
            raise CliError(message)
        if not os.path.isfile(filename):
            message = f"One of the passed image names was not a file: {filename}"
            raise CliError(message)
    if not args.advanced:
        for option, given in (
            ("--offsets", args.offsets),
            ("--perspective", args.perspective),
            ("--spangroups", args.spangroups),
        ):
            if given:
                message = f"'{option}' only works with advanced spanning: add '-a' or '--advanced'."
                raise CliError(message)
    try:
        spangroups = profile_file.parse_spangroups(args.spangroups) if args.spangroups else None
    except ValueError as error:
        raise CliError(str(error)) from error
    try:
        offsets = parse_offset_args(args.offsets or [])
    except OffsetError as error:
        raise CliError(str(error)) from error
    if args.command and len(args.command) > 1:
        message = "Remember to put the custom command in quotes."
        raise CliError(message)
    return SetImages(
        images=tuple(args.setimages),
        advanced=args.advanced,
        perspective=args.perspective,
        spangroups=spangroups,
        offsets=offsets,
        set_command=args.command[0] if args.command else "",
        debug=args.debug,
    )


def configure_logging(*, debug: bool, log_file: Path | None = None) -> None:
    """Log to the console when debugging, and to ``log_file`` (which also means debugging).

    Nothing is configured at import; this runs once, before any work starts. Without either
    argument, warnings and errors still reach stderr through Python's last-resort handler.
    Calling this again replaces the earlier configuration.
    """
    for handler in _PACKAGE_LOGGER.handlers[:]:
        _PACKAGE_LOGGER.removeHandler(handler)
        handler.close()
    debugging = debug or log_file is not None
    _PACKAGE_LOGGER.setLevel(logging.INFO if debugging else logging.NOTSET)
    if debugging:
        _PACKAGE_LOGGER.addHandler(logging.StreamHandler())
    if log_file is not None:
        _PACKAGE_LOGGER.addHandler(logging.FileHandler(log_file, mode="w", encoding="utf-8"))
    sys.excepthook = _log_uncaught_exception if log_file is not None else sys.__excepthook__


def _log_uncaught_exception(exception_type, exception, traceback) -> None:
    _PACKAGE_LOGGER.critical("Uncaught exception", exc_info=(exception_type, exception, traceback))


def _start_tray(paths: AppPaths, desktop: Desktop, profile_id: ProfileId | None, *, debug: bool) -> None:
    """Run the tray applet, with ``profile_id`` started if given, and the desktop set to span.

    A first start writes the default settings, so that the file is there to edit. Raises
    CliError if wxPython is not installed.
    """
    ensure_dirs(paths)
    try:
        from superpaper.ui.app import run as run_tray
    except ModuleNotFoundError as error:
        if error.name != "wx":
            raise
        message = (
            "Superpaper's tray icon and settings window need wxPython. Install it from your "
            "distribution's packages, or install Superpaper with the [gui] extra."
        )
        raise CliError(message) from error
    settings_file = paths.config / SETTINGS_FILE
    settings = read_settings(settings_file)
    if settings is None:
        settings = Settings()
        write_settings(settings_file, settings)
    configure_logging(debug=debug or settings.logging, log_file=paths.cache / "log" if settings.logging else None)
    _span_desktop(desktop, settings.set_command)
    run_tray(paths, settings, desktop, profile=profile_id)


def _span_desktop(desktop: Desktop, set_command: str) -> None:
    result = desktop.set_spanmode(set_command)
    if not result.ok:
        logger.warning("Could not set the desktop to span the displays: %s", result.problem)


def _detect_displays(paths: AppPaths, desktop: Desktop) -> Layout:
    try:
        loaded = detect_layout_or_default(paths.config, desktop)
    except DisplayDetectionError as error:
        message = f"No displays could be detected: {error}"
        raise CliError(message) from error
    except OSError as error:
        message = f"Superpaper's files could not be read or written: {error}"
        raise CliError(message) from error
    if loaded.problem is not None:
        print(f"Warning: {' '.join(loaded.problem.split())}", file=sys.stderr)
    return loaded.layout


def _check_profile_exists(paths: AppPaths, desktop: Desktop, profile_id: ProfileId) -> None:
    ensure_dirs(paths)
    _detect_displays(paths, desktop)  # fail here, with a message, rather than in the tray
    inventory = profile_store.discover(paths, windows_names=desktop.strict_profile_names())
    if inventory.find(profile_id) is None:
        names = [entry.profile_id.value for entry in inventory.entries]
        message = f"No profile was found by the given name: {profile_id.value}. Valid profile names are: {names}"
        raise CliError(message)


def _set_images(request: SetImages, paths: AppPaths, desktop: Desktop) -> int:
    configure_logging(debug=request.debug)
    if request.debug:
        logger.info("Command line request: %s", request)
    ensure_dirs(paths)
    saved = read_settings(paths.config / SETTINGS_FILE)
    set_command = request.set_command or (saved.set_command if saved else "")
    layout = None
    if request.perspective:
        layout = _detect_displays(paths, desktop)
        perspectives = layout.perspective_names()
        if request.perspective not in perspectives:
            message = f"Valid perspective profile names are: {perspectives}"
            raise CliError(message)
    problem = desktop.setter_problem(set_command)
    if problem:
        raise CliError(problem)
    if layout is None:  # the perspective check above already detected them
        layout = _detect_displays(paths, desktop)
    if request.advanced and (hint := layout.size_hint()):
        logger.warning("%s", hint)
    _span_desktop(desktop, set_command)
    images = [os.path.realpath(image) for image in request.images]
    if request.advanced:
        spanmode = "advanced"
    elif len(images) == 1:
        spanmode = "single"
    else:
        spanmode = "multi"
    profile = profile_file.draft(
        images,
        spanmode=spanmode,
        perspective=Named(request.perspective) if request.perspective else None,
        spangroups=request.spangroups,
        offsets=request.offsets,
    )
    # What went wrong, if anything, is logged where it happened.
    return 1 if show(profile, images, paths, desktop=desktop, layout=layout, set_command=set_command) is not None else 0
