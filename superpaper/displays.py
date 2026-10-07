"""The displays and their layout: detection, and the pixel-density, bezel, offset and
diagonal geometry that lines a wallpaper up across them.

A layout is saved with display_store, under a key derived from the displays.
"""

import logging
import math
import time
from pathlib import Path

from screeninfo import get_monitors

from superpaper import display_store

logger = logging.getLogger(__name__)

SIZE_HINT = (
    "Detection of the diagonal size of a display has failed. It will show up as a 23 inch "
    "display in advanced mode. Enter the correct diagonal size with the Override Detected "
    "Sizes tool."
)


class DisplayDetectionError(RuntimeError):
    """Raised when monitor enumeration cannot produce a usable display list."""

    def __init__(self, attempts):
        super().__init__(f"Unable to detect any displays after {attempts} attempts.")
        self.attempts = attempts


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
        # Part of the key the layout is saved under (DisplaySystem.key): ints only.
        return hash((self.resolution, self.digital_offset, self.detected_phys_size_mm))

    def diagonal_size(self):
        diag_mm = math.sqrt(self.phys_size_mm[0] ** 2 + self.phys_size_mm[1] ** 2)
        diag_in = round(diag_mm / 25.4, 1)
        return (round(diag_mm), diag_in)

    def compute_ppi(self):
        if self.phys_size_mm[0]:
            ppmm_horiz = self.resolution[0] / self.phys_size_mm[0]
        else:
            logger.info("Display.compute_ppi: self.phys_size_mm[0] was 0.")
            return None
        if self.phys_size_mm[1]:
            ppmm_vert = self.resolution[1] / self.phys_size_mm[1]
        else:
            logger.info("Display.compute_ppi: self.phys_size_mm[1] was 0.")
            return None
        if abs(ppmm_horiz / ppmm_vert - 1) > 0.01:
            logger.info(
                "WARNING: Horizontal and vertical PPI do not match! hor: %s, ver: %s",
                ppmm_horiz * 25.4,
                ppmm_vert * 25.4,
            )
            logger.info(str(self))
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

        logger.info(
            "Updated PPI = %s and phys_size_mm = %s based on diagonal size: %s inches",
            self.ppi,
            self.phys_size_mm,
            diag_inch,
        )
        logger.info(str(self))


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

        saved = display_store.read_layout(config_dir, self.key)
        if saved is None:
            self.compute_initial_preview_offsets()
        else:
            self._apply(saved)
        self.perspective_dict = display_store.read_perspectives(config_dir, self.key)

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

    @property
    def key(self) -> str:
        """What the layout is saved under. It is CPython's hash of the displays'
        resolutions, positions and detected sizes, all ints, so it is the same in every
        run. It must never change: every user's saved layouts would be lost."""
        return str(hash(self))

    def size_hint(self) -> str | None:
        """What to tell the user when a display's physical size wasn't detected and no
        diagonal they entered replaces the guess."""
        if not self.use_user_diags and any(display.phys_size_failed for display in self.disp_list):
            return SIZE_HINT
        return None

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
        logger.info("get_ppi_norm_offsets: %s", self.get_ppinorm_offsets())
        logger.info("get_ppi_norm_crops: %s", crops)
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
            logger.info("DisplaySystem column recostruction has failed completely. Trigger fallback.")
            columns = [[dsp] for dsp in self.disp_list]

        # Tile columns on to the plane with vertical centering
        col_sizes = []
        try:
            col_sizes = [self.column_size(col) for col in columns]
        except ValueError, IndexError:
            logger.info("Problem with column sizes. col_sizes: %s", col_sizes)
        max_col_h = 0
        try:
            max_col_h = max([sz[1] for sz in col_sizes])
        except ValueError:
            logger.info("There are no column sizes? col_sizes: %s", col_sizes)
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
        """Update displays with new bezel sizes, in millimetres; they can't be negative."""
        if any(bez < 0 for bez_pair in bezels_mm for bez in bez_pair):
            message = f"Bezel thicknesses can't be negative: {bezels_mm}"
            raise ValueError(message)
        # convert to normalized pixel units
        max_ppmm = self.max_ppi() / 25.4
        bezels_ppi_norm = [(bz[0] * max_ppmm, bz[1] * max_ppmm) for bz in bezels_mm]
        for bz_px, dsp in zip(bezels_ppi_norm, self.disp_list):
            dsp.ppi_norm_bezels = bz_px
            logger.info("update_bezels: %s", bz_px)
        self.compute_initial_preview_offsets()

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
        """Save the user's settings for these displays in display_systems.dat: where they
        are placed (bezels included), the bezels, any diagonal sizes entered, and the
        perspective choice. The layouts of other displays are kept."""
        diagonal_inches = [display.diagonal_size()[1] for display in self.disp_list] if self.use_user_diags else None
        saved = display_store.SavedLayout(
            ppi_norm_offsets=self.get_ppinorm_offsets(),
            bezel_mms=self.bezels_in_mm(),
            user_diagonal_inches=diagonal_inches,
            use_perspective=self.use_perspective,
            default_perspective=self.default_perspective,
        )
        display_store.write_layout(self.config_dir, self.key, saved)

    def _apply(self, saved: display_store.SavedLayout):
        """Apply a layout saved for these displays."""
        # Diagonal overrides first: the bezels were saved in millimetres using the pixel
        # densities they imply, so converting with the detected densities would make
        # every save drift the bezels a little further.
        if saved.user_diagonal_inches:
            logger.info("Updating diagonal_inches")
            self.update_display_diags(saved.user_diagonal_inches, reset_offsets=False)
        if any(bez < 0 for bez_pair in saved.bezel_mms for bez in bez_pair):
            logger.warning("Ignoring the saved bezels, which can't be negative: %s", saved.bezel_mms)
        else:
            self.update_bezels(saved.bezel_mms)
        self.update_ppinorm_offsets(saved.ppi_norm_offsets)  # Bezels & user diagonals always included.
        self.use_perspective = saved.use_perspective
        self.default_perspective = saved.default_perspective

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
        # The perspective dialog saves the layout once the user has accepted the settings.

    def save_perspectives(self):
        """Save all the perspectives of these displays, in their <key>.persp file."""
        display_store.write_perspectives(self.config_dir, self.key, self.perspective_dict)

    # End DisplaySystem


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
            logger.warning("Display detection attempt %d/%d failed: %s", attempt, max_attempts, error)
        if monitors:
            break
        if attempt < max_attempts:
            logger.info("Display detection returned no displays; retrying.")
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

    logger.info(
        "get_display_data output: %s displays, resolutions %s, offsets %s",
        len(display_list),
        [disp.resolution for disp in display_list],
        [disp.digital_offset for disp in display_list],
    )
    for disp in display_list:
        logger.info(str(disp))
    return display_list
