"""
Display layouts, and the jobs that change the wallpaper: choose a profile's images,
render them (superpaper.render), keep the result (superpaper.render_cache) and show it
(superpaper.desktop).

Written by Henri Hänninen, copyright 2022 under MIT licence.
"""

import configparser
import math
import os
import time
from pathlib import Path
from threading import Lock, Thread, Timer

from screeninfo import get_monitors

import superpaper.desktop as desktop
import superpaper.render as render
import superpaper.render_cache as render_cache
import superpaper.sp_logging as sp_logging
from superpaper.desktop.kde import Activities
from superpaper.desktop.process import Result
from superpaper.message_dialog import show_message_dialog
from superpaper.paths import AppPaths
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.sp_platform import IS_WINDOWS

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


def set_wallpaper(image, source_files=None, *, display_system: DisplaySystem, paths: AppPaths, set_command="") -> bool:
    """Hand the rendered wallpaper ``image`` to the desktop, then run the user's
    run-after-wp-change.py. Returns whether the desktop took it.

    Desktops that take one image per display get ``image`` cut for ``display_system``.
    ``set_command`` is the user's own setter command, if any (Linux only).
    """
    pieces = None
    if desktop.takes_pieces(set_command):
        pieces = [str(piece) for piece in render_cache.cut_pieces(Path(image), display_system)]
    result = desktop.set_wallpaper(str(image), pieces, set_command=set_command, activities=_activities(paths))
    _log_problem(result)
    script = paths.config / "run-after-wp-change.py"
    if script.is_file():
        _log_problem(desktop.run_hook(script, str(image), source_files or []))
    return result.ok


def _activities(paths: AppPaths) -> Activities:
    """How KDE finds the wallpapers of the profiles its activities are named after."""
    return Activities(
        current_profile=G_ACTIVE_PROFILE,
        cached_pieces=lambda name: _cached_pieces(paths.cache, name),
        state_dir=paths.config,
    )


def _cached_pieces(cache_dir: Path, profile_name: str) -> list[str]:
    """The per-display images last rendered for the profile named ``profile_name``."""
    try:
        profile_id = ProfileId.parse(profile_name)
    except ProfileIdError:  # an activity name no profile can have
        return []
    rendered = render_cache.latest(render_cache.slot(cache_dir, profile_id))
    return [str(piece) for piece in rendered.pieces] if rendered else []


def _log_problem(result: Result) -> None:
    if not result.ok:
        sp_logging.G_LOGGER.error("%s", result.problem)


def _change_wallpaper(profile, force, advance, display_system: DisplaySystem, paths: AppPaths, set_command):
    """Choose ``profile``'s images, render them for ``display_system``, keep the render in
    the cache and show it.

    Unless ``force``, a profile that is no longer running is left alone: its slideshow can
    tick once more after another profile has started.
    """
    if not force and profile.name != G_ACTIVE_PROFILE:
        sp_logging.G_LOGGER.info("Wallpaper change skipped: profile '%s' is no longer running.", profile.name)
        return
    if (advance or not profile.has_valid_selection()) and not profile.advance_wallpaper():
        sp_logging.G_LOGGER.error("Wallpaper change skipped: profile '%s' has no complete selection.", profile.name)
        return
    files = profile.next_wallpaper_files()
    try:
        image = _render(profile, files, display_system)
    except render.SourceImageError as error:
        sp_logging.G_LOGGER.error("Wallpaper change skipped: %s", error)
        return
    if image is None:
        return
    try:
        output = render_cache.save(render_cache.slot(paths.cache, profile.profile_id), image)
    except OSError as error:
        sp_logging.G_LOGGER.error("Wallpaper change skipped: the wallpaper could not be saved: %s", error)
        return
    if set_wallpaper(output, files, display_system=display_system, paths=paths, set_command=set_command):
        # Until the desktop takes the new render, the previous one may still be on screen.
        render_cache.forget_previous(output)


def _render(profile, files, display_system: DisplaySystem):
    """Compose ``profile``'s desktop image from ``files``; None, with the reason logged, if
    they don't fit its span mode."""
    resolutions = display_system.resolutions()
    if profile.spanmode.startswith("multi"):
        if len(files) != len(resolutions):
            _log_incomplete(profile)
            return None
        return render.multi(files, display_system, zoom=profile.zoom, pan=profile.offsets)
    corrections = profile.display_corrections(resolutions)
    if profile.spanmode.startswith("single") and not corrections.ppimode:
        if len(files) != 1:
            _log_incomplete(profile)
            return None
        return render.simple(files[0], display_system, zoom=profile.zoom, pan=profile.offsets)
    # Advanced spanning, or a single image with legacy corrections (offsets=, ppi=, ...).
    if len(files) != (len(profile.spangroups) if profile.spangroups else 1):
        _log_incomplete(profile)
        return None
    perspective = display_system.get_persp_data(profile.perspective) if display_system.use_perspective else None
    return render.advanced(
        files,
        display_system,
        manual_offsets=corrections.manual_offsets,
        spangroups=profile.spangroups,
        perspective=perspective,
        zoom=profile.zoom,
        pan=profile.offsets,
    )


def _log_incomplete(profile) -> None:
    sp_logging.G_LOGGER.error("No complete wallpaper selection is available for profile '%s'.", profile.name)


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


def quick_profile_job(profile, *, display_system: DisplaySystem, paths: AppPaths, set_command="") -> bool:
    """Show the last wallpaper again at startup, without rendering anything.

    That is the last render of ``profile``, or a draft shown after it: the editor's Apply,
    the align test or the command line. Returns False if ``profile`` has no render to
    show, so that the caller can render it.
    """
    if profile.profile_id is None:
        return False
    rendered = render_cache.latest(render_cache.slot(paths.cache, profile.profile_id))
    if rendered is None:
        sp_logging.G_LOGGER.info("Profile '%s' has no earlier render to show.", profile.name)
        return False
    draft = render_cache.latest(render_cache.slot(paths.cache, None))
    if draft is not None and draft.modified > rendered.modified:
        rendered = draft

    def locked_setter(setter, *args, **kwargs):
        with G_WALLPAPER_CHANGE_PENDING, G_WALLPAPER_CHANGE_LOCK:
            setter(*args, **kwargs)

    # The setter worker takes the render lock, so the UI thread never blocks behind an
    # in-progress render.
    image = str(rendered.image)
    pieces = [str(piece) for piece in rendered.pieces]
    if desktop.takes_pieces(set_command) and pieces:
        sp_logging.G_LOGGER.info("Use wallpaper crop pieces: %s", pieces)
        setter, args, kwargs = _restore_pieces, (image, pieces), {"paths": paths, "set_command": set_command}
    elif IS_WINDOWS and not _windows_restores(profile, display_system):
        return True  # Windows keeps the wallpaper itself
    else:
        setter, args = set_wallpaper, (image,)
        kwargs = {"display_system": display_system, "paths": paths, "set_command": set_command}
    Thread(target=locked_setter, args=(setter, *args), kwargs=kwargs, daemon=True).start()
    return True


def _windows_restores(profile, display_system: DisplaySystem) -> bool:
    """Whether Windows gets the wallpaper again at startup: only a perspective render does."""
    if profile.spanmode != "advanced" or not display_system.use_perspective:
        return False
    if profile.perspective == "default":
        return display_system.default_perspective is not None
    return profile.perspective != "disabled"


def _restore_pieces(image, pieces, *, paths: AppPaths, set_command):
    """Show the per-display images last rendered, on a desktop that takes those."""
    _log_problem(desktop.set_wallpaper(image, pieces, set_command=set_command, activities=_activities(paths)))
