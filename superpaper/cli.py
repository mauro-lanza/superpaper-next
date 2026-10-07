"""CLI for Superpaper. --help switch prints usage."""

import argparse
import os
import sys
from typing import NoReturn

import superpaper.desktop as desktop
import superpaper.sp_logging as sp_logging
import superpaper.wallpaper_processing as wpproc
from superpaper.data import CLIProfileData, discover_profile_inventory
from superpaper.desktop.spanmode import set_spanmode
from superpaper.paths import AppPaths, ensure_dirs
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.settings import SETTINGS_FILE, read_settings, write_settings
from superpaper.wallpaper_processing import DisplaySystem, change_wallpaper_job


def start_tray(paths: AppPaths, profile: ProfileId | None = None, *, debug: bool = False) -> None:
    """Run the tray applet, or explain what is missing if wxPython is not installed.

    A first start writes the default settings, so that the file is there to edit.
    """
    try:
        from superpaper.tray import tray_loop
    except ModuleNotFoundError as error:
        if error.name != "wx":
            raise
        sys.exit(
            "Superpaper's tray icon and settings window need wxPython. Install it from your "
            "distribution's packages, or install Superpaper with the [gui] extra."
        )
    settings_file = paths.config / SETTINGS_FILE
    settings = read_settings(settings_file, sys.platform)
    if not settings_file.exists():
        write_settings(settings_file, settings)
    sp_logging.configure_logging(
        debug=debug or settings.logging, log_file=paths.cache / "log" if settings.logging else None
    )
    tray_loop(paths, settings, profile=profile)


def _exit_with_error(message: str) -> NoReturn:
    sp_logging.G_LOGGER.error(message)
    sys.exit(1)


def _detect_displays(paths: AppPaths) -> DisplaySystem:
    try:
        return DisplaySystem(paths.config)
    except wpproc.DisplayDetectionError as error:
        _exit_with_error(f"No displays could be detected: {error}")


def cli_logic(paths: AppPaths):
    """
    CLI command parsing and enacting.

    Allows setting a wallpaper using Superpaper features without running the full application.
    Superpaper's directories are created only once the arguments are known to be usable.
    """
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
    args = parser.parse_args()

    if args.debug and len(sys.argv) == 2:
        ensure_dirs(paths)
        set_spanmode()
        start_tray(paths, debug=True)
        return 0
    if args.setimages and not args.profile:
        for filename in args.setimages:
            if filename and not os.path.isfile(filename):
                _exit_with_error(f"One of the passed image names was not a file: {filename}")
    elif args.profile and not args.setimages:
        try:
            profile_id = ProfileId.parse(args.profile)
        except ProfileIdError as error:
            _exit_with_error(f"Invalid profile name: {error}")
        ensure_dirs(paths)
        _detect_displays(paths)  # fail here, with a message, rather than in the tray
        inventory = discover_profile_inventory(paths)
        if inventory.find(profile_id) is None:
            names = [entry.profile_id.value for entry in inventory.entries]
            _exit_with_error(
                f"No profile was found by the given name: {args.profile}. Valid profile names are: {names}"
            )
        set_spanmode()
        start_tray(paths, profile=profile_id, debug=args.debug)
        return 0
    else:
        _exit_with_error(
            "Pass either image(s) to set as the wallpaper with '-s' or '--setimages', "
            "or a profile to start Superpaper with using '-p' or '--profile'."
        )
    sp_logging.configure_logging(debug=args.debug)
    if args.debug:
        sp_logging.G_LOGGER.info(f"Input images: {args.setimages}")
        sp_logging.G_LOGGER.info(f"Input perspective: {args.perspective}")
        sp_logging.G_LOGGER.info(f"Input spangroups: {args.spangroups}")
        sp_logging.G_LOGGER.info(f"Input offsets: {args.offsets}")
        sp_logging.G_LOGGER.info(f"User defined command: {args.command}")
    ensure_dirs(paths)
    display_system = None
    if args.perspective:
        display_system = _detect_displays(paths)
        perspectives = display_system.perspective_dict
        if args.perspective not in perspectives:
            _exit_with_error(f"Valid perspective profile names are: {list(perspectives)}")
    spangrp = None
    if args.spangroups:
        # Parse spangroups
        spangrp = []
        for grp in args.spangroups:
            try:
                ids = [int(idx) for idx in grp]
            except ValueError:
                _exit_with_error(f"One of the display ids was not an integer: {grp}")
            spangrp.append(sorted(set(ids)))  # drop duplicates
    if args.offsets and len(args.offsets) % 2 != 0:
        _exit_with_error(
            "Number of offset pixels not even. If passing manual offsets, give width and height offset "
            "for each display, even if not actually offsetting every display."
        )
    set_command = ""
    if args.command:
        if len(args.command) > 1:
            _exit_with_error("Remember to put the custom command in quotes.")
        set_command = args.command[0]
    problem = desktop.setter_problem(set_command)
    if problem:
        _exit_with_error(problem)

    if display_system is None:  # the perspective check above already detected them
        display_system = _detect_displays(paths)
    set_spanmode()
    profile = CLIProfileData(args.setimages, args.advanced, args.perspective, spangrp, args.offsets)
    job_thread = change_wallpaper_job(
        profile, paths, display_system=display_system, set_command=set_command, force=True
    )
    if job_thread is not None:
        job_thread.join()
    return 0
