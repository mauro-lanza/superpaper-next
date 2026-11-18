"""CLI for Superpaper. --help switch prints usage."""

import argparse
import configparser
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import assert_never

import superpaper.desktop as desktop
import superpaper.sp_logging as sp_logging
from superpaper import profile_store, profiles
from superpaper.display_detection import DisplayDetectionError, detect_layout
from superpaper.displays import Layout
from superpaper.paths import AppPaths, ensure_dirs
from superpaper.perspective import Named
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.session import show
from superpaper.settings import SETTINGS_FILE, read_settings, write_settings
from superpaper.user_input import Offset, OffsetError, parse_offset_args

logger = logging.getLogger(__name__)


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


def run(argv: Sequence[str], paths: AppPaths) -> int:
    """Do what the command line ``argv`` (without the program name) asks; returns the exit status.

    Superpaper's directories are created, and the desktop set to span, only on the way to
    setting a wallpaper, so that `--help` or a mistyped option changes nothing.
    """
    try:
        request = parse_arguments(argv)
        match request:
            case StartTray():
                if request.profile_id is not None:
                    _check_profile_exists(paths, request.profile_id)
                _start_tray(paths, request.profile_id, debug=request.debug)
                return 0
            case SetImages():
                return _set_images(request, paths)
            case _:
                assert_never(request)
    except CliError as error:
        logger.error("%s", error)  # noqa: TRY400  # the message is the whole report
        return 1


def parse_arguments(argv: Sequence[str]) -> Request:
    """The request the command line ``argv`` makes. Raises CliError if it can't be met."""
    if not argv:
        return StartTray(profile_id=None, debug=False)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s",
        "--setimages",
        nargs="*",
        help="""List of images to set as wallpaper,
                                starting from the left most monitor.
                                If a single image is given, it is spanned
                                across all monitors.""",
    )
    parser.add_argument(
        "-a",
        "--advanced",
        action="store_true",
        help="""Span an image across all displays using advanced settings.
                                These must be configured in the graphical interface.""",
    )
    parser.add_argument(
        "--perspective",
        help="""Select an existing perspective profile to be used with
                                advanced spanning. Configure settings in application.""",
    )
    parser.add_argument(
        "--spangroups",
        nargs="*",
        help="""Span groups to use with advanced spanning. With this you
                                can span wallpapers on groups of displays. Syntax is:
                                0 12 35 4 6, i.e. separate groups by spaces. If display
                                numbering is unclear, check in the application.""",
    )
    parser.add_argument(
        "-p",
        "--profile",
        help="""Start Superpaper by running an existing wallpaper profile.
                                Name must match the one configured in the application.""",
    )
    parser.add_argument(
        "-o",
        "--offsets",
        nargs="*",
        help="""List of wallpaper offsets. Only supported by advanced
                                span mode.""",
    )
    parser.add_argument(
        "-c",
        "--command",
        nargs="*",
        help="""Custom command to set the wallpaper.
                                Substitute /path/to/image.jpg by '{image}'.
                                Must be in quotes.""",
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Run the full application with debugging.")
    args = parser.parse_args(argv)

    if args.debug and len(argv) == 1:
        return StartTray(profile_id=None, debug=True)
    if args.profile and not args.setimages:
        try:
            return StartTray(profile_id=ProfileId.parse(args.profile), debug=args.debug)
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
        if filename and not os.path.isfile(filename):
            message = f"One of the passed image names was not a file: {filename}"
            raise CliError(message)
    try:
        spangroups = profiles.parse_spangroups(args.spangroups) if args.spangroups else None
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


def _start_tray(paths: AppPaths, profile_id: ProfileId | None, *, debug: bool) -> None:
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
    settings = read_settings(settings_file, sys.platform)
    if not settings_file.exists():
        write_settings(settings_file, settings)
    sp_logging.configure_logging(
        debug=debug or settings.logging, log_file=paths.cache / "log" if settings.logging else None
    )
    _span_desktop(settings.set_command)
    run_tray(paths, settings, profile=profile_id)


def _span_desktop(set_command: str) -> None:
    result = desktop.set_spanmode(set_command)
    if not result.ok:
        logger.warning("Could not set the desktop to span the displays: %s", result.problem)


def _detect_displays(paths: AppPaths) -> Layout:
    try:
        return detect_layout(paths.config)
    except DisplayDetectionError as error:
        message = f"No displays could be detected: {error}"
        raise CliError(message) from error
    except (ValueError, configparser.Error) as error:
        message = f"The saved display layout could not be read: {error}"
        raise CliError(message) from error


def _check_profile_exists(paths: AppPaths, profile_id: ProfileId) -> None:
    ensure_dirs(paths)
    _detect_displays(paths)  # fail here, with a message, rather than in the tray
    inventory = profile_store.discover(paths)
    if inventory.find(profile_id) is None:
        names = [entry.profile_id.value for entry in inventory.entries]
        message = f"No profile was found by the given name: {profile_id.value}. Valid profile names are: {names}"
        raise CliError(message)


def _set_images(request: SetImages, paths: AppPaths) -> int:
    sp_logging.configure_logging(debug=request.debug)
    if request.debug:
        logger.info("Command line request: %s", request)
    ensure_dirs(paths)
    layout = None
    if request.perspective:
        layout = _detect_displays(paths)
        perspectives = layout.perspective_names()
        if request.perspective not in perspectives:
            message = f"Valid perspective profile names are: {perspectives}"
            raise CliError(message)
    problem = desktop.setter_problem(request.set_command)
    if problem:
        raise CliError(problem)
    if layout is None:  # the perspective check above already detected them
        layout = _detect_displays(paths)
    if request.advanced and (hint := layout.size_hint()):
        logger.warning("%s", hint)
    _span_desktop(request.set_command)
    images = [os.path.realpath(image) for image in request.images]
    if request.advanced:
        spanmode = "advanced"
    elif len(images) == 1:
        spanmode = "single"
    else:
        spanmode = "multi"
    profile = profiles.draft(
        images,
        spanmode=spanmode,
        perspective=Named(request.perspective) if request.perspective else None,
        spangroups=request.spangroups,
        offsets=request.offsets,
    )
    # What went wrong, if anything, is logged where it happened.
    return 1 if show(profile, images, paths, layout=layout, set_command=request.set_command) is not None else 0
