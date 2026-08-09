"""CLI for Superpaper. --help switch prints usage."""

import argparse
import logging
import os
import sys

import superpaper.sp_logging as sp_logging
import superpaper.wallpaper_processing as wpproc
from superpaper.data import CLIProfileData, discover_profile_inventory
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.wallpaper_processing import change_wallpaper_job, refresh_display_data


def cli_logic():
    """
    CLI command parsing and enacting.

    Allows setting a wallpaper using Superpaper features without running the full application.
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

    if args.debug:
        sp_logging.DEBUG = True
        sp_logging.G_LOGGER.setLevel(logging.INFO)
        # Install exception handler
        # sys.excepthook = custom_exception_handler
        console_handler = logging.StreamHandler()
        sp_logging.CONSOLE_HANDLER = console_handler
        sp_logging.G_LOGGER.addHandler(console_handler)
        sp_logging.G_LOGGER.info(f"Input images: {args.setimages}")
        sp_logging.G_LOGGER.info(f"Input profile: {args.profile}")
        sp_logging.G_LOGGER.info(f"Input perspective: {args.perspective}")
        sp_logging.G_LOGGER.info(f"Input spangroups: {args.spangroups}")
        sp_logging.G_LOGGER.info(f"Input offsets: {args.offsets}")
        sp_logging.G_LOGGER.info(f"User defined command: {args.command}")
        sp_logging.G_LOGGER.info(f"Debugging: {args.debug}")
    if args.debug and len(sys.argv) == 2:
        from superpaper.tray import tray_loop

        tray_loop()
    else:
        if args.setimages and not args.profile:
            for filename in args.setimages:
                if filename and not os.path.isfile(filename):
                    sp_logging.G_LOGGER.error(
                        "Exception: One of the passed image names was not \
a file: (%s). Exiting.",
                        filename,
                    )
                    sys.exit()
        elif args.profile and not args.setimages:
            try:
                profile_id = ProfileId.parse(args.profile)
            except ProfileIdError as error:
                sp_logging.G_LOGGER.error("Invalid profile name: %s", error)
                sys.exit()
            refresh_display_data()
            inventory = discover_profile_inventory()
            entry = inventory.find(profile_id)
            if entry is not None:
                from superpaper.tray import tray_loop

                tray_loop(profile=profile_id)
                return 0
            else:
                sp_logging.G_LOGGER.error(
                    "Exception: No profile was found by the given name: \
(%s). Exiting.",
                    args.profile,
                )
                sp_logging.G_LOGGER.error(
                    "Valid profile names are: \
(%s)",
                    [entry.profile_id.value for entry in inventory.entries],
                )
                sys.exit(1)
        else:
            sp_logging.G_LOGGER.info("""Exception: You must pass either image(s) to set as \
wallpaper with '-s' or '--setimages', or a profile \
to start Superpaper with using '-p' or '--profile'. \
Exiting.""")
            sys.exit()
        display_data_loaded = False
        if args.perspective:
            refresh_display_data()
            display_data_loaded = True
            if args.perspective not in wpproc.G_ACTIVE_DISPLAYSYSTEM.perspective_dict:
                sp_logging.G_LOGGER.error(
                    f"Exception: Valid perspective profile names are: {list(wpproc.G_ACTIVE_DISPLAYSYSTEM.perspective_dict.keys())}."
                )
                sys.exit()
        spangrp = None
        if args.spangroups:
            # Parse spangroups
            spangrp = []
            for grp in args.spangroups:
                try:
                    ids = [int(idx) for idx in grp]
                    spangrp.append(sorted(set(ids)))  # drop duplicates
                except ValueError:
                    sp_logging.G_LOGGER.error(
                        f"Exception: One of the display ids \
was not an integer: {grp}. Exiting."
                    )
                    sys.exit()
        if args.offsets and len(args.offsets) % 2 != 0:
            sp_logging.G_LOGGER.error(
                "Exception: Number of offset pixels not even. \
If passing manual offsets, give width and height offset for each display, even if \
not actually offsetting every display. Exiting."
            )
            sys.exit()
        if args.command:
            if len(args.command) > 1:
                sp_logging.G_LOGGER.error(
                    "Exception: Remember to put the \
custom command in quotes. Exiting."
                )
                sys.exit()
            wpproc.G_SET_COMMAND_STRING = args.command[0]

        if not display_data_loaded:
            refresh_display_data()
        profile = CLIProfileData(args.setimages, args.advanced, args.perspective, spangrp, args.offsets)
        job_thread = change_wallpaper_job(profile, force=True)
        if job_thread is not None:
            job_thread.join()
        return 0
