"""
Wallpaper image processing back-end for Superpaper.

Applies image corrections, crops, merges etc., and hands the result to the desktop
(superpaper.desktop) to set as the wallpaper.

Written by Henri Hänninen, copyright 2022 under MIT licence.
"""

import configparser
import math
import os
import time
from operator import itemgetter
from pathlib import Path
from threading import Lock, Thread, Timer

from PIL import Image, ImageOps, UnidentifiedImageError
from screeninfo import get_monitors

import superpaper.desktop as desktop
import superpaper.perspective as persp
import superpaper.sp_logging as sp_logging
from superpaper.desktop.kde import Activities
from superpaper.desktop.process import Result
from superpaper.message_dialog import show_message_dialog
from superpaper.paths import AppPaths
from superpaper.sp_platform import IS_WINDOWS

# Disables PIL.Image.DecompressionBombError.
Image.MAX_IMAGE_PIXELS = None  # 715827880 would be 4x default max.


# Global constants

G_ACTIVE_PROFILE = None
G_WALLPAPER_CHANGE_LOCK = Lock()
G_WALLPAPER_CHANGE_PENDING = Lock()
G_SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp")


def is_supported_image(filename: str) -> bool:
    """Whether a file name has an extension Superpaper renders, in any letter case."""
    return filename.lower().endswith(G_SUPPORTED_IMAGE_EXTENSIONS)


# global to take care that failure message is not shown more than once at launch
USER_TOLD_OF_PHYS_FAIL = False


class DisplayDetectionError(RuntimeError):
    """Raised when monitor enumeration cannot produce a usable display list."""

    def __init__(self, attempts):
        super().__init__(f"Unable to detect any displays after {attempts} attempts.")
        self.attempts = attempts


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

    def __init__(self, config_dir: Path, *, max_attempts=3, retry_delay=0.25):
        """Detect the displays and load the layout saved for them from ``config_dir``.

        A wallpaper change is given the layout it renders for, so replacing the layout
        a running slideshow uses never touches one that a change is still using.
        """
        # display_systems.dat and the .persp files that hold the user's layout live here.
        self.config_dir = config_dir
        self.disp_list = get_display_data(max_attempts=max_attempts, retry_delay=retry_delay)
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

    def resolutions(self):
        """Each display's resolution in pixels, in desktop order."""
        return [display.resolution for display in self.disp_list]

    def digital_offsets(self):
        """Each display's top-left corner on the desktop, in desktop order."""
        return [display.digital_offset for display in self.disp_list]

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

        if columns == []:
            sp_logging.G_LOGGER.info("DisplaySystem column recostruction has failed completely. Trigger fallback.")
            columns = [[dsp] for dsp in self.disp_list]

        # Tile columns on to the plane with vertical centering
        col_sizes = []
        try:
            col_sizes = [self.column_size(col) for col in columns]
        except ValueError, IndexError:
            sp_logging.G_LOGGER.info("Problem with column sizes. col_sizes: %s", col_sizes)
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
        in a central file (config_dir/display_systems.dat).

        Data is saved with a DisplaySystem specific has as the key,
        and data saved include:
            - ppi_norm offsets which contain any given bezel thicknesses
            - bezel (bez+gap+bez) sizes for (right_b, bottom_b)
            - display diagonal sizes if any of them are manually changed
            - rotation angles of displays for perspective correction
        """
        archive_file = os.path.join(self.config_dir, "display_systems.dat")
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

    def load_system(self):
        """Try to load system data from database based on initialization data,
        i.e. the Display list. If no pre-existing system is found, try to guess
        the system topology and update disp_list"""
        archive_file = os.path.join(self.config_dir, "display_systems.dat")
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
            # Diagonal overrides first: the bezels were saved in millimetres using the
            # pixel densities they imply, so converting with the detected densities would
            # make every save drift the bezels a little further.
            if diagonal_inches:
                sp_logging.G_LOGGER.info("Updating diagonal_inches")
                self.update_display_diags(diagonal_inches, reset_offsets=False)
            self.update_bezels(bezel_mms)
            self.update_ppinorm_offsets(ppi_norm_offsets)  # Bezels & user diagonals always included.
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
        if persp_name is not None:
            if persp_name not in self.perspective_dict:
                self.perspective_dict[persp_name] = {}
            self.perspective_dict[persp_name]["central_disp"] = centr_disp
            self.perspective_dict[persp_name]["viewer_pos"] = viewer_pos
            self.perspective_dict[persp_name]["swivels"] = swivels
            self.perspective_dict[persp_name]["tilts"] = tilts
        # Persistence is triggered by the dialog after temporary validation.

    def save_perspectives(self):
        """Save perspective data dict to file."""
        instance_key = str(hash(self))
        persp_file = os.path.join(self.config_dir, instance_key + ".persp")

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
        persp_file = os.path.join(self.config_dir, instance_key + ".persp")
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


def get_display_data(*, max_attempts=3, retry_delay=0.25):
    """
    Detect the displays: a list of Display objects, one for each monitor, sorted by
    their position on the desktop. Offsets are sanitized so that they are always
    non-negative.
    """
    # https://github.com/rr-/screeninfo
    if max_attempts < 1:
        message = "max_attempts must be at least 1"
        raise ValueError(message)
    if retry_delay < 0:
        message = "retry_delay cannot be negative"
        raise ValueError(message)

    monitors = None
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            monitors = get_monitors()
        except Exception as error:
            last_error = error
            sp_logging.G_LOGGER.warning("Display detection attempt %d/%d failed: %s", attempt, max_attempts, error)
        if monitors:
            break
        if attempt < max_attempts:
            sp_logging.G_LOGGER.info("Display detection returned no displays; retrying.")
            time.sleep(retry_delay)
    else:
        error = DisplayDetectionError(max_attempts)
        if last_error is not None:
            raise error from last_error
        raise error

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

    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info(
            "get_display_data output: %s displays, resolutions %s, offsets %s",
            len(display_list),
            [disp.resolution for disp in display_list],
            [disp.digital_offset for disp in display_list],
        )
        for disp in display_list:
            sp_logging.G_LOGGER.info(str(disp))
    return display_list


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


# resize image to fill given rectangle and do a positioned crop to size.
# Return output image.
def resize_to_fill(
    img,
    res,
    quality: str | Image.Resampling = Image.Resampling.LANCZOS,
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
    except TypeError, ValueError:
        zoom = 1.0
    if zoom < 1.0:
        zoom = 1.0
    try:
        offset_x = min(1.0, max(-1.0, float(offset[0])))
        offset_y = min(1.0, max(-1.0, float(offset[1])))
    except TypeError, ValueError, IndexError:
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


def compute_working_canvas(crop_tuples, bezels=None):
    """Computes effective size of the desktop are taking into account PPI/offsets/bezels.

    When ``bezels`` is provided (a list of ``(right, bottom)`` ppi-normalized
    bezel sizes parallel to ``crop_tuples``), the outer bezels extend the
    canvas so that the rendered image matches what the GUI preview shows. The
    preview sizes its canvas with these bezels included, so omitting them here
    made the applied wallpaper ignore outer bezels.
    """
    # Take the subtractions of right-most right - left-most left
    # and bottom-most bottom - top-most top (=0).
    leftmost = 0
    topmost = 0
    if bezels:
        # Right-/bottom-most edge including each display's outer bezel.
        rightmost = max(round(crp[2] + bez[0]) for crp, bez in zip(crop_tuples, bezels))
        bottommost = max(round(crp[3] + bez[1]) for crp, bez in zip(crop_tuples, bezels))
    else:
        # Right-most edge of the crop tuples.
        rightmost = max(crop_tuples, key=itemgetter(2))[2]
        # Bottom-most edge of the crop tuples.
        bottommost = max(crop_tuples, key=itemgetter(3))[3]
    canvas_size = [rightmost - leftmost, bottommost - topmost]
    return canvas_size


def alternating_outputfile(cache_dir: Path, prof_name):
    """Return alternating output filename and old filename.

    This is done so that the cache doesn't become a huge dump of unused files,
    and it is alternating since some OSs don't update their wallpapers if the
    current image file is overwritten.
    """
    if IS_WINDOWS:
        ftype = "jpg"
    else:
        ftype = "png"
    outputfile = os.path.join(cache_dir, prof_name + "-a." + ftype)
    if os.path.isfile(outputfile):
        outputfile_old = outputfile
        outputfile = os.path.join(cache_dir, prof_name + "-b." + ftype)
    else:
        outputfile_old = os.path.join(cache_dir, prof_name + "-b." + ftype)
    return (outputfile, outputfile_old)


def span_single_image_simple(profile, force, *, display_system: DisplaySystem, paths: AppPaths, set_command=""):
    """
    Spans a single image across all monitors. No corrections.

    This simple method resizes the source image so it fills the whole
    desktop canvas. Since no corrections are applied, no offset dependent
    cuts are needed and so this should work on any monitor arrangement.
    """
    files = profile.next_wallpaper_files()
    if len(files) != 1:
        sp_logging.G_LOGGER.error("No complete wallpaper selection is available for profile '%s'.", profile.name)
        return
    file = files[0]
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info(file)
    try:
        img = Image.open(file)
        img = ImageOps.exif_transpose(img)
    except OSError, UnidentifiedImageError:
        sp_logging.G_LOGGER.info(
            ("Opening image '%s' failed with PIL.UnidentifiedImageError.It could be corrupted or is of foreign type."),
            file,
        )
        return
    canvas_tuple = tuple(compute_canvas(display_system.resolutions(), display_system.digital_offsets()))
    img_resize = resize_to_fill(img, canvas_tuple, zoom=profile.zoom, offset=profile.offsets)

    outputfile, outputfile_old = alternating_outputfile(paths.cache, profile.name)
    img_resize.save(outputfile, quality=95)  # set quality if jpg is used, png unaffected
    if profile.name == G_ACTIVE_PROFILE or force:
        set_wallpaper(outputfile, [file], display_system=display_system, paths=paths, set_command=set_command)
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
def span_single_image_advanced(profile, force, *, display_system: DisplaySystem, paths: AppPaths, set_command=""):
    """
    Applies wallpaper using PPI, bezel, offset corrections.

    Further description todo.
    """
    files = profile.next_wallpaper_files()
    expected_files = len(profile.spangroups) if profile.spangroups else 1
    if len(files) != expected_files:
        sp_logging.G_LOGGER.error("No complete wallpaper selection is available for profile '%s'.", profile.name)
        return
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info(files)
    try:
        img_list = [Image.open(fil) for fil in files]
        img_list = [ImageOps.exif_transpose(img) for img in img_list]
    except OSError, UnidentifiedImageError:
        sp_logging.G_LOGGER.info(
            ("Opening image '%s' failed with PIL.UnidentifiedImageError.It could be corrupted or is of foreign type."),
            files,
        )
        return

    # Cropping now sections of the image to be shown, USE EFFECTIVE WORKING
    # SIZES. Also EFFECTIVE SIZE Offsets are now required.
    resolutions = display_system.resolutions()
    manual_offsets = profile.display_corrections(resolutions).manual_offsets
    cropped_images = {}
    crop_tuples = display_system.get_ppi_norm_crops(manual_offsets)
    sp_logging.G_LOGGER.info(
        "use_perspective: %s, prof.perspective: %s",
        display_system.use_perspective,
        profile.perspective,
    )
    persp_dat = None
    if display_system.use_perspective:
        persp_dat = display_system.get_persp_data(profile.perspective)

    if profile.spangroups:
        spangroups = profile.spangroups
    else:
        spangroups = [list(range(len(resolutions)))]

    grp_crop_tuples = translate_to_group_coordinates([[crop_tuples[index] for index in grp] for grp in spangroups])
    grp_res_array = [[resolutions[index] for index in grp] for grp in spangroups]
    # Per-display outer bezel sizes (ppi-normalized), grouped to match the
    # crops, so the working canvas can include outer bezels like the preview.
    bezels_px = display_system.bezels_in_px()
    grp_bezels = [[bezels_px[index] for index in grp] for grp in spangroups]
    grp_persp_dat = group_persp_data(persp_dat, spangroups)

    for img, grp, grp_p_dat, grp_crops, grp_res_arr, grp_bez in zip(
        img_list, spangroups, grp_persp_dat, grp_crop_tuples, grp_res_array, grp_bezels
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
            # Outer bezels extend the canvas so the result matches the preview
            # (issue #156); the per-display crops below stay resolution-sized.
            canvas_tuple_eff = tuple(compute_working_canvas(grp_crops, grp_bez))
            # Image is now the height of the eff tallest display + possible manual
            # offsets and the width of the combined eff widths + possible manual
            # offsets.
            img_workingsize = resize_to_fill(img, canvas_tuple_eff, zoom=profile.zoom, offset=profile.offsets)
            # Simultaneously make crops at working size and then resize down to actual
            # display resolution as needed.
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
    offsets = display_system.digital_offsets()
    canvas_tuple_fin = tuple(compute_canvas(resolutions, offsets))
    combined_image = Image.new("RGB", canvas_tuple_fin, color=0)
    combined_image.load()
    for crp_id in cropped_images:
        combined_image.paste(cropped_images[crp_id], offsets[crp_id])

    # Saving combined image
    outputfile, outputfile_old = alternating_outputfile(paths.cache, profile.name)
    combined_image.save(outputfile, quality=95)  # set quality if jpg is used, png unaffected
    if profile.name == G_ACTIVE_PROFILE or force:
        set_wallpaper(outputfile, files, display_system=display_system, paths=paths, set_command=set_command)
    if os.path.exists(outputfile_old):
        os.remove(outputfile_old)
    return 0


def set_multi_image_wallpaper(profile, force, *, display_system: DisplaySystem, paths: AppPaths, set_command=""):
    """Sets a distinct image on each monitor.

    Since most platforms only support setting a single image
    as the wallpaper this has to be accomplished by creating a
    composite image based on the monitor offsets and then setting
    the resulting image as the wallpaper. A profile set up for a different
    number of displays than ``display_system`` has is not rendered.
    """
    resolutions = display_system.resolutions()
    offsets = display_system.digital_offsets()
    files = profile.next_wallpaper_files()
    if len(files) != len(resolutions):
        sp_logging.G_LOGGER.error("No complete wallpaper selection is available for profile '%s'.", profile.name)
        return
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info(str(files))
    img_resized = []
    for file, res in zip(files, resolutions):
        # image = Image.open(file)
        try:
            image = Image.open(file)
            image = ImageOps.exif_transpose(image)
        except OSError, UnidentifiedImageError:
            sp_logging.G_LOGGER.info(
                (
                    "Opening image '%s' failed with PIL.UnidentifiedImageError."
                    "It could be corrupted or is of foreign type."
                ),
                file,
            )
            return
        img_resized.append(resize_to_fill(image, res, zoom=profile.zoom, offset=profile.offsets))
    canvas_tuple = tuple(compute_canvas(resolutions, offsets))
    combined_image = Image.new("RGB", canvas_tuple, color=0)
    combined_image.load()
    for i in range(len(files)):
        combined_image.paste(img_resized[i], offsets[i])

    outputfile, outputfile_old = alternating_outputfile(paths.cache, profile.name)
    combined_image.save(outputfile, quality=95)  # set quality if jpg is used, png unaffected
    if profile.name == G_ACTIVE_PROFILE or force:
        set_wallpaper(outputfile, files, display_system=display_system, paths=paths, set_command=set_command)
    if os.path.exists(outputfile_old):
        os.remove(outputfile_old)
    return 0


def set_wallpaper(outputfile, source_files=None, *, display_system: DisplaySystem, paths: AppPaths, set_command=""):
    """Hand a rendered wallpaper to the desktop, then run the user's run-after-wp-change.py.

    Desktops that take one image per display get ``outputfile`` cut for ``display_system``.
    ``set_command`` is the user's own setter command, if any (Linux only).
    """
    pieces = special_image_cropper(outputfile, display_system) if desktop.takes_pieces(set_command) else None
    _log_problem(desktop.set_wallpaper(outputfile, pieces, set_command=set_command, activities=_activities(paths)))
    remove_old_temp_files(outputfile)
    script = paths.config / "run-after-wp-change.py"
    if script.is_file():
        _log_problem(desktop.run_hook(script, outputfile, source_files or []))


def _activities(paths: AppPaths) -> Activities:
    """How KDE finds the wallpapers of the profiles its activities are named after."""
    return Activities(
        current_profile=G_ACTIVE_PROFILE,
        cached_pieces=lambda name: _cached_pieces(paths.cache, name),
        state_dir=paths.config,
    )


def _cached_pieces(cache_dir: Path, profile_name: str) -> list[str]:
    """The per-display images last rendered for the profile named ``profile_name``."""
    names = sorted(
        name
        for name in os.listdir(cache_dir)
        if os.path.isfile(os.path.join(cache_dir, name)) and name.startswith(profile_name + "-") and "-crop-" in name
    )
    return [os.path.join(cache_dir, name) for name in names]


def _log_problem(result: Result) -> None:
    if not result.ok:
        sp_logging.G_LOGGER.error("%s", result.problem)


def special_image_cropper(outputfile, display_system: DisplaySystem):
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
    for crop_id, (res, offset) in enumerate(zip(display_system.resolutions(), display_system.digital_offsets())):
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
    needed for KDE and XFCE. They are kept beside ``outputfile``.
    """
    opbase = os.path.basename(outputfile)
    opname = os.path.splitext(opbase)[0]
    oldfileid = ""
    if opname.endswith("-a"):
        oldfileid = "-b"
    elif opname.endswith("-b"):
        oldfileid = "-a"
    else:
        pass
    if oldfileid:
        # Must take care than only temps of current profile are deleted.
        profilename = opname.strip()[:-2]
        match_string = profilename + oldfileid + "-crop"
        match_string = match_string.strip()
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("Removing images matching with: '%s'", match_string)
        cache_dir = os.path.dirname(outputfile)
        for temp_file in os.listdir(cache_dir):
            if match_string in temp_file:
                os.remove(os.path.join(cache_dir, temp_file))


def _change_wallpaper(profile, force, advance, display_system: DisplaySystem, paths: AppPaths, set_command):
    """Resolve a selection and render it for ``display_system``."""
    if (advance or not profile.has_valid_selection()) and not profile.advance_wallpaper():
        sp_logging.G_LOGGER.error("Wallpaper change skipped: profile '%s' has no complete selection.", profile.name)
        return
    if profile.spanmode.startswith("single"):
        # A single image with legacy corrections (offsets=, ppi=, ...) needs the advanced renderer.
        if profile.display_corrections(display_system.resolutions()).ppimode:
            span_single_image_advanced(
                profile, force, display_system=display_system, paths=paths, set_command=set_command
            )
        else:
            span_single_image_simple(
                profile, force, display_system=display_system, paths=paths, set_command=set_command
            )
    elif profile.spanmode.startswith("advanced"):
        span_single_image_advanced(profile, force, display_system=display_system, paths=paths, set_command=set_command)
    elif profile.spanmode.startswith("multi"):
        set_multi_image_wallpaper(profile, force, display_system=display_system, paths=paths, set_command=set_command)
    else:
        sp_logging.G_LOGGER.info("Unkown profile spanmode: %s", profile.spanmode)


def change_wallpaper_job(
    profile,
    paths: AppPaths,
    *,
    display_system: DisplaySystem,
    set_command="",
    force=False,
    advance=False,
    skip_if_busy=False,
):
    """Centralized wallpaper method that calls setter algorithm based on input prof settings.
    When force, skip the profile name check.
    When advance, cycle to the next image before rendering (slideshow / manual next).
    Otherwise the current persistent selection is rendered unchanged; if none has
    been established yet, the first image is picked once and saved as the selection.
    The wallpaper is rendered for ``display_system`` into ``paths.cache``;
    ``set_command`` is the user's own wallpaper setter command, if any.
    """
    if not (
        profile.spanmode.startswith("single")
        or profile.spanmode.startswith("advanced")
        or profile.spanmode.startswith("multi")
    ):
        sp_logging.G_LOGGER.info("Unkown profile spanmode: %s", profile.spanmode)
        return None
    gate_acquired = False
    if skip_if_busy:
        gate_acquired = G_WALLPAPER_CHANGE_PENDING.acquire(blocking=False)
        if not gate_acquired:
            sp_logging.G_LOGGER.info("Wallpaper change skipped because another change is pending.")
            return None

    def run_change():
        if not gate_acquired:
            G_WALLPAPER_CHANGE_PENDING.acquire()
        try:
            with G_WALLPAPER_CHANGE_LOCK:
                _change_wallpaper(profile, force, advance, display_system, paths, set_command)
        finally:
            G_WALLPAPER_CHANGE_PENDING.release()

    thrd = Thread(target=run_change, daemon=True)
    thrd.start()
    return thrd


def run_profile_job(profile, change, startup=False):
    """Start running ``profile``: set its wallpaper now and arm its slideshow.

    ``change(profile, advance=..., skip_if_busy=...)`` starts one wallpaper change; the
    slideshow timer calls it on every tick. When ``startup`` is True the wallpaper is not
    changed immediately: the currently shown wallpaper is kept and, for slideshow
    profiles, only the repeating timer is armed so cycling happens later on its own
    schedule instead of on every app launch.
    """
    repeating_timer = None
    thrd = None
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info("running profile job with profile: %s", profile.name)

    if not startup:
        thrd = change(profile)
    if profile.slideshow:
        repeating_timer = RepeatedTimer(
            profile.delay_list[0],
            change,
            profile,
            advance=True,
            skip_if_busy=True,
        )
    return (repeating_timer, thrd)


def quick_profile_job(profile, *, display_system: DisplaySystem, paths: AppPaths, set_command=""):
    """
    At startup and profile change, switch to old temp wallpaper.

    Since the image processing takes some time, in order to carry
    out actions quickly at startup or at user request, set the old
    temp image of the requested profile as the wallpaper.
    """

    def locked_setter(setter, *args, **kwargs):
        with G_WALLPAPER_CHANGE_PENDING, G_WALLPAPER_CHANGE_LOCK:
            setter(*args, **kwargs)

    # Look for old temp image. The setter worker takes the render lock, so the
    # UI thread never blocks behind an in-progress render.
    cache_dir = paths.cache
    files = [
        i
        for i in os.listdir(cache_dir)
        if os.path.isfile(os.path.join(cache_dir, i)) and (i.startswith((profile.name + "-a", profile.name + "-b")))
    ]
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info("quickswitch file lookup: %s", files)
    if files:
        image = os.path.join(cache_dir, files[0])
        image_pieces = sorted(os.path.join(cache_dir, i) for i in files if "-crop-" in i)
        if desktop.takes_pieces(set_command) and image_pieces:
            if sp_logging.DEBUG:
                sp_logging.G_LOGGER.info("Use wallpaper crop pieces: %s", image_pieces)
            thrd = Thread(
                target=locked_setter,
                args=(_restore_pieces, image, image_pieces),
                kwargs={"paths": paths, "set_command": set_command},
                daemon=True,
            )
            thrd.start()
        elif IS_WINDOWS:
            # Skip quick switch on Windows if not using perspective corrections.
            if profile.spanmode == "advanced" and display_system.use_perspective:
                if (
                    profile.perspective == "default" and display_system.default_perspective is not None
                ) or profile.perspective not in ["default", "disabled"]:
                    thrd = Thread(
                        target=locked_setter,
                        args=(set_wallpaper, image),
                        kwargs={"display_system": display_system, "paths": paths, "set_command": set_command},
                        daemon=True,
                    )
                    thrd.start()
            else:
                pass
        else:
            thrd = Thread(
                target=locked_setter,
                args=(set_wallpaper, image),
                kwargs={"display_system": display_system, "paths": paths, "set_command": set_command},
                daemon=True,
            )
            thrd.start()
    else:
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("Old file for quickswitch was not found. %s", files)


def _restore_pieces(image, pieces, *, paths: AppPaths, set_command):
    """Show the per-display images last rendered, on a desktop that takes those."""
    _log_problem(desktop.set_wallpaper(image, pieces, set_command=set_command, activities=_activities(paths)))
