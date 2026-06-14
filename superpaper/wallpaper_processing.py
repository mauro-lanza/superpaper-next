"""
Wallpaper image processing back-end for Superpaper.

Applies image corrections, crops, merges etc. and sets the wallpaper
with native platform methods whenever possible.

Written by Henri Hänninen, copyright 2022 under MIT licence.
"""

import configparser
import json
import math
import os
import shutil
import subprocess
import sys
import traceback
from operator import itemgetter
from threading import Lock, Thread, Timer
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from screeninfo import get_monitors

import superpaper.perspective as persp
import superpaper.sp_logging as sp_logging
from superpaper.message_dialog import show_message_dialog
from superpaper.sp_paths import CONFIG_PATH, TEMP_PATH
from superpaper.sp_platform import IS_LINUX, IS_MACOS, IS_WINDOWS

# Disables PIL.Image.DecompressionBombError.
Image.MAX_IMAGE_PIXELS = None  # 715827880 would be 4x default max.


def running_kde():
    """Detect if running in a KDE session."""
    d_ses = os.environ.get("DESKTOP_SESSION")
    if d_ses and ("plasma" in d_ses or "kde" in d_ses):
        return True
    kde_f_ses = os.environ.get("KDE_FULL_SESSION")
    xdg_ses_dtop = os.environ.get("XDG_SESSION_DESKTOP")
    return bool(kde_f_ses == "true" or xdg_ses_dtop == "KDE")


# Platform-native helpers are imported conditionally below. Declare them up front
# with safe fallbacks so the names are always bound regardless of platform; the
# real implementations replace these on the matching OS.
set_wallpaper_win: Any = None
dbus: Any = None
NSScreen: Any = None
NSWorkspace: Any = None
NSURL: Any = None

if sys.platform == "win32":
    from superpaper.wallpaper_windows import set_wallpaper_win
elif sys.platform == "linux":
    # KDE has special needs
    # if os.environ.get("DESKTOP_SESSION") in ["/usr/share/xsessions/plasma", "plasma"]:
    if running_kde():
        import dbus
elif sys.platform == "darwin":
    from AppKit import NSScreen, NSWorkspace
    from Foundation import NSURL


# Global constants

NUM_DISPLAYS = 0
# list of display resolutions (width,height), use tuples.
RESOLUTION_ARRAY = []
# list of display offsets (width,height), use tuples.
DISPLAY_OFFSET_ARRAY = []

# Lazily initialized in load_system() before any wallpaper processing runs.
G_ACTIVE_DISPLAYSYSTEM: "DisplaySystem" = None  # pyright: ignore[reportAssignmentType]  # ty:ignore[invalid-assignment]
G_ACTIVE_PROFILE = None
G_WALLPAPER_CHANGE_LOCK = Lock()
G_SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp")
G_SET_COMMAND_STRING: str = ""

# global to take care that failure message is not shown more than once at launch
USER_TOLD_OF_PHYS_FAIL = False


class RepeatedTimer:
    """Threaded timer used for slideshow."""

    # Credit:
    # https://stackoverflow.com/questions/3393612/run-certain-code-every-n-seconds/13151299#13151299
    def __init__(self, interval, function, *args, **kwargs):
        self._timer = None
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.is_running = False
        self.start()

    def _run(self):
        self.is_running = False
        self.start()
        self.function(*self.args, **self.kwargs)

    def start(self):
        """Starts timer."""
        if not self.is_running:
            self._timer = Timer(self.interval, self._run)
            self._timer.daemon = True
            self._timer.start()
            self.is_running = True

    def stop(self):
        """Stops timer."""
        if self._timer is not None:
            self._timer.cancel()
        self.is_running = False


class Display:
    """
    Stores refined data of a display.

    Computes PPI if data is available. Stores non-negative translated offsets.
    """

    def __init__(self, monitor):
        self.resolution = (monitor.width, monitor.height)
        self.digital_offset = (monitor.x, monitor.y)
        if monitor.width_mm and monitor.height_mm:
            self.phys_size_mm = tuple(
                sorted(
                    [monitor.width_mm, monitor.height_mm],
                    reverse=bool(self.resolution[0] > self.resolution[1]),
                )
            )  # Take care that physical rotation matches resolution.
            self.phys_size_failed = False
        else:
            # if physical size detection has failed, assume display is 23" diagonal
            # to have it stand out
            self.phys_size_mm = tuple(
                sorted([509, 286], reverse=bool(self.resolution[0] > self.resolution[1]))
            )  # Take care that physical rotation matches resolution.
            self.phys_size_failed = True
        self.detected_phys_size_mm = self.phys_size_mm
        self.ppi = None
        self.ppi_norm_resolution = None
        self.ppi_norm_offset = None
        self.ppi_norm_bezels = (0, 0)
        self.perspective_angles = (0, 0)
        self.name = monitor.name
        if self.resolution and self.phys_size_mm:
            self.ppi = self.compute_ppi()

    def __str__(self):
        return (
            f"Display("
            f"resolution={self.resolution}, "
            f"digital_offset={self.digital_offset}, "
            f"phys_size_mm={self.phys_size_mm}, "
            f"detected_phys_size_mm={self.detected_phys_size_mm}, "
            f"ppi={self.ppi}, "
            f"ppi_norm_resolution={self.ppi_norm_resolution}, "
            f"ppi_norm_offset={self.ppi_norm_offset}, "
            f"ppi_norm_bezels={self.ppi_norm_bezels}, "
            f"perspective_angles={self.perspective_angles}, "
            f"name={self.name!r}"
            f")"
        )

    def __eq__(self, other):
        return bool(
            self.resolution == other.resolution
            and self.digital_offset == other.digital_offset
            and self.detected_phys_size_mm == other.detected_phys_size_mm
        )

    def __hash__(self):
        return hash((self.resolution, self.digital_offset, self.detected_phys_size_mm))

    def diagonal_size(self):
        diag_mm = math.sqrt(self.phys_size_mm[0] ** 2 + self.phys_size_mm[1] ** 2)
        diag_in = round(diag_mm / 25.4, 1)
        return (round(diag_mm), diag_in)

    def compute_ppi(self):
        if self.phys_size_mm[0]:
            ppmm_horiz = self.resolution[0] / self.phys_size_mm[0]
        else:
            if sp_logging.DEBUG:
                sp_logging.G_LOGGER.info("Display.compute_ppi: self.phys_size_mm[0] was 0.")
            return None
        if self.phys_size_mm[1]:
            ppmm_vert = self.resolution[1] / self.phys_size_mm[1]
        else:
            if sp_logging.DEBUG:
                sp_logging.G_LOGGER.info("Display.compute_ppi: self.phys_size_mm[1] was 0.")
            return None
        if abs(ppmm_horiz / ppmm_vert - 1) > 0.01 and sp_logging.DEBUG:
            sp_logging.G_LOGGER.info(
                "WARNING: Horizontal and vertical PPI do not match! hor: %s, ver: %s",
                ppmm_horiz * 25.4,
                ppmm_vert * 25.4,
            )
            sp_logging.G_LOGGER.info(str(self))
        return ppmm_horiz * 25.4  # inch has 25.4 times the pixels of a millimeter.

    def translate_offset(self, translate_tuple):
        """Move offset point by subtracting the input point.

        This takes the top left most corner of the canvas to (0,0)
        and retains relative offsets between displays as they should be.
        """
        old_offsets = self.digital_offset
        self.digital_offset = (
            old_offsets[0] - translate_tuple[0],
            old_offsets[1] - translate_tuple[1],
        )

    def ppi_and_physsize_from_diagonal_inch(self, diag_inch):
        """
        If physical size detection fails, it can be computed by
        asking the user to enter the diagonal dimension of the monitor
        in inches.
        """
        height_to_width_ratio = self.resolution[1] / self.resolution[0]
        phys_width_inch = diag_inch / math.sqrt(1 + height_to_width_ratio**2)
        phys_height_inch = height_to_width_ratio * phys_width_inch

        self.phys_size_mm = (phys_width_inch * 25.4, phys_height_inch * 25.4)
        self.ppi = self.resolution[0] / phys_width_inch

        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info(
                "Updated PPI = %s and phys_size_mm = %s based on diagonal size: %s inches",
                self.ppi,
                self.phys_size_mm,
                diag_inch,
            )
            sp_logging.G_LOGGER.info(str(self))


class DisplayLight:
    """Small class to store resolution and position data a kin to full Display."""

    def __init__(self, res, off, bez):
        self.resolution = res
        self.digital_offset = off
        if bez:
            self.ppi_norm_bezels = bez
        else:
            self.ppi_norm_bezels = (0, 0)

    def __str__(self):
        return (
            f"DisplayLight("
            f"resolution={self.resolution}, "
            f"digital_offset={self.digital_offset}, "
            f"ppi_norm_bezels={self.ppi_norm_bezels} "
            f")"
        )


class DisplaySystem:
    """
    Handle the display system as a whole, applying user data such as
    bezel corrections, offsets, physical layout, and produces
    resolutions and offsets that are used to set the wallpaper
    in advanced mode.
    """

    def __init__(self):
        self.disp_list = get_display_data()
        self.compute_ppinorm_resolutions()

        # Data
        self.use_user_diags = False
        self.use_perspective = True
        self.default_perspective = None
        self.perspective_dict = {}

        self.load_system()
        self.load_perspectives()

        # if user diags are not entered, tell about failed physical sizes
        global USER_TOLD_OF_PHYS_FAIL
        if not self.use_user_diags:
            for dsp in self.disp_list:
                if dsp.phys_size_failed and not USER_TOLD_OF_PHYS_FAIL:
                    msg = (
                        "Detection of the diagonal size of a display has failed. "
                        "It will show up as a 23 inch display in advanced mode. "
                        "Enter the correct diagonal size with the Override Detected "
                        "Sizes tool."
                    )
                    show_message_dialog(msg)
                    USER_TOLD_OF_PHYS_FAIL = True

    def __eq__(self, other):
        # return bool(tuple(self.disp_list) == tuple(other.disp_list))
        for dsp_1, dsp_2 in zip(self.disp_list, other.disp_list):
            if dsp_1 == dsp_2:
                continue
            else:
                return False
        return len(self.disp_list) == len(other.disp_list)

    def __hash__(self):
        return hash(tuple(self.disp_list))

    def max_ppi(self):
        """Return maximum pixel density."""
        return max([disp.ppi for disp in self.disp_list])

    def get_normalized_ppis(self):
        """Return list of PPI values normalized to the max_ppi."""
        max_ppi = self.max_ppi()
        return [disp.ppi / max_ppi for disp in self.disp_list]

    def compute_ppinorm_resolutions(self):
        """Update disp_list PPI density normalized sizes of the real resolutions."""
        rel_ppis = self.get_normalized_ppis()
        for r_ppi, dsp in zip(rel_ppis, self.disp_list):
            dsp.ppi_norm_resolution = (
                round(dsp.resolution[0] / r_ppi),
                round(dsp.resolution[1] / r_ppi),
            )

    def get_ppi_norm_crops(self, manual_offsets):
        """Returns list of ppi_norm crop tuples to cut from ppi_norm canvas.

        A valid crop is a 4-tuple: (left, top, right, bottom).
        """
        crops = []
        for dsp in self.disp_list:
            try:
                off = manual_offsets[self.disp_list.index(dsp)]
            except IndexError:
                off = (0, 0)
            left_top = (
                round(dsp.ppi_norm_offset[0] + off[0]),
                round(dsp.ppi_norm_offset[1] + off[1]),
            )
            right_btm = (
                round(dsp.ppi_norm_resolution[0]) + left_top[0],
                round(dsp.ppi_norm_resolution[1]) + left_top[1],
            )
            crops.append(left_top + right_btm)
        sp_logging.G_LOGGER.info("get_ppi_norm_offsets: %s", self.get_ppinorm_offsets())
        sp_logging.G_LOGGER.info("get_ppi_norm_crops: %s", crops)
        return crops

    def fits_in_column(self, disp, col):
        """Test if IN DEKSTOP RES the horiz center of disp is below the last disp in the col."""
        col_last_disp = col[-1]
        disp_cntr = (disp.digital_offset[0] + disp.digital_offset[0] + disp.resolution[0]) / 2  # (left+right)/2
        col_last_left = col_last_disp.digital_offset[0]
        col_last_right = col_last_disp.digital_offset[0] + col_last_disp.resolution[0]
        return bool(disp_cntr > col_last_left and disp_cntr < col_last_right)

    def column_size(self, col):
        width = max([dsp.ppi_norm_resolution[0] + dsp.ppi_norm_bezels[0] for dsp in col])
        height = sum([dsp.ppi_norm_resolution[1] + dsp.ppi_norm_bezels[1] for dsp in col])
        return (width, height)

    def compute_initial_preview_offsets(self):
        """
        Uses desktop layout data to arrange the displays in their
        physical dimensions in to horizontally centered columns and
        then concatenating these columns horizontally centered, with
        each columns width being that of the widest display in the
        column. Display list needs to be sorted so that displays in
        a column are together and then the columns progress left
        to right.

        Column composition is TESTED with resolution but column SIZES
        are in PPI normalized resolutions to reflect the physical sizes
        of the displays.
        """
        # Construct columns from disp_list
        columns = []
        work_col = []
        for dsp in self.disp_list:
            if work_col == []:
                work_col.append(dsp)
                if dsp == self.disp_list[-1]:
                    columns.append(work_col)
            else:
                if self.fits_in_column(dsp, work_col):
                    work_col.append(dsp)
                else:
                    columns.append(work_col)
                    work_col = [dsp]
                if dsp == self.disp_list[-1]:
                    columns.append(work_col)
            # print("columns", columns)
            # print("work_col", work_col)
        # print("columns done", columns)
        # for col in columns:
        # for dsp in col:
        # print(str(dsp))

        col_ids = [list(range(len(col))) for col in columns]
        # sort columns in place vertically in digital offset
        sorted_ids = []
        sorted_columns = []
        for ids, col in zip(col_ids, columns):
            # col.sort(key=lambda x: x.digital_offset[1])
            srt_id, srt_col = (list(t) for t in zip(*sorted(zip(ids, col), key=lambda pair: pair[1].digital_offset[1])))
            sorted_ids.append(srt_id)
            sorted_columns.append(srt_col)
        columns = sorted_columns

        # print("columns sorted", columns, "sorted_ids", sorted_ids)
        # for col in columns:
        # for dsp in col:
        # print(str(dsp))
        if columns == []:
            sp_logging.G_LOGGER.info("DisplaySystem column recostruction has failed completely. Trigger fallback.")
            columns = [[dsp] for dsp in self.disp_list]

        # Tile columns on to the plane with vertical centering
        col_sizes = []
        try:
            col_sizes = [self.column_size(col) for col in columns]
        except (ValueError, IndexError):
            sp_logging.G_LOGGER.info("Problem with column sizes. col_sizes: %s", col_sizes)
        # print("col_sizes", col_sizes)
        max_col_h = 0
        try:
            max_col_h = max([sz[1] for sz in col_sizes])
        except ValueError:
            sp_logging.G_LOGGER.info("There are no column sizes? col_sizes: %s", col_sizes)
        col_left_tops = []
        current_left = 0
        for sz in col_sizes:
            col_left_tops.append((current_left, round((max_col_h - sz[1]) / 2)))
            current_left += sz[0]
        # print("col_left_tops", col_left_tops)

        # Tile displays in columns onto the plane with horizontal centering
        # within the column. Anchor columns to col_left_tops.
        for col, col_anchor in zip(columns, col_left_tops):
            current_top = 0
            max_dsp_w = max([dsp.ppi_norm_resolution[0] + dsp.ppi_norm_bezels[0] for dsp in col])
            for dsp in col:
                dsp_w = dsp.ppi_norm_resolution[0] + dsp.ppi_norm_bezels[0]
                dsp.ppi_norm_offset = (
                    col_anchor[0] + round((max_dsp_w - dsp_w) / 2),
                    col_anchor[1] + current_top,
                )
                # print(dsp.ppi_norm_offset)
                current_top += dsp.ppi_norm_resolution[1] + dsp.ppi_norm_bezels[1]
        # Restore column order to the original order that matches self.disp_list and other sorts (kde).
        restored_columns = []
        for ids, col in zip(sorted_ids, columns):
            srt_id, srt_col = (list(t) for t in zip(*sorted(zip(ids, col), key=lambda pair: pair[0])))
            restored_columns.append(srt_col)
        columns = restored_columns

        # Update offsets to disp_list
        flattened_cols = [dsp for col in columns for dsp in col]
        for scope_dsp, dsp in zip(flattened_cols, self.disp_list):
            dsp.ppi_norm_offset = scope_dsp.ppi_norm_offset
        # print("PPI NORM RESOLUTIONS AND OFFSETS")
        # print([(dsp.ppi_norm_resolution, dsp.ppi_norm_offset) for dsp in self.disp_list])
        # sys.exit()

    def get_disp_list(self, use_ppi_norm=False):
        if use_ppi_norm:
            disp_l = []
            for dsp in self.disp_list:
                disp_l.append(DisplayLight(dsp.ppi_norm_resolution, dsp.ppi_norm_offset, dsp.ppi_norm_bezels))
            return disp_l
        else:
            disp_l = self.disp_list
            return disp_l

    def get_ppinorm_offsets(self):
        """Return ppi norm offsets."""
        pnoffs = []
        for dsp in self.disp_list:
            pnoffs.append(dsp.ppi_norm_offset)
        return pnoffs

    def get_persp_data(self, persp_name):
        """Return a dict of perspective settings."""
        if persp_name == "default":
            get_id = self.default_perspective
        else:
            get_id = persp_name
        if not get_id or get_id == "disabled" or get_id not in self.perspective_dict:
            return None
        return self.perspective_dict[get_id]

    def update_ppinorm_offsets(self, offsets, bezels_included=False):
        """Write ppi_norm resolution offsets as determined
        in the GUI into Displays."""
        for dsp, offs in zip(self.disp_list, offsets):
            dsp.ppi_norm_offset = offs

    def update_bezels(self, bezels_mm):
        """Update displays with new bezel sizes."""
        # test that input values are positive
        for bez_pair in bezels_mm:
            for bez in bez_pair:
                if bez < 0:
                    msg = f"Bezel thickness must be a non-negative number, {bez} was entered."
                    sp_logging.G_LOGGER.info(msg)
                    show_message_dialog(msg, "Error")
                    return 0
        # convert to normalized pixel units
        max_ppmm = self.max_ppi() / 25.4
        bezels_ppi_norm = [(bz[0] * max_ppmm, bz[1] * max_ppmm) for bz in bezels_mm]
        for bz_px, dsp in zip(bezels_ppi_norm, self.disp_list):
            dsp.ppi_norm_bezels = bz_px
            sp_logging.G_LOGGER.info("update_bezels: %s", bz_px)
        self.compute_initial_preview_offsets()
        return 1

    def bezels_in_mm(self):
        """Return list of bezel thicknesses in millimeters."""
        bezels_mm = []
        max_ppmm = self.max_ppi() / 25.4
        for dsp in self.disp_list:
            bezels_mm.append(
                (
                    round(dsp.ppi_norm_bezels[0] / max_ppmm, 2),
                    round(dsp.ppi_norm_bezels[1] / max_ppmm, 2),
                )
            )
        return bezels_mm

    def bezels_in_px(self):
        """Return list of bezel thicknesses in ppi norm px."""
        bezels = []
        for dsp in self.disp_list:
            bezels.append((dsp.ppi_norm_bezels[0], dsp.ppi_norm_bezels[1]))
        return bezels

    def update_display_diags(self, diag_inches, reset_offsets=True):
        """Overwrite detected display sizes with user input."""
        if diag_inches == "auto":
            self.use_user_diags = False
            for dsp in self.disp_list:
                dsp.phys_size_mm = dsp.detected_phys_size_mm
                dsp.ppi = dsp.compute_ppi()
            self.compute_ppinorm_resolutions()
            self.compute_initial_preview_offsets()
        else:
            self.use_user_diags = True
            for dsp, diag in zip(self.disp_list, diag_inches):
                dsp.ppi_and_physsize_from_diagonal_inch(diag)
            self.compute_ppinorm_resolutions()
            if reset_offsets:
                self.compute_initial_preview_offsets()

    def save_system(self):
        """Save the current DisplaySystem instance user given data
        in a central file (CONFIG_PATH/display_systems.dat).

        Data is saved with a DisplaySystem specific has as the key,
        and data saved include:
            - ppi_norm offsets which contain any given bezel thicknesses
            - bezel (bez+gap+bez) sizes for (right_b, bottom_b)
            - display diagonal sizes if any of them are manually changed
            - rotation angles of displays for perspective correction
        """
        archive_file = os.path.join(CONFIG_PATH, "display_systems.dat")
        instance_key = str(hash(self))

        # collect data for saving
        ppi_norm_offsets = []
        bezel_mms = self.bezels_in_mm()
        diagonal_inches = []
        use_perspective = self.use_perspective
        def_perspective = str(self.default_perspective)
        for dsp in self.disp_list:
            ppi_norm_offsets.append(dsp.ppi_norm_offset)
            diagonal_inches.append(dsp.diagonal_size()[1])
        if not self.use_user_diags:
            diagonal_inches = None

        # load previous configs if file is found
        config = configparser.ConfigParser()
        if os.path.exists(archive_file):
            config.read(archive_file)

        # entering data to config under instance_key
        config[instance_key] = {
            "ppi_norm_offsets": list_to_str(ppi_norm_offsets, item_len=2),
            "bezel_mms": list_to_str(bezel_mms, item_len=2),
            "user_diagonal_inches": list_to_str(diagonal_inches, item_len=1),
            "use_perspective": str(int(use_perspective)),
            "def_perspective": def_perspective,
        }

        sp_logging.G_LOGGER.info(
            "Saving DisplaySystem: key: %s, ppi_norm_offsets: %s, "
            "bezel_mms: %s, user_diagonal_inches: %s, "
            "use_perspective: %s, def_perspective: %s",
            instance_key,
            ppi_norm_offsets,
            bezel_mms,
            diagonal_inches,
            use_perspective,
            def_perspective,
        )

        # write config to file
        with open(archive_file, "w") as configfile:
            config.write(configfile)

        # Once profile is saved make it available for wallpaper setter
        refresh_display_data()

    def load_system(self):
        """Try to load system data from database based on initialization data,
        i.e. the Display list. If no pre-existing system is found, try to guess
        the system topology and update disp_list"""
        archive_file = os.path.join(CONFIG_PATH, "display_systems.dat")
        instance_key = str(hash(self))
        found_match = False

        # check if file exists and if the current key exists in it
        config = configparser.ConfigParser()
        if os.path.exists(archive_file):
            config.read(archive_file)
            sp_logging.G_LOGGER.info("config.sections: %s", config.sections())
            if instance_key in config:
                found_match = True
            else:
                sp_logging.G_LOGGER.info("load: system not found with hash %s", instance_key)
        else:
            sp_logging.G_LOGGER.info("load_system: archive_file not found: %s", archive_file)

        if found_match:
            # read values
            # and push them into self.disp_list
            instance_data = config[instance_key]
            ppi_norm_offsets = str_to_list(instance_data["ppi_norm_offsets"], item_len=2)
            bezel_mms = str_to_list(instance_data["bezel_mms"], item_len=2)
            if bezel_mms:
                bezel_mms = [(round(bez[0], 2), round(bez[1], 2)) for bez in bezel_mms]
            diagonal_inches = str_to_list(instance_data["user_diagonal_inches"], item_len=1)
            use_perspective = bool(int(instance_data.get("use_perspective", 0)))
            def_perspective = instance_data.get("def_perspective", "None")
            sp_logging.G_LOGGER.info(
                "DisplaySystem loaded: P.N.Offs: %s, "
                "bezel_mmṣ: %s, "
                "user_diagonal_inches: %s, "
                "use_perspective: %s, "
                "def_perspective: %s",
                ppi_norm_offsets,
                bezel_mms,
                diagonal_inches,
                use_perspective,
                def_perspective,
            )
            self.update_bezels(bezel_mms)
            self.update_ppinorm_offsets(ppi_norm_offsets)  # Bezels & user diagonals always included.
            if diagonal_inches:
                sp_logging.G_LOGGER.info("Updating diagonal_inches")
                self.update_display_diags(diagonal_inches, reset_offsets=False)
            self.use_perspective = use_perspective
            if def_perspective == "None":
                self.default_perspective = None
            else:
                self.default_perspective = def_perspective
        else:
            # Continue without data
            self.compute_initial_preview_offsets()

    def update_perspectives(self, persp_name, use_persp_master, is_ds_def, viewer_data, swivels, tilts):
        """Update perspective data.

        Common data across all profiles:
            - master toggle for perspective corrections

        Data types in a profile are:
            - index of central display
            - viewer's position relative to the center of the central display
                - lateral, vertical, depth
            - swivel data as a list over each display
                - axis in ["left", "right"]
                    - points up
                - angle
                    - sign with right hand rule
                - axis offset: (lateral, depth)
            - tilt data as a list over each display
                - angle (axis is the equator line of the display)
                    - axis points left
                    - sign with right hand rule
                - axis offset: (vertical, depth)
        """
        centr_disp, viewer_pos = viewer_data
        self.use_perspective = use_persp_master
        if is_ds_def and self.default_perspective != persp_name:
            self.default_perspective = persp_name
        elif not is_ds_def and self.default_perspective == persp_name:
            self.default_perspective = None
        self.save_system()

        if persp_name is not None:
            if persp_name not in self.perspective_dict:
                self.perspective_dict[persp_name] = {}
            self.perspective_dict[persp_name]["central_disp"] = centr_disp
            self.perspective_dict[persp_name]["viewer_pos"] = viewer_pos
            self.perspective_dict[persp_name]["swivels"] = swivels
            self.perspective_dict[persp_name]["tilts"] = tilts
        # trigger save afterwards (not here)

    def save_perspectives(self):
        """Save perspective data dict to file."""
        instance_key = str(hash(self))
        persp_file = os.path.join(CONFIG_PATH, instance_key + ".persp")

        # load previous configs if file is found
        config = configparser.ConfigParser()
        # if os.path.exists(persp_file):
        # config.read(persp_file)

        for sect in self.perspective_dict:
            config[sect] = {
                "central_disp": str(self.perspective_dict[sect]["central_disp"]),
                "viewer_pos": list_to_str(self.perspective_dict[sect]["viewer_pos"], item_len=1),
                "swivels": list_to_str(self.perspective_dict[sect]["swivels"], item_len=4),
                "tilts": list_to_str(self.perspective_dict[sect]["tilts"], item_len=3),
            }

        sp_logging.G_LOGGER.info("Saving perspective profs: %s", config.sections())

        # write config to file
        with open(persp_file, "w") as configfile:
            config.write(configfile)

    def load_perspectives(self):
        """Load perspective data dict from file."""
        instance_key = str(hash(self))
        persp_file = os.path.join(CONFIG_PATH, instance_key + ".persp")
        # check if file exists and load saved perspective dicts
        if os.path.exists(persp_file):
            config = configparser.ConfigParser()
            config.read(persp_file)
            sp_logging.G_LOGGER.info("Loading perspective profs: %s", config.sections())

            self.perspective_dict = {}
            for sect in config.sections():
                self.perspective_dict[sect] = {
                    "central_disp": int(config[sect]["central_disp"]),
                    "viewer_pos": str_to_list(config[sect]["viewer_pos"], item_len=1),
                    "swivels": str_to_list(config[sect]["swivels"], item_len=4, strings=True),
                    "tilts": str_to_list(config[sect]["tilts"], item_len=3),
                }
        else:
            pass

    # End DisplaySystem


def list_to_str(lst, item_len=1):
    """Format lists as ,(;) separated strings."""
    if item_len == 1:
        if lst:
            return ",".join(str(lst_itm) for lst_itm in lst)
        else:
            return "None"
    else:
        joined_items = []
        for sub_lst in lst:
            joined_items.append(",".join(str(sub_itm) for sub_itm in sub_lst))
        return ";".join(joined_items)


def str_to_list(joined_list, item_len=1, strings=False):
    """Extract list from joined_list."""
    if item_len == 1:
        if joined_list in [None, "None"]:
            return None
        split_list = joined_list.split(",")
        conv_list = []
        for item in split_list:
            try:
                val = int(item)
            except ValueError:
                try:
                    val = float(item)
                except ValueError:
                    val = item
                    if not strings:
                        sp_logging.G_LOGGER.info("str_to_list: ValueError: not int or float: %s", item)
            conv_list.append(val)
        return conv_list
    else:
        split_list = joined_list.split(";")
        conv_list = []
        for item in split_list:
            split_item = item.split(",")
            conv_item = []
            for sub_item in split_item:
                try:
                    val = int(sub_item)
                except ValueError:
                    try:
                        val = float(sub_item)
                    except ValueError:
                        val = sub_item
                        if not strings:
                            sp_logging.G_LOGGER.info("str_to_list: ValueError: not int or float: %s", sub_item)
                conv_item.append(val)
            conv_list.append(tuple(conv_item))
        return conv_list


def extract_global_vars(disp_list):
    res_arr = []
    off_arr = []
    for disp in disp_list:
        res_arr.append(disp.resolution)
        off_arr.append(disp.digital_offset)
    return [res_arr, off_arr]


def get_display_data():
    """
    Updates global display variables: number of displays, resolutions and offsets.

    Returns a list of Display objects, one for each monitor. Offsets are sanitized
    so that they are always non-negative.
    """
    # https://github.com/rr-/screeninfo
    global NUM_DISPLAYS, RESOLUTION_ARRAY, DISPLAY_OFFSET_ARRAY
    RESOLUTION_ARRAY = []
    DISPLAY_OFFSET_ARRAY = []
    monitors = get_monitors()
    while not monitors:
        monitors = get_monitors()
        sp_logging.G_LOGGER.info("Had to re-query for display data.")
    NUM_DISPLAYS = len(monitors)

    display_list = []
    for monitor in monitors:
        display_list.append(Display(monitor))
    # Check that there are no negative offsets and fix if any are found.
    leftmost_offset = min([disp.digital_offset[0] for disp in display_list])
    topmost_offset = min([disp.digital_offset[1] for disp in display_list])
    if leftmost_offset < 0 or topmost_offset < 0:
        for disp in display_list:
            disp.translate_offset((leftmost_offset, topmost_offset))
    # sort display list by digital offsets
    display_list.sort(key=lambda x: x.digital_offset)
    # extract global variables for legacy compatibility
    RESOLUTION_ARRAY, DISPLAY_OFFSET_ARRAY = extract_global_vars(display_list)

    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info(
            "get_display_data output: NUM_DISPLAYS = %s, RES_ARR = %s, OFF_ARR = %s",
            NUM_DISPLAYS,
            RESOLUTION_ARRAY,
            DISPLAY_OFFSET_ARRAY,
        )
        for disp in display_list:
            sp_logging.G_LOGGER.info(str(disp))
    return display_list


def refresh_display_data():
    global G_ACTIVE_DISPLAYSYSTEM
    G_ACTIVE_DISPLAYSYSTEM = DisplaySystem()


def compute_canvas(res_array, offset_array):
    """Computes the size of the total desktop area from monitor resolutions and offsets."""
    # Take the subtractions of right-most right - left-most left
    # and bottom-most bottom - top-most top (=0).
    leftmost = 0
    topmost = 0
    right_edges = []
    bottom_edges = []
    for res, off in zip(res_array, offset_array):
        right_edges.append(off[0] + res[0])
        bottom_edges.append(off[1] + res[1])
    # Right-most edge.
    rightmost = max(right_edges)
    # Bottom-most edge.
    bottommost = max(bottom_edges)
    canvas_size = [rightmost - leftmost, bottommost - topmost]
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info("Canvas size: %s", canvas_size)
    return canvas_size


def compute_ppi_corrected_res_array(res_array, ppi_list_rel_density):
    """Return ppi density normalized sizes of the real resolutions."""
    eff_res_array = []
    for i in range(len(res_array)):
        effw = round(res_array[i][0] / ppi_list_rel_density[i])
        effh = round(res_array[i][1] / ppi_list_rel_density[i])
        eff_res_array.append((effw, effh))
    return eff_res_array


# resize image to fill given rectangle and do a positioned crop to size.
# Return output image.
def resize_to_fill(
    img,
    res,
    quality: "str | Image.Resampling" = Image.Resampling.LANCZOS,
    zoom=1.0,
    offset=(0.0, 0.0),
):
    """Resize image to fill given rectangle and do a positioned crop to size.

    The image is always scaled so that it fully covers the target rectangle
    ``res`` (no letterboxing). ``zoom`` (>= 1.0) scales the image further in,
    cropping away more of the source. ``offset`` is an (x, y) pair in the range
    [-1.0, 1.0] that slides the crop window within the available overflow:
    0.0 keeps the default centered crop, -1.0 aligns to the left/top edge and
    +1.0 aligns to the right/bottom edge. The result always fills ``res``.
    """
    if quality == "fast":
        quality = Image.Resampling.HAMMING
        reducing_gap = 1.5
    else:
        quality = Image.Resampling.LANCZOS
        reducing_gap = None

    if img.mode != "RGB":
        img = img.convert("RGB")

    # Sanitize positioning parameters.
    try:
        zoom = float(zoom)
    except (TypeError, ValueError):
        zoom = 1.0
    if zoom < 1.0:
        zoom = 1.0
    try:
        offset_x = min(1.0, max(-1.0, float(offset[0])))
        offset_y = min(1.0, max(-1.0, float(offset[1])))
    except (TypeError, ValueError, IndexError):
        offset_x, offset_y = 0.0, 0.0

    image_size = img.size  # returns image (width,height)
    if image_size == res and zoom == 1.0 and offset_x == 0.0 and offset_y == 0.0:
        # input image is already of the correct size, no action needed.
        return img

    # Scale so the image at least covers the target rectangle (cover fit),
    # then apply the additional user zoom. Using max() of the edge ratios
    # guarantees coverage regardless of aspect ratios.
    cover_multiplier = max(res[0] / image_size[0], res[1] / image_size[1])
    resize_multiplier = cover_multiplier * zoom
    # Guarantee the scaled image is never smaller than the target on either
    # edge despite rounding, so the final crop always yields exactly res.
    new_size = (
        max(round(resize_multiplier * image_size[0]), res[0]),
        max(round(resize_multiplier * image_size[1]), res[1]),
    )
    img = img.resize(new_size, resample=quality, reducing_gap=reducing_gap)

    extra_width = new_size[0] - res[0]
    extra_height = new_size[1] - res[1]
    # offset 0.0 -> centered crop (extra/2); -1.0 -> 0; +1.0 -> extra.
    left = round(extra_width / 2 * (1 + offset_x))
    top = round(extra_height / 2 * (1 + offset_y))
    # Clamp the crop origin so the window stays fully inside the image.
    left = min(max(left, 0), extra_width)
    top = min(max(top, 0), extra_height)
    crop_tuple = (left, top, left + res[0], top + res[1])
    cropped_res = img.crop(crop_tuple)
    if cropped_res.size == res:
        return cropped_res
    else:
        sp_logging.G_LOGGER.info("Error: result image not of correct size. crp:%s, res:%s", cropped_res.size, res)
        return cropped_res


def get_center(res):
    """Computes center point of a resolution rectangle."""
    return (round(res[0] / 2), round(res[1] / 2))


def get_all_centers(resarr_eff, manual_offsets):
    """Computes center points of given resolution list taking into account their offsets."""
    centers = []
    sum_widths = 0
    # get the vertical pixel distance of the center of the left most display
    # from the top.
    center_standard_height = get_center(resarr_eff[0])[1]
    if len(manual_offsets) < len(resarr_eff):
        sp_logging.G_LOGGER.info(
            "get_all_centers: Not enough manual offsets: \
                                 %s for displays: %s",
            len(manual_offsets),
            len(resarr_eff),
        )
    else:
        for i in range(len(resarr_eff)):
            horiz_radius = get_horizontal_radius(resarr_eff[i])
            # here take the center height to be the same for all the displays
            # unless modified with the manual offset
            center_pos_from_anchor_left_top = (
                sum_widths + manual_offsets[i][0] + horiz_radius,
                center_standard_height + manual_offsets[i][1],
            )
            centers.append(center_pos_from_anchor_left_top)
            sum_widths += resarr_eff[i][0]
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info("centers: %s", centers)
    return centers


def get_lefttop_from_center(center, res):
    """Compute top left coordinate of a rectangle from its center."""
    return (center[0] - round(res[0] / 2), center[1] - round(res[1] / 2))


def get_rightbottom_from_lefttop(lefttop, res):
    """Compute right bottom corner of a rectangle from its left top."""
    return (lefttop[0] + res[0], lefttop[1] + res[1])


def get_horizontal_radius(res):
    """Returns half the width of the input rectangle."""
    return round(res[0] / 2)


def compute_crop_tuples(resolution_array_ppinormalized, manual_offsets):
    # Assume the centers of the physical displays are aligned on common
    # horizontal line. If this is not the case one must use the manual
    # offsets defined in the profile for adjustment (and bezel corrections).
    # Anchor positions to the top left corner of the left most display. If
    # its size is scaled up, one will need to adjust the horizontal positions
    # of all the displays. (This is automatically handled by using the
    # effective resolution array).
    # Additionally one must make sure that the highest point of the display
    # arrangement is at y=0.
    crop_tuples = []
    centers = get_all_centers(resolution_array_ppinormalized, manual_offsets)
    for center, res in zip(centers, resolution_array_ppinormalized):
        lefttop = get_lefttop_from_center(center, res)
        rightbottom = get_rightbottom_from_lefttop(lefttop, res)
        crop_tuples.append(lefttop + rightbottom)
    # Translate crops so that the highest point is at y=0 -- remember to add
    # translation to both top and bottom coordinates! Same horizontally.
    # Left-most edge of the crop tuples.
    leftmost = min(crop_tuples, key=itemgetter(0))[0]
    # Top-most edge of the crop tuples.
    topmost = min(crop_tuples, key=itemgetter(1))[1]
    if leftmost == 0 and topmost == 0:
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("crop_tuples: %s", crop_tuples)
        return crop_tuples  # [(left, up, right, bottom),...]
    else:
        crop_tuples_translated = translate_crops(crop_tuples, (leftmost, topmost))
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("crop_tuples_translated: %s", crop_tuples_translated)
        return crop_tuples_translated  # [(left, up, right, bottom),...]


def translate_crops(crop_tuples, translate_tuple):
    """Translate crop tuples to be over the image are, i.e. left top at (0,0)."""
    crop_tuples_translated = []
    for crop_tuple in crop_tuples:
        crop_tuples_translated.append(
            (
                crop_tuple[0] - translate_tuple[0],
                crop_tuple[1] - translate_tuple[1],
                crop_tuple[2] - translate_tuple[0],
                crop_tuple[3] - translate_tuple[1],
            )
        )
    return crop_tuples_translated


def compute_working_canvas(crop_tuples):
    """Computes effective size of the desktop are taking into account PPI/offsets/bezels."""
    # Take the subtractions of right-most right - left-most left
    # and bottom-most bottom - top-most top (=0).
    leftmost = 0
    topmost = 0
    # Right-most edge of the crop tuples.
    rightmost = max(crop_tuples, key=itemgetter(2))[2]
    # Bottom-most edge of the crop tuples.
    bottommost = max(crop_tuples, key=itemgetter(3))[3]
    canvas_size = [rightmost - leftmost, bottommost - topmost]
    return canvas_size


def alternating_outputfile(prof_name):
    """Return alternating output filename and old filename.

    This is done so that the cache doesn't become a huge dump of unused files,
    and it is alternating since some OSs don't update their wallpapers if the
    current image file is overwritten.
    """
    if IS_WINDOWS:
        ftype = "jpg"
    else:
        ftype = "png"
    outputfile = os.path.join(TEMP_PATH, prof_name + "-a." + ftype)
    if os.path.isfile(outputfile):
        outputfile_old = outputfile
        outputfile = os.path.join(TEMP_PATH, prof_name + "-b." + ftype)
    else:
        outputfile_old = os.path.join(TEMP_PATH, prof_name + "-b." + ftype)
    return (outputfile, outputfile_old)


def span_single_image_simple(profile, force):
    """
    Spans a single image across all monitors. No corrections.

    This simple method resizes the source image so it fills the whole
    desktop canvas. Since no corrections are applied, no offset dependent
    cuts are needed and so this should work on any monitor arrangement.
    """
    file = profile.next_wallpaper_files()[0]
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info(file)
    try:
        img = Image.open(file)
        img = ImageOps.exif_transpose(img)
    except UnidentifiedImageError:
        sp_logging.G_LOGGER.info(
            ("Opening image '%s' failed with PIL.UnidentifiedImageError.It could be corrupted or is of foreign type."),
            file,
        )
        return
    canvas_tuple = tuple(compute_canvas(RESOLUTION_ARRAY, DISPLAY_OFFSET_ARRAY))
    img_resize = resize_to_fill(img, canvas_tuple, zoom=profile.zoom, offset=profile.offsets)

    outputfile, outputfile_old = alternating_outputfile(profile.name)
    img_resize.save(outputfile, quality=95)  # set quality if jpg is used, png unaffected
    if profile.name == G_ACTIVE_PROFILE or force:
        set_wallpaper(outputfile, force, [file])
    if os.path.exists(outputfile_old):
        os.remove(outputfile_old)
    return 0


def group_persp_data(persp_dat, groups):
    """Rerturn list of grouped perspective data objects."""
    if not persp_dat:
        return [None] * len(groups)
    group_persp_data_list = []
    for grp in groups:
        group_data = {
            "central_disp": persp_dat["central_disp"],
            "viewer_pos": persp_dat["viewer_pos"],
            "swivels": [persp_dat["swivels"][index] for index in grp],
            "tilts": [persp_dat["tilts"][index] for index in grp],
        }
        group_persp_data_list.append(group_data)
    return group_persp_data_list


def translate_to_group_coordinates(group_crop_list):
    """Translates lists of group crops into groups internal coordinates."""
    if len(group_crop_list) == 1:
        return group_crop_list
    else:
        group_crop_list_transl = []
        for grp_crops in group_crop_list:
            left_anch = min([crp[0] for crp in grp_crops])
            top_anch = min([crp[1] for crp in grp_crops])
            transl_crops = []
            for crp in grp_crops:
                transl_crops.append((crp[0] - left_anch, crp[1] - top_anch, crp[2] - left_anch, crp[3] - top_anch))
            group_crop_list_transl.append(transl_crops)
        return group_crop_list_transl


# Take pixel densities of displays into account to have the image match
# physically between displays.
def span_single_image_advanced(profile, force):
    """
    Applies wallpaper using PPI, bezel, offset corrections.

    Further description todo.
    """
    files = profile.next_wallpaper_files()
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info(files)
    try:
        img_list = [Image.open(fil) for fil in files]
        img_list = [ImageOps.exif_transpose(img) for img in img_list]
    except UnidentifiedImageError:
        sp_logging.G_LOGGER.info(
            ("Opening image '%s' failed with PIL.UnidentifiedImageError.It could be corrupted or is of foreign type."),
            files,
        )
        return

    # Cropping now sections of the image to be shown, USE EFFECTIVE WORKING
    # SIZES. Also EFFECTIVE SIZE Offsets are now required.
    manual_offsets = profile.manual_offsets
    cropped_images = {}
    crop_tuples = G_ACTIVE_DISPLAYSYSTEM.get_ppi_norm_crops(manual_offsets)
    sp_logging.G_LOGGER.info(
        "G_A_DSYS.use_perspective: %s, prof.perspective: %s",
        G_ACTIVE_DISPLAYSYSTEM.use_perspective,
        profile.perspective,
    )
    persp_dat = None
    if G_ACTIVE_DISPLAYSYSTEM.use_perspective:
        persp_dat = G_ACTIVE_DISPLAYSYSTEM.get_persp_data(profile.perspective)

    if profile.spangroups:
        spangroups = profile.spangroups
    else:
        spangroups = [list(range(NUM_DISPLAYS))]

    grp_crop_tuples = translate_to_group_coordinates([[crop_tuples[index] for index in grp] for grp in spangroups])
    grp_res_array = [[RESOLUTION_ARRAY[index] for index in grp] for grp in spangroups]
    grp_persp_dat = group_persp_data(persp_dat, spangroups)

    for img, grp, grp_p_dat, grp_crops, grp_res_arr in zip(
        img_list, spangroups, grp_persp_dat, grp_crop_tuples, grp_res_array
    ):
        if persp_dat:
            proj_plane_crops, persp_coeffs = persp.get_backprojected_display_system(grp_crops, grp_p_dat)
            # Canvas containing back-projected displays
            canvas_tuple_proj = tuple(compute_working_canvas(proj_plane_crops))
            # Canvas containing ppi normalized displays
            canvas_tuple_trgt = tuple(compute_working_canvas(grp_crops))
            sp_logging.G_LOGGER.info("Back-projected canvas size: %s", canvas_tuple_proj)
            img_workingsize = resize_to_fill(img, canvas_tuple_proj, zoom=profile.zoom, offset=profile.offsets)
            for _crop_tup, coeffs, ppin_crop, (i_res, res) in zip(
                proj_plane_crops, persp_coeffs, grp_crops, enumerate(grp_res_arr)
            ):
                # Whole image needs to be transformed for each display separately
                # since the coeffs live between the full back-projected plane
                # containing all displays and the full 'target' working canvas
                # size canvas_tuple_trgt containing ppi normalized displays.
                persp_crop = img_workingsize.transform(
                    canvas_tuple_trgt, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC
                )
                ## persp_crop.save(str(canvas_tuple_trgt)+str(crop_tup), "PNG")
                # Crop desired region from transformed image which is now in
                # ppi normalized resolution
                crop_img = persp_crop.crop(ppin_crop)
                # Resize correct crop to actual display resolution
                crop_img = crop_img.resize(res, resample=Image.Resampling.LANCZOS)
                # cropped_images.append(crop_img) #old
                cropped_images[grp[i_res]] = crop_img
        else:
            # larger working size needed to fill all the normalized lower density
            # displays. Takes account manual offsets that might require extra space.
            canvas_tuple_eff = tuple(compute_working_canvas(grp_crops))
            # Image is now the height of the eff tallest display + possible manual
            # offsets and the width of the combined eff widths + possible manual
            # offsets.
            img_workingsize = resize_to_fill(img, canvas_tuple_eff, zoom=profile.zoom, offset=profile.offsets)
            # Simultaneously make crops at working size and then resize down to actual
            # resolution from RESOLUTION_ARRAY as needed.
            for crop_tup, (i_res, res) in zip(grp_crops, enumerate(grp_res_arr)):
                crop_img = img_workingsize.crop(crop_tup)
                if crop_img.size == res:
                    # cropped_images.append(crop_img)
                    cropped_images[grp[i_res]] = crop_img
                else:
                    crop_img = crop_img.resize(res, resample=Image.Resampling.LANCZOS)
                    # cropped_images.append(crop_img)
                    cropped_images[grp[i_res]] = crop_img
    # Combine crops to a single canvas of the size of the actual desktop
    # actual combined size of the display resolutions
    canvas_tuple_fin = tuple(compute_canvas(RESOLUTION_ARRAY, DISPLAY_OFFSET_ARRAY))
    combined_image = Image.new("RGB", canvas_tuple_fin, color=0)
    combined_image.load()
    # for i in range(len(cropped_images)):
    # combined_image.paste(cropped_images[i], DISPLAY_OFFSET_ARRAY[i])
    for crp_id in cropped_images:
        combined_image.paste(cropped_images[crp_id], DISPLAY_OFFSET_ARRAY[crp_id])

    # Saving combined image
    outputfile, outputfile_old = alternating_outputfile(profile.name)
    combined_image.save(outputfile, quality=95)  # set quality if jpg is used, png unaffected
    if profile.name == G_ACTIVE_PROFILE or force:
        set_wallpaper(outputfile, force, files)
    if os.path.exists(outputfile_old):
        os.remove(outputfile_old)
    return 0


def set_multi_image_wallpaper(profile, force):
    """Sets a distinct image on each monitor.

    Since most platforms only support setting a single image
    as the wallpaper this has to be accomplished by creating a
    composite image based on the monitor offsets and then setting
    the resulting image as the wallpaper.
    """
    files = profile.next_wallpaper_files()
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info(str(files))
    img_resized = []
    for file, res in zip(files, RESOLUTION_ARRAY):
        # image = Image.open(file)
        try:
            image = Image.open(file)
            image = ImageOps.exif_transpose(image)
        except UnidentifiedImageError:
            sp_logging.G_LOGGER.info(
                (
                    "Opening image '%s' failed with PIL.UnidentifiedImageError."
                    "It could be corrupted or is of foreign type."
                ),
                file,
            )
            return
        img_resized.append(resize_to_fill(image, res, zoom=profile.zoom, offset=profile.offsets))
    canvas_tuple = tuple(compute_canvas(RESOLUTION_ARRAY, DISPLAY_OFFSET_ARRAY))
    combined_image = Image.new("RGB", canvas_tuple, color=0)
    combined_image.load()
    for i in range(len(files)):
        combined_image.paste(img_resized[i], DISPLAY_OFFSET_ARRAY[i])

    outputfile, outputfile_old = alternating_outputfile(profile.name)
    combined_image.save(outputfile, quality=95)  # set quality if jpg is used, png unaffected
    if profile.name == G_ACTIVE_PROFILE or force:
        set_wallpaper(outputfile, force, files)
    if os.path.exists(outputfile_old):
        os.remove(outputfile_old)
    return 0


# def errcheck(result, func, args):
#     """Error getter for Windows."""
#     if not result:
#         raise ctypes.WinError(ctypes.get_last_error())


def set_wallpaper(outputfile, force=False, source_files=None):
    """
    Master method to set the composed image as wallpaper.

    After the final background image is created, this method
    is called to communicate with the host system to set the
    desktop background. For Linux hosts there is a separate method.
    """
    if IS_WINDOWS:
        set_wallpaper_win(outputfile)
    # Old wallpaper setting code with no transition
    #         spi_setdeskwallpaper = 20
    #         spif_update_ini_file = 1
    #         spif_send_change = 2
    #         user32 = ctypes.WinDLL('user32', use_last_error=True)
    #         spiw = user32.SystemParametersInfoW
    #         spiw.argtypes = [
    #             ctypes.c_uint,
    #             ctypes.c_uint,
    #             ctypes.c_void_p,
    #             ctypes.c_uint]
    #         spiw.restype = ctypes.c_int
    #         spiw.errcheck = errcheck
    #         spi_success = spiw(
    #             spi_setdeskwallpaper,
    #             0,
    #             outputfile,
    #             spif_update_ini_file | spif_send_change)
    #         if spi_success == 0:
    #             sp_logging.G_LOGGER.info("SystemParametersInfo wallpaper set failed with \
    # spi_success: '%s'", spi_success)
    elif IS_LINUX:
        set_wallpaper_linux(outputfile, force)
    elif IS_MACOS:
        # script = """/usr/bin/osascript<<END
        #             tell application "Finder"
        #             set desktop picture to POSIX file "%s"
        #             end tell
        #             END"""
        # subprocess.Popen(script % outputfile, shell=True)
        set_wallpaper_macos(outputfile, image_piece_list=None, force=force)
    else:
        sp_logging.G_LOGGER.info("Unknown platform: %s", sys.platform)
    script_file = os.path.join(CONFIG_PATH, "run-after-wp-change.py")
    if os.path.isfile(script_file):
        subprocess.run(["python3", script_file, str(outputfile), str(source_files)])
    return 0


def set_wallpaper_macos(outputfile, image_piece_list=None, force=False):
    """
    MacOS has a separate desktop for each screen, each of which has their own
    background image property. This means that the wallpaper has to be set
    piece-by-piece.

    The list of screens given by NSScreen is not sorted by coordinates so
    that must be done first.

    https://developer.apple.com/documentation/appkit/nsscreen/1388393-screens
    https://developer.apple.com/documentation/appkit/nsworkspace/1527228-setdesktopimageurl
    https://developer.apple.com/documentation/foundation/url
    """
    screens = NSScreen.screens()

    # get screen positions on desktop
    screen_coords = []
    for scrn in screens:
        frm: Any = scrn.frame
        if callable(frm):
            frm = frm()
        screen_coords.append((int(frm.origin.x), int(frm.origin.y)))

    # sort screens by their desktop coords
    screens_and_coords = list(zip(screens, screen_coords))
    screens_and_coords.sort(key=lambda x: x[1])
    sorted_screens = [sac[0] for sac in screens_and_coords]

    # image cropper to get image list
    profname = None
    if outputfile:
        profname = os.path.splitext(os.path.basename(outputfile))[0][:-2]
        img_names = special_image_cropper(outputfile)
    elif not outputfile and image_piece_list:
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("KDE: Using image piece list!")
        img_names = image_piece_list
    else:
        sp_logging.G_LOGGER.info("Error! macOS wallpaper setter called without arguments!")
        return
    img_piece_urls = [NSURL.fileURLWithPath_(imagepath) for imagepath in img_names]

    # zip screens and image list and loop over setting the images using the shared workspace
    sharedSpace = NSWorkspace.sharedWorkspace()
    options = {}
    if profname == G_ACTIVE_PROFILE or image_piece_list or force:
        for screen, imgurl in zip(sorted_screens, img_piece_urls):
            (result, error) = sharedSpace.setDesktopImageURL_forScreen_options_error_(imgurl, screen, options, None)
            if error:
                sp_logging.G_LOGGER.info("setDesktopImageURL failed with error: %s", error)

    # Delete old images after new ones are set
    if outputfile:
        remove_old_temp_files(outputfile)


def set_wallpaper_linux(outputfile, force=False):
    """
    Wallpaper setter for Linux hosts.

    Functionality is based on the DESKTOP_SESSION environment variable,
    if it is not set, like often on window managers such as i3, the default
    behavior is to attempt to use feh as the communication layer with the
    desktop.

    On systems where the variable is set, a native way of setting the
    wallpaper can be used. These are DE specific.
    """
    sp_logging.G_LOGGER.info("set_wallpaper_linux: Starting for file: %s", outputfile)
    file = "file://" + outputfile
    set_command = G_SET_COMMAND_STRING
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info(file)

    desk_env = os.environ.get("DESKTOP_SESSION")
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info("DESKTOP_SESSION is: '%s'", desk_env)

    if set_command != "":
        if set_command == "feh":
            sp_logging.G_LOGGER.info("Using 'feh' command mode!")
            subprocess.run(["feh", "--bg-scale", "--no-xinerama", outputfile])
        else:
            command_string_list = set_command.split()
            formatted_command = []
            for term in command_string_list:
                formatted_command.append(term.format(image=outputfile))
            sp_logging.G_LOGGER.info("Formatted custom command is: '%s'", formatted_command)
            subprocess.run(formatted_command)
    if desk_env:
        if desk_env in [
            "gnome",
            "gnome-wayland",
            "gnome-xorg",
            "unity",
            "ubuntu",
            "pantheon",
            "budgie-desktop",
            "pop",
            "zorin",
        ]:
            subprocess.run(
                [
                    "/usr/bin/gsettings",
                    "set",
                    "org.gnome.desktop.background",
                    "picture-uri-dark",
                    file,
                ]
            )
            subprocess.run(["/usr/bin/gsettings", "set", "org.gnome.desktop.background", "picture-uri", file])
        elif desk_env in ["cinnamon"] or "cinnamon" in desk_env.lower():
            subprocess.run(
                [
                    "/usr/bin/gsettings",
                    "set",
                    "org.cinnamon.desktop.background",
                    "picture-uri",
                    file,
                ]
            )
        elif desk_env in ["mate"]:
            subprocess.run(["/usr/bin/gsettings", "set", "org.mate.background", "picture-filename", outputfile])
        elif desk_env in ["xfce", "xubuntu", "ubuntustudio"]:
            xfce_actions(outputfile)
        elif desk_env.lower() == "lubuntu" or "lxqt" in desk_env.lower():
            try:
                subprocess.run(["pcmanfm", "-w", outputfile])
            except OSError:
                try:
                    subprocess.run(["pcmanfm-qt", "-w", outputfile])
                except OSError:
                    sp_logging.G_LOGGER.info(
                        "Exception: failure to find either command \
'pcmanfm' or 'pcmanfm-qt'. Exiting."
                    )
                    sys.exit(1)
        # elif desk_env in ["/usr/share/xsessions/plasma", "plasma"]:
        elif running_kde():
            kdeplasma_actions(outputfile, force=force, profile_name=G_ACTIVE_PROFILE)
        elif "i3" in desk_env or desk_env in ["/usr/share/xsessions/bspwm"]:
            subprocess.run(["feh", "--bg-scale", "--no-xinerama", outputfile])
        else:
            if set_command == "":
                message = "Your DE could not be detected to set the wallpaper. \
You need to set the 'set_command' option in your \
settings file superpaper/general_settings. Exiting."
                sp_logging.G_LOGGER.info(message)
                show_message_dialog(message, "Error")
                sys.exit(1)
            else:
                os.system(set_command.format(image=outputfile))  # ty:ignore[deprecated]
    else:
        if running_kde():
            kdeplasma_actions(outputfile, force=force, profile_name=G_ACTIVE_PROFILE)
        elif set_command == "":
            sp_logging.G_LOGGER.info(
                "DESKTOP_SESSION variable is empty, \
attempting to use feh to set the wallpaper."
            )
            subprocess.run(["feh", "--bg-scale", "--no-xinerama", outputfile])


def set_wallpaper_piecewise(image_piece_list):
    """
    Wallpaper setter that takes already cropped images and sets them
    directly to corresponding monitors on systems where wallpapers
    are set on a monitor by monitor basis.

    This is used when the quick wallpaper change conditions are met,
    see quick_profile_job method, to improve performance on these
    systems.

    Currently supported such systems are KDE Plasma and XFCE.
    """
    if IS_LINUX:
        if running_kde():
            kdeplasma_actions(None, image_piece_list, profile_name=G_ACTIVE_PROFILE)
        # desk_env = os.environ.get("DESKTOP_SESSION")
        # elif desk_env in ["xfce", "xubuntu", "ubuntustudio"]:
        # xfce_actions(None, image_piece_list)
    elif IS_MACOS:
        set_wallpaper_macos(None, image_piece_list=image_piece_list)
    else:
        pass
    return 0


def special_image_cropper(outputfile):
    """
    Crops input image into monitor specific pieces based on display offsets.

    This is needed on systems where the wallpapers are set on a per display basis.
    This means that the composed image needs to be re-cut into pieces which
    are saved separately.
    """
    # file needs to be split into monitor pieces since KDE/XFCE are special
    img = Image.open(outputfile)
    outputname = os.path.splitext(outputfile)[0]
    img_names = []
    for crop_id, (res, offset) in enumerate(zip(RESOLUTION_ARRAY, DISPLAY_OFFSET_ARRAY)):
        left = offset[0]
        top = offset[1]
        right = left + res[0]
        bottom = top + res[1]
        crop_tuple = (left, top, right, bottom)
        cropped_img = img.crop(crop_tuple)
        fname = outputname + "-crop-" + str(crop_id) + ".png"
        img_names.append(fname)
        cropped_img.save(fname, "PNG")
    return img_names


def remove_old_temp_files(outputfile):
    """
    This method looks for previous temp images and deletes them.

    Currently only used to delete the monitor specific crops that are
    needed for KDE and XFCE.
    """
    opbase = os.path.basename(outputfile)
    opname = os.path.splitext(opbase)[0]
    # print(opname)
    oldfileid = ""
    if opname.endswith("-a"):
        oldfileid = "-b"
        # print(oldfileid)
    elif opname.endswith("-b"):
        oldfileid = "-a"
        # print(oldfileid)
    else:
        pass
    if oldfileid:
        # Must take care than only temps of current profile are deleted.
        profilename = opname.strip()[:-2]
        match_string = profilename + oldfileid + "-crop"
        match_string = match_string.strip()
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("Removing images matching with: '%s'", match_string)
        for temp_file in os.listdir(TEMP_PATH):
            if match_string in temp_file:
                # print(temp_file)
                os.remove(os.path.join(TEMP_PATH, temp_file))


def _escape_js_string(s):
    """Escape a string for safe embedding in a JavaScript string literal."""
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("'", "\\'")
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    return s


def _get_qdbus_cmd():
    """Return the available qdbus command name (qdbus6 for Plasma 6, qdbus otherwise)."""
    for cmd in ("qdbus6", "qdbus"):
        if shutil.which(cmd):
            return cmd
    return None


def get_kde_activity_mapping():
    """Get mapping of activity IDs to activity names."""
    try:
        qdbus = _get_qdbus_cmd()
        if not qdbus:
            sp_logging.G_LOGGER.error("Neither qdbus6 nor qdbus found")
            return {}
        # Get list of activity IDs
        result = subprocess.run(
            [qdbus, "org.kde.ActivityManager", "/ActivityManager/Activities", "ListActivities"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {}

        activity_ids = result.stdout.strip().split("\n")
        activity_map = {}

        # Get name for each activity
        for activity_id in activity_ids:
            if activity_id:
                result = subprocess.run(
                    [
                        qdbus,
                        "org.kde.ActivityManager",
                        "/ActivityManager/Activities",
                        "ActivityName",
                        activity_id,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    activity_name = result.stdout.strip()
                    activity_map[activity_id] = activity_name

        sp_logging.G_LOGGER.info("KDE Activities found: %s", activity_map)
        return activity_map
    except Exception as e:
        sp_logging.G_LOGGER.error("Failed to get KDE activities: %s", e)
        return {}


def kde_load_desktop_mapping_cache():
    """Load cached desktop-to-activity mapping from file."""
    cache_file = os.path.join(CONFIG_PATH, "kde_desktop_mapping.json")
    try:
        if os.path.isfile(cache_file):
            with open(cache_file) as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    sp_logging.G_LOGGER.warning("Invalid cache format, expected dict, got %s", type(data).__name__)
                    return {}
                result = {}
                for k, v in data.items():
                    try:
                        result[int(k)] = str(v)
                    except (ValueError, TypeError):
                        sp_logging.G_LOGGER.warning("Skipping invalid cache entry: %s -> %s", k, v)
                return result
    except (json.JSONDecodeError, OSError) as e:
        sp_logging.G_LOGGER.error("Failed to load desktop mapping cache: %s", e)
    return {}


def kde_save_desktop_mapping_cache(mapping):
    """Save desktop-to-activity mapping to file."""
    cache_file = os.path.join(CONFIG_PATH, "kde_desktop_mapping.json")
    try:
        with open(cache_file, "w") as f:
            json.dump(mapping, f, indent=2)
        sp_logging.G_LOGGER.info("Saved desktop mapping cache to %s", cache_file)
    except Exception as e:
        sp_logging.G_LOGGER.error("Failed to save desktop mapping cache: %s", e)


def kde_get_desktop_to_activity_mapping():
    """
    Query KDE to get which desktop containment belongs to which activity.
    Returns dict mapping desktop_id -> activity_id

    This function builds up knowledge progressively. Each time it's called,
    it knows for certain which desktops belong to the CURRENT activity,
    and uses cached information for other activities.
    """
    try:
        # Load cached mapping
        desktop_to_activity = kde_load_desktop_mapping_cache()

        qdbus = _get_qdbus_cmd()
        if not qdbus:
            sp_logging.G_LOGGER.error("Neither qdbus6 nor qdbus found")
            return desktop_to_activity

        # Get list of all activities
        result = subprocess.run(
            [qdbus, "org.kde.ActivityManager", "/ActivityManager/Activities", "ListActivities"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return desktop_to_activity

        activity_ids = [a.strip() for a in result.stdout.strip().split("\n") if a.strip()]

        # Get current activity
        result = subprocess.run(
            [qdbus, "org.kde.ActivityManager", "/ActivityManager/Activities", "CurrentActivity"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        current_activity_id = result.stdout.strip() if result.returncode == 0 else None

        # Query plasma shell for desktop containment information
        script = """
var allDesktops = desktops();
var result = [];
for(var i = 0; i < allDesktops.length; i++) {
    result.push(allDesktops[i].id + ',' + allDesktops[i].screen);
}
print(result.join(';'));
"""

        sessionb = dbus.SessionBus()
        plasma_interface = dbus.Interface(
            sessionb.get_object("org.kde.plasmashell", "/PlasmaShell"),
            dbus_interface="org.kde.PlasmaShell",
        )

        desktop_info = plasma_interface.evaluateScript(script)
        sp_logging.G_LOGGER.info("Desktop info from plasma: %s", desktop_info)

        # Parse desktop info: "id,screen;id,screen;..."
        all_desktop_ids = []
        active_desktop_ids = []
        if desktop_info:
            for item in desktop_info.split(";"):
                if "," in item:
                    parts = item.split(",")
                    desktop_id = int(parts[0])
                    screen_id = int(parts[1])
                    all_desktop_ids.append(desktop_id)
                    if screen_id != -1:
                        active_desktop_ids.append(desktop_id)

        if not active_desktop_ids or not current_activity_id:
            sp_logging.G_LOGGER.error("Could not determine active desktops or current activity")
            return desktop_to_activity

        # Update mapping: the active desktops definitely belong to the current activity
        mapping_updated = False
        for desktop_id in active_desktop_ids:
            if desktop_to_activity.get(desktop_id) != current_activity_id:
                desktop_to_activity[desktop_id] = current_activity_id
                mapping_updated = True

        # For any desktops we don't know about yet, make educated guesses
        # based on the number of screens and activity count
        unmapped_desktop_ids = [d for d in all_desktop_ids if d not in desktop_to_activity]
        if unmapped_desktop_ids and len(activity_ids) > 1:
            other_activities = [a for a in activity_ids if a != current_activity_id]
            num_screens = len(active_desktop_ids)

            for idx, desktop_id in enumerate(unmapped_desktop_ids):
                activity_idx = idx // num_screens
                if activity_idx < len(other_activities):
                    desktop_to_activity[desktop_id] = other_activities[activity_idx]
                    mapping_updated = True

        # Save updated mapping
        if mapping_updated:
            kde_save_desktop_mapping_cache(desktop_to_activity)

        sp_logging.G_LOGGER.info("Current activity: %s", current_activity_id)
        sp_logging.G_LOGGER.info("Active desktops: %s", active_desktop_ids)
        sp_logging.G_LOGGER.info("Desktop to activity mapping: %s", desktop_to_activity)
        return desktop_to_activity

    except Exception as e:
        sp_logging.G_LOGGER.error("Failed to get desktop-activity mapping: %s", e)
        sp_logging.G_LOGGER.error(traceback.format_exc())
        return {}


def kde_set_activity_wallpapers(activity_wallpapers_map):
    """
    Set wallpapers for specific activities in KDE Plasma.

    Args:
        activity_wallpapers_map: dict mapping activity_id -> list of image file paths
    """
    if not activity_wallpapers_map:
        sp_logging.G_LOGGER.info("No activity wallpapers to set")
        return

    # Get desktop-to-activity mapping
    desktop_to_activity = kde_get_desktop_to_activity_mapping()
    if not desktop_to_activity:
        sp_logging.G_LOGGER.error("Failed to get desktop-activity mapping, cannot set wallpapers")
        return

    # Build mapping as JavaScript: desktop_id -> [images]
    desktop_images_js = "{\n"
    for desktop_id, activity_id in desktop_to_activity.items():
        if activity_id in activity_wallpapers_map:
            images = activity_wallpapers_map[activity_id]
            file_urls = ["file://" + img for img in images]
            images_str = ", ".join('"' + _escape_js_string(url) + '"' for url in file_urls)
            desktop_images_js += f"    {desktop_id}: [{images_str}],\n"
    desktop_images_js += "}"

    script = (
        """
var desktopImagesMap = """
        + desktop_images_js
        + """;

// Get all desktops
var allDesktops = desktops();

// Get currently active desktops to determine screen order
var activeDesktops = [];
for(var idx = 0; idx < allDesktops.length; idx++) {
    if(allDesktops[idx].screen != -1) {
        activeDesktops.push(allDesktops[idx]);
    }
}

// Sort active desktops by position (vertical then horizontal)
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

// Create screen ID list from sorted active desktops
var screenOrder = [];
for(var k = 0; k < activeDesktops.length; k++) {
    screenOrder.push(activeDesktops[k].screen);
}

// Apply wallpapers to each desktop based on its ID
for(var idx = 0; idx < allDesktops.length; idx++) {
    var desktop = allDesktops[idx];
    var desktopId = desktop.id;

    // Check if we have wallpapers for this desktop
    if(desktopImagesMap[desktopId]) {
        var imageArray = desktopImagesMap[desktopId];
        var screenId = desktop.screen;

        // For inactive desktops, infer screen from desktop index
        if(screenId == -1 && screenOrder.length > 0) {
            screenId = screenOrder[idx % screenOrder.length];
        }

        // Find which image index to use for this screen
        var imageIndex = -1;
        for(var s = 0; s < screenOrder.length; s++) {
            if(screenOrder[s] == screenId) {
                imageIndex = s;
                break;
            }
        }

        // Set wallpaper if we found a valid image for this screen
        if(imageIndex >= 0 && imageIndex < imageArray.length) {
            desktop.wallpaperPlugin = "org.kde.image";
            desktop.currentConfigGroup = Array("Wallpaper", "org.kde.image", "General");
            desktop.writeConfig("Image", imageArray[imageIndex]);
        }
    }
}

// Reload config for all desktops
for(var idx = 0; idx < allDesktops.length; idx++) {
    allDesktops[idx].reloadConfig();
}
"""
    )

    try:
        sp_logging.G_LOGGER.info("kde_set_activity_wallpapers: Creating dbus connection")
        sessionb = dbus.SessionBus()
        plasma_interface = dbus.Interface(
            sessionb.get_object("org.kde.plasmashell", "/PlasmaShell"),
            dbus_interface="org.kde.PlasmaShell",
        )

        sp_logging.G_LOGGER.info("kde_set_activity_wallpapers: Evaluating KDE script")
        plasma_interface.evaluateScript(script)
        sp_logging.G_LOGGER.info("kde_set_activity_wallpapers: Script evaluation complete")
    except Exception as e:
        sp_logging.G_LOGGER.error("kde_set_activity_wallpapers failed: %s", e)
        sp_logging.G_LOGGER.error(traceback.format_exc())


def kdeplasma_actions(outputfile, image_piece_list=None, force=False, profile_name=None):
    """
    Sets the multi monitor wallpaper on KDE.

    Arguments are path to an image and an optional image piece
    list when one can set the wallpaper from existing cropped
    images. IF image pieces are to be used, call this method
    with outputfile == None.

    If profile_name is provided and matches an activity name, wallpapers
    are set for that specific activity. Otherwise, sets for all activities
    based on profile name matching.

    This is needed since KDE uses its own scripting language to
    set the desktop background which sets a single image on every
    monitor. This means that the composed image must be cut into
    correct pieces that then are set to their respective displays.
    """

    # Check if we should use activity-aware wallpaper setting
    activity_map = get_kde_activity_mapping()
    if activity_map:
        # Build wallpapers for all activities based on matching profiles
        activity_wallpapers = {}

        # Get the current profile's images
        if outputfile and os.path.isfile(outputfile):
            current_img_names = special_image_cropper(outputfile)
        elif image_piece_list:
            current_img_names = image_piece_list
        else:
            current_img_names = None

        # Match each activity to a profile
        for act_id, act_name in activity_map.items():
            # Check if this activity matches the current profile
            if profile_name and act_name == profile_name and current_img_names:
                activity_wallpapers[act_id] = current_img_names
                sp_logging.G_LOGGER.info("Activity '%s' matched profile '%s'", act_name, profile_name)
            else:
                # Try to find existing temp files for a profile matching this activity name
                matching_files = [
                    i
                    for i in os.listdir(TEMP_PATH)
                    if os.path.isfile(os.path.join(TEMP_PATH, i)) and i.startswith(act_name + "-") and "-crop-" in i
                ]

                if matching_files:
                    matching_files.sort()
                    full_paths = [os.path.join(TEMP_PATH, f) for f in matching_files]
                    activity_wallpapers[act_id] = full_paths
                    sp_logging.G_LOGGER.info(
                        "Activity '%s' using cached wallpapers from profile '%s'",
                        act_name,
                        act_name,
                    )
                elif current_img_names:
                    # No matching profile found, use current profile as fallback
                    activity_wallpapers[act_id] = current_img_names
                    sp_logging.G_LOGGER.info(
                        "Activity '%s' using fallback wallpapers from profile '%s'",
                        act_name,
                        profile_name,
                    )

        # Apply wallpapers to all activities at once
        if activity_wallpapers:
            kde_set_activity_wallpapers(activity_wallpapers)

            # Clean up old temp files
            if outputfile:
                remove_old_temp_files(outputfile)
            return

    script = """
var imageFileArray = Array({imagelist});

// Get all desktops across all activities
var allDesktops = desktops();

// First, identify the screen order from currently active desktops
var activeDesktops = [];
for(var idx = 0; idx < allDesktops.length; idx++) {{
    if(allDesktops[idx].screen != -1) {{
        activeDesktops.push(allDesktops[idx]);
    }}
}}

// Sort active desktops by screen position (vertical then horizontal)
var i = 1;
while(i < activeDesktops.length) {{
    var j = i;
    while(j > 0 && screenGeometry(activeDesktops[j-1].screen).top > screenGeometry(activeDesktops[j].screen).top) {{
        var temp = activeDesktops[j];
        activeDesktops[j] = activeDesktops[j-1];
        activeDesktops[j-1] = temp;
        j = j-1;
    }}
    i = i+1;
}}

i = 1;
while(i < activeDesktops.length) {{
    var j = i;
    while(j > 0 && screenGeometry(activeDesktops[j-1].screen).left > screenGeometry(activeDesktops[j].screen).left) {{
        var temp = activeDesktops[j];
        activeDesktops[j] = activeDesktops[j-1];
        activeDesktops[j-1] = temp;
        j = j-1;
    }}
    i = i+1;
}}

// Create mapping: screen id -> image index
var screenToImageIndex = {{}};
for(var k = 0; k < activeDesktops.length && k < imageFileArray.length; k++) {{
    screenToImageIndex[activeDesktops[k].screen] = k;
}}

// Now apply wallpapers to ALL desktops (including inactive activities)
// Each desktop remembers its screen assignment even when inactive
for(var idx = 0; idx < allDesktops.length; idx++) {{
    var desktop = allDesktops[idx];
    var screenId = desktop.screen;

    // For inactive desktops (screen == -1), try to infer screen from desktop index
    // In KDE, desktops are typically ordered: activity0_screen0, activity0_screen1, etc.
    if(screenId == -1) {{
        // Estimate screen based on position in desktop list
        // This assumes desktops are in order within each activity
        var numScreens = activeDesktops.length;
        if(numScreens > 0) {{
            screenId = idx % numScreens;
        }}
    }}

    // Look up which image to use for this screen
    var imageIndex = screenToImageIndex[screenId];
    if(imageIndex !== undefined && imageIndex < imageFileArray.length) {{
        desktop.wallpaperPlugin = "org.kde.image";
        desktop.currentConfigGroup = Array("Wallpaper", "org.kde.image", "General");
        desktop.writeConfig("Image", imageFileArray[imageIndex]);
    }}
}}

// Reload config for all desktops
for(var idx = 0; idx < allDesktops.length; idx++) {{
    allDesktops[idx].reloadConfig();
}}
"""
    profname = None
    if outputfile:
        profname = os.path.splitext(os.path.basename(outputfile))[0][:-2]
        img_names = special_image_cropper(outputfile)
    elif not outputfile and image_piece_list:
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("KDE: Using image piece list!")
        img_names = image_piece_list
    else:
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("Error! KDE actions called without arguments!")
        return

    filess_img_names = []
    for fname in img_names:
        filess_img_names.append("file://" + fname)
    filess_img_names_str = ", ".join('"' + _escape_js_string(item) + '"' for item in filess_img_names)
    # print(script.format(imagelist=filess_img_names_str))

    sp_logging.G_LOGGER.info("kdeplasma_actions: Creating dbus connection")
    sessionb = dbus.SessionBus()
    plasma_interface = dbus.Interface(
        sessionb.get_object("org.kde.plasmashell", "/PlasmaShell"),
        dbus_interface="org.kde.PlasmaShell",
    )
    if profname == G_ACTIVE_PROFILE or image_piece_list or force:
        sp_logging.G_LOGGER.info("kdeplasma_actions: Evaluating KDE script")
        plasma_interface.evaluateScript(script.format(imagelist=filess_img_names_str))
        sp_logging.G_LOGGER.info("kdeplasma_actions: Script evaluation complete")

    # Delete old images after new ones are set
    if outputfile:
        remove_old_temp_files(outputfile)


# def xfce_actions(outputfile, image_piece_list = None):
def xfce_actions(outputfile):
    """
    Sets the multi monitor wallpaper on XFCE.

    This is needed since XFCE uses its own scripting interface to
    set the desktop background which sets a single image on every
    monitor. This means that the composed image must be cut into
    correct pieces that then are set to their respective displays.
    """

    read_prop = subprocess.Popen(
        ["xfconf-query", "-c", "xfce4-desktop", "-p", "/backdrop", "-l"], stdout=subprocess.PIPE
    )
    props = []
    if read_prop.stdout is not None:
        props = read_prop.stdout.read().decode("utf-8").split("\n")
    for prop in props:
        if "workspace0/image-style" in prop:
            os.system("xfconf-query -c xfce4-desktop -p " + prop + " -s 6")  # ty:ignore[deprecated]
        elif "workspace0/last-image" in prop:
            os.system("xfconf-query -c xfce4-desktop -p " + prop + f" -s '{outputfile}'")  # ty:ignore[deprecated]

    # Delete old images after new ones are set
    if outputfile:
        remove_old_temp_files(outputfile)


def change_wallpaper_job(profile, force=False, advance=False):
    """Centralized wallpaper method that calls setter algorithm based on input prof settings.
    When force, skip the profile name check.
    When advance, cycle to the next image before rendering (slideshow / manual next).
    Otherwise the current persistent selection is rendered unchanged; if none has
    been established yet, the first image is picked once and saved as the selection.
    """
    with G_WALLPAPER_CHANGE_LOCK:
        if advance or not profile.selected:
            profile.advance_wallpaper()
        if profile.spanmode.startswith("single") and profile.ppimode is False:
            thrd = Thread(target=span_single_image_simple, args=(profile, force), daemon=True)
            thrd.start()
        elif (profile.spanmode.startswith("single") and profile.ppimode is True) or profile.spanmode.startswith(
            "advanced"
        ):
            thrd = Thread(target=span_single_image_advanced, args=(profile, force), daemon=True)
            thrd.start()
        elif profile.spanmode.startswith("multi"):
            thrd = Thread(target=set_multi_image_wallpaper, args=(profile, force), daemon=True)
            thrd.start()
        else:
            sp_logging.G_LOGGER.info("Unkown profile spanmode: %s", profile.spanmode)
            return None
        return thrd


def run_profile_job(profile, startup=False):
    """This method executes the input profile as the profile is configured.

    When ``startup`` is True the wallpaper is not changed immediately: the
    currently shown wallpaper is kept and, for slideshow profiles, only the
    repeating timer is armed so cycling happens later on its own schedule
    instead of on every app launch.
    """
    global G_ACTIVE_DISPLAYSYSTEM
    # get_display_data()  # Check here so new profile has fresh data.
    refresh_display_data()  # Refresh available display data.

    repeating_timer = None
    thrd = None
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info("running profile job with profile: %s", profile.name)

    if not profile.slideshow:
        # if sp_logging.DEBUG:
        #     sp_logging.G_LOGGER.info("Running a one-off wallpaper change.")
        if not startup:
            thrd = change_wallpaper_job(profile)
    elif profile.slideshow:
        # if sp_logging.DEBUG:
        #     sp_logging.G_LOGGER.info("Running wallpaper slideshow.")
        if not startup:
            thrd = change_wallpaper_job(profile)
        repeating_timer = RepeatedTimer(profile.delay_list[0], change_wallpaper_job, profile, advance=True)
    return (repeating_timer, thrd)


def quick_profile_job(profile):
    """
    At startup and profile change, switch to old temp wallpaper.

    Since the image processing takes some time, in order to carry
    out actions quickly at startup or at user request, set the old
    temp image of the requested profile as the wallpaper.
    """
    with G_WALLPAPER_CHANGE_LOCK:
        # Look for old temp image:
        files = [
            i
            for i in os.listdir(TEMP_PATH)
            if os.path.isfile(os.path.join(TEMP_PATH, i)) and (i.startswith((profile.name + "-a", profile.name + "-b")))
        ]
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("quickswitch file lookup: %s", files)
        if files:
            image_pieces = [os.path.join(TEMP_PATH, i) for i in files if "-crop-" in i]
            if use_image_pieces() and image_pieces:
                image_pieces.sort()
                if sp_logging.DEBUG:
                    sp_logging.G_LOGGER.info("Use wallpaper crop pieces: %s", image_pieces)
                thrd = Thread(target=set_wallpaper_piecewise, args=(image_pieces,), daemon=True)
                thrd.start()
            elif IS_WINDOWS:
                # Skip quick switch on Windows if not using perspective corrections.
                if profile.spanmode == "advanced" and G_ACTIVE_DISPLAYSYSTEM.use_perspective:
                    if (
                        profile.perspective == "default" and G_ACTIVE_DISPLAYSYSTEM.default_perspective is not None
                    ) or profile.perspective not in ["default", "disabled"]:
                        thrd = Thread(
                            target=set_wallpaper,
                            args=(os.path.join(TEMP_PATH, files[0]),),
                            daemon=True,
                        )
                        thrd.start()
                else:
                    pass
            else:
                thrd = Thread(target=set_wallpaper, args=(os.path.join(TEMP_PATH, files[0]),), daemon=True)
                thrd.start()
        else:
            if sp_logging.DEBUG:
                sp_logging.G_LOGGER.info("Old file for quickswitch was not found. %s", files)


def use_image_pieces():
    """Determine if it improves perfomance to use existing image pieces.

    Systems that use image pieces are: KDE, XFCE.
    """
    if IS_LINUX:
        # desk_env = os.environ.get("DESKTOP_SESSION")
        # elif desk_env in ["xfce", "xubuntu", "ubuntustudio"]:
        #     return True
        return running_kde()
    return bool(IS_MACOS)
