"""
Display rotation correcting perspective transforms for Superpaper.

Having displays in a multi monitor setup both tilted and swiveled will
shear the wallpaper in disjoint pieces where lines are not preserved.
This module will research into alleviating or fixing this issue by applying
perspective corrections that aim to undo these effects caused by the rotations
of the displays relative to each other.

Written by Henri Hänninen, copyright 2020 under MIT licence.
"""

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from math import pi
from typing import assert_never

import numpy as np

from superpaper.user_input import parse_float

logger = logging.getLogger(__name__)

# "none" is display_store's no-default sentinel; "default" and "disabled" clash with the
# editor's perspective choices.
_RESERVED_PERSPECTIVE_NAMES = frozenset({"default", "disabled", "none"})
DEFAULT_LABEL = "default"
DISABLED_LABEL = "disabled"
ROTATION_CELL_NAMES = (
    "Swivel angle",
    "Sw. ax. lat. off.",
    "Sw. ax. dep. off.",
    "Tilt angle",
    "Ti. ax. ver. off.",
    "Ti. ax. dep. off.",
)


class SwivelAxis(Enum):
    """Which vertical edge of a display it turns around; the values are what .persp files hold."""

    NONE = 0
    LEFT = 1
    RIGHT = 2


@dataclass(frozen=True, slots=True)
class Swivel:
    """A display's turn around a vertical axis: the angle in degrees, and the axis offset in ppi norm pixels."""

    axis: SwivelAxis
    angle: float
    lateral_offset: float
    depth_offset: float


@dataclass(frozen=True, slots=True)
class Tilt:
    """A display's tilt around its horizontal midline: the angle in degrees, and the axis offset in ppi norm pixels."""

    angle: float
    vertical_offset: float
    depth_offset: float


@dataclass(frozen=True, slots=True)
class Perspective:
    """A named set of corrections for displays turned towards the viewer.

    ``viewer_pos`` is (lateral, vertical, depth) from the centre of display ``central_display``,
    in ppi norm pixels. ``swivels`` and ``tilts`` have one entry per display. Numbers keep
    the int or float the .persp file gave, so saving writes the file back as it was read.
    """

    name: str
    central_display: int
    viewer_pos: tuple[float, float, float]
    swivels: tuple[Swivel, ...]
    tilts: tuple[Tilt, ...]

    def of_displays(self, indices: tuple[int, ...] | list[int]) -> Perspective:
        """The perspective of just the displays at ``indices``."""
        return Perspective(
            self.name,
            self.central_display,
            self.viewer_pos,
            tuple(self.swivels[index] for index in indices),
            tuple(self.tilts[index] for index in indices),
        )


@dataclass(frozen=True, slots=True)
class Default:
    """The layout's default perspective."""


@dataclass(frozen=True, slots=True)
class Disabled:
    """No perspective correction."""


@dataclass(frozen=True, slots=True)
class Named:
    """The saved perspective called ``name``."""

    name: str


PerspectiveChoice = Default | Disabled | Named


def parse_choice(text: str) -> PerspectiveChoice:
    """The choice a profile file or the editor's dropdown spells as ``text``."""
    if text == DEFAULT_LABEL:
        return Default()
    if text == DISABLED_LABEL:
        return Disabled()
    return Named(text)


def choice_label(choice: PerspectiveChoice) -> str:
    """How a profile file and the editor's dropdown spell ``choice``."""
    match choice:
        case Default():
            return DEFAULT_LABEL
        case Disabled():
            return DISABLED_LABEL
        case Named(name):
            return name
        case _:
            assert_never(choice)


def check_new_perspective_name(name: str) -> None:
    """Raise ValueError if ``name`` cannot be given to a perspective being saved."""
    if name.casefold() in _RESERVED_PERSPECTIVE_NAMES:
        message = f"'{name}' is reserved; choose another perspective name."
        raise ValueError(message)


def perspective_from_mm(
    name: str,
    max_ppi: float,
    central_display: int,
    viewer_offset_mm: list[float],
    swivels_mm: list[tuple[SwivelAxis, float, float, float]],
    tilts_mm: list[tuple[float, float, float]],
) -> Perspective:
    """The perspective for the dialog's lengths in millimetres, converted to pixels at
    ``max_ppi``; angles and axes are kept."""
    px_per_mm = max_ppi / 25.4
    lateral, vertical, depth = (px_per_mm * length for length in viewer_offset_mm)
    return Perspective(
        name,
        central_display,
        (lateral, vertical, depth),
        tuple(Swivel(axis, angle, px_per_mm * lat, px_per_mm * dep) for axis, angle, lat, dep in swivels_mm),
        tuple(Tilt(angle, px_per_mm * ver, px_per_mm * dep) for angle, ver, dep in tilts_mm),
    )


def parse_viewer_offsets_mm(texts: Sequence[str]) -> list[float]:
    """The viewer's (horizontal, vertical, distance) offsets in millimetres, as typed.

    Raises ValueError saying what is wrong with them; the distance must be positive.
    """
    numbers = [parse_float(text) for text in texts]
    offsets = [number for number in numbers if number is not None]
    if len(offsets) != len(numbers):
        message = "Viewer offsets should be lenghts in millimeters, separate decimals with a point."
        raise ValueError(message)
    if offsets[2] <= 0:
        message = "Viewer distance must be entered and positive."
        raise ValueError(message)
    return offsets


def parse_rotations_mm(
    axes: Sequence[int], cells: Sequence[Sequence[str]]
) -> tuple[list[tuple[SwivelAxis, float, float, float]], list[tuple[float, float, float]]]:
    """The swivels and tilts of the displays in the dialog's grid, as typed.

    ``axes`` holds each display's swivel axis choice (a SwivelAxis value) and ``cells`` its
    texts in the order of ROTATION_CELL_NAMES. Raises ValueError naming the display and
    column of a cell that is not a number.
    """
    swivels = []
    tilts = []
    for display, (axis, row) in enumerate(zip(axes, cells, strict=True)):
        numbers = []
        for name, text in zip(ROTATION_CELL_NAMES, row, strict=True):
            number = parse_float(text)
            if number is None:
                message = f"Display {display}, '{name}': '{text}' is not a number; separate decimals with a point."
                raise ValueError(message)
            numbers.append(number)
        swivels.append((SwivelAxis(axis), numbers[0], numbers[1], numbers[2]))
        tilts.append((numbers[3], numbers[4], numbers[5]))
    return swivels, tilts


def get_backprojected_display_system(crops, perspective: Perspective):
    """
    Return a back-projected quadrilateral and associated projection
    transformation coefficients for each display in the Layout.

    Displays are initialized in a flat plane in homogeneous coordinates
    front of the viewer using the size and offset data from the Layout.
    These represent the display as they would be without any swivels or tilts.
    Then each display is rotated in 3D around a swivel axis and a tilt axis
    to get a 3D representation of the display setup.

    From this geometric setup, perspective corrections are computed by back-
    projecting the display corners back onto the initial common plane which
    represents the image plane. This produces stretched quadrilaterals that
    are used to compute the perspective correction coefficients that are used
    with Pillow to perform the perspective transformation on the source image.
    """
    sizes = [(crp[2] - crp[0], crp[3] - crp[1]) for crp in crops]
    central_disp = perspective.central_display
    viewer_pos_wrt_central = perspective.viewer_pos  # (lateral, vert, depth)
    swivels = perspective.swivels
    tilts = perspective.tilts
    logger.info("swivs: %s", swivels)
    logger.info("tilts: %s", tilts)

    disp_positions, init_plane_basis = position_displays_viewer(central_disp, viewer_pos_wrt_central, crops)
    init_plane_point = disp_positions[central_disp]

    projected_quads = []
    for sz, pos, swiv, tilt in zip(sizes, disp_positions, swivels, tilts):
        p_quad = get_backprojected_display(sz, pos, swiv, tilt, init_plane_basis, init_plane_point)
        projected_quads.append(p_quad)
    leftmost_corner = min([corner[0] for quad in projected_quads for corner in quad])
    bottommost_corner = min([corner[1] for quad in projected_quads for corner in quad])
    translated_quads = []
    for quad in projected_quads:
        work_quad = []
        for corner in quad:
            work_quad.append((round(corner[0] - leftmost_corner), round(corner[1] - bottommost_corner)))
        translated_quads.append(work_quad)
    logger.info("translated_quads: %s", translated_quads)
    ordered_quads = [(tquad[2], tquad[3], tquad[1], tquad[0]) for tquad in translated_quads]
    logger.info("ordered_quads: %s", ordered_quads)
    ordered_crops = [crop_from_quad(ordqu) for ordqu in ordered_quads]
    logger.info("ordered_crops: %s", ordered_crops)
    ppi_norm_corners = [
        ((crop[0], crop[1]), (crop[2], crop[1]), (crop[2], crop[3]), (crop[0], crop[3])) for crop in crops
    ]
    projected_coeffs = []
    for ordquad, ppi_norm_quad in zip(ordered_quads, ppi_norm_corners):
        coeffs = find_coeffs(ordquad, ppi_norm_quad)
        projected_coeffs.append(coeffs)

    return (ordered_crops, projected_coeffs)


def position_displays_viewer(central_disp, viewer_pos_wrt_central, crops):
    """Return display positions in viewer coordinates and a basis for the
    initialized plane."""
    centers = [((crp[2] + crp[0]) / 2, (crp[3] + crp[1]) / 2) for crp in crops]
    view_lat_off, view_ver_off, view_dist = viewer_pos_wrt_central
    # Translate centers so that central_disp center is at (0, 0)
    cd_cent = centers[central_disp]
    transl_cents = [(cent[0] - cd_cent[0] + view_lat_off, cent[1] - cd_cent[1] + view_ver_off) for cent in centers]
    homog_cents = [np.array((tracen[0], tracen[1], view_dist, 1)) for tracen in transl_cents]
    basis = [
        np.array([1, 0, 0, 1]),
        np.array([0, 1, 0, 1]),
        np.array([0, 0, 1, 1]),
    ]
    return homog_cents, basis


def crop_from_quad(quad):
    """Return (left, top, right, bottom) from a list of 4 corners."""
    leftmost = min([corner[0] for corner in quad])
    topmost = min([corner[1] for corner in quad])
    rightmost = max([corner[0] for corner in quad])
    bottommost = max([corner[1] for corner in quad])
    return (leftmost, topmost, rightmost, bottommost)


def get_backprojected_display(
    display_size, display_center, swivel_ax_ang_off: Swivel, tilt_ang_off: Tilt, bproj_pln_basis, bproj_pln_point
):
    """
    Return a quadrilateral that is produced then a display is back projected
    onto the plane of the assumed wallpaper, to be called 'poster plane'.

    Arguments needed are:
        - swivel angle & axis & axis offset from display edge in ppi norm res
        - tilt angle & axis offset from display surface horizontal mid line
        - distance of viewer in ppi norm res
        - height of viewer relative to the display. assume this to be 1/2?
            - lateral pos is assumed to be 1/2, centered to the display
        - display size (physical / ppi normalized resolution)

    Viewer (point camera) is taken to be at the origo of the world coordinates.
    The display is placed on the z-axis, centering it to (0, 0, view_dist).
    """

    swiv_ang, swiv_loff, swiv_depth = (
        swivel_ax_ang_off.angle,
        swivel_ax_ang_off.lateral_offset,
        swivel_ax_ang_off.depth_offset,
    )
    match swivel_ax_ang_off.axis:
        case SwivelAxis.NONE:
            # No swivel; keep code simpler by performing rotation of 0 degrees
            swiv_ax = "left"
            swiv_ang = 0
            swiv_loff = 0
            swiv_depth = 0
        case SwivelAxis.LEFT:
            swiv_ax = "left"
        case SwivelAxis.RIGHT:
            swiv_ax = "right"
        case _:
            assert_never(swivel_ax_ang_off.axis)
    tilt_ang, tilt_voff, tilt_depth = tilt_ang_off.angle, tilt_ang_off.vertical_offset, tilt_ang_off.depth_offset
    # convert angles to radians
    swiv_ang *= -1 * 2 * pi / 360  # something causes swivels go the wrong way; maybe the y-axis flip?
    tilt_ang *= 2 * pi / 360

    display_plane = XYPlaneRectangle(display_center, display_size)
    axis_swivel = display_plane.swivel_axis(swiv_ax, depth_offset=swiv_depth, lateral_offset=swiv_loff)
    axis_tilt = display_plane.tilt_axis(depth_offset=tilt_depth, vertical_offset=tilt_voff)

    # Swivel and tilt each corner of the display, specifically in this order
    disp_corners = display_plane.corners
    rotated_corners = tuple(
        swivel_and_tilt(corner, axis_tilt, tilt_ang, axis_swivel, swiv_ang) for corner in disp_corners
    )

    posterplane_normal = bproj_pln_basis[2]
    posterplane_basis = bproj_pln_basis[:-1]
    posterplane_center = bproj_pln_point

    # Back project display plane corners onto poster plane
    proj_corners = tuple(
        backproject_point_to_plane(crnr, posterplane_center, posterplane_normal) for crnr in rotated_corners
    )

    # Convert corners into poster plane coordinates
    poster_plane_corners = convert_to_plane_basis(proj_corners, posterplane_basis, posterplane_center)

    return poster_plane_corners


class XYPlaneRectangle:
    """Represent a rectangle in viewer coordinates."""

    def __init__(self, center, size):
        self.center = center
        self.size = size
        self.corners = self.get_corners()

    def get_corners(self):
        """Return rect corners as top left, top right, bot left, bot right."""
        width, height = self.size
        cent_x, cent_y, cent_z, cent_w = self.center
        corners = (
            np.array([cent_x - width / 2, cent_y + height / 2, cent_z, 1]),
            np.array([cent_x + width / 2, cent_y + height / 2, cent_z, 1]),
            np.array([cent_x - width / 2, cent_y - height / 2, cent_z, 1]),
            np.array([cent_x + width / 2, cent_y - height / 2, cent_z, 1]),
        )
        return corners

    def side_middle_pt(self, side):
        """Return the midpoint of side (left/right)."""
        if side == "left":
            mid = (self.corners[0] + self.corners[2]) / 2
        elif side == "right":
            mid = (self.corners[1] + self.corners[3]) / 2
        else:
            msg = f"Unknown side: {side}"
            raise ValueError(msg)
        return mid

    def swivel_axis(self, side, depth_offset=0, lateral_offset=0):
        """Return swivel axis.

        Points from side midpoint to top side top corner."""
        side_mid = self.side_middle_pt(side)
        if side == "left":
            axis_end = self.corners[0]
        elif side == "right":
            axis_end = self.corners[1]
        else:
            msg = f"Unknown side: {side}"
            raise ValueError(msg)
        axis = axis_end - side_mid
        pt_on_line = side_mid
        pt_on_line[0] += lateral_offset
        pt_on_line[2] += depth_offset
        return (axis, pt_on_line)

    def tilt_axis(self, side="left", depth_offset=0, vertical_offset=0):
        """Return tilt axis, including optional offsets.

        Choose positive rotation to tilt display upwards."""
        side_mid = self.side_middle_pt(side)
        if side == "left":
            axis = side_mid - self.center
        elif side == "right":
            axis = self.center - side_mid
        else:
            msg = f"Unknown side: {side}"
            raise ValueError(msg)
        pt_on_line = side_mid
        pt_on_line[1] += vertical_offset
        pt_on_line[2] += depth_offset
        return (axis, pt_on_line)


def swivel_and_tilt(vector, axis_tilt, tilt, axis_swivel, swivel):
    """Swivel and tilt a vector around given axii."""
    swivel_vec = rotate_point_around_line(vector, axis_swivel, swivel)
    tilt_swiveled_vec = rotate_point_around_line(swivel_vec, axis_tilt, tilt)
    return tilt_swiveled_vec


def rotate_point_around_line(point, axis_with_pt, theta):
    """Return a point in homogenous coordinates that results in
    the rotation around a line.

    Point is the one to be rotated, axis is the direction of the line
    and point_on_line is a point on the line where to move the origo
    for the duration of the rotation.

    Analytical form of the translation + rotation in homogenous coordinates
    is
    M = [[R, p-Rp], [0^T, 1]]
    """
    axis, point_on_line = axis_with_pt
    ax_3d = np.array([axis[0], axis[1], axis[2]])
    rot_m = rotation_matrix(ax_3d, theta)
    p = np.array([point_on_line[0], point_on_line[1], point_on_line[2]])
    p_rp = p - np.dot(rot_m, p)
    col_p_rp = np.array([[p_rp[0]], [p_rp[1]], [p_rp[2]]])

    zeros_transp = np.array([0, 0, 0])

    transl_and_rot = np.block([[rot_m, col_p_rp], [zeros_transp, 1]])

    return np.dot(transl_and_rot, point)


def rotation_matrix(axis, theta):
    """
    Return the rotation matrix associated with counterclockwise rotation about
    the given axis by theta radians.

    Rodrigues' rotation formula.
    """
    axis = np.asarray(axis)
    axis = axis / math.sqrt(np.dot(axis, axis))
    a = math.cos(theta / 2.0)
    b, c, d = -axis * math.sin(theta / 2.0)
    aa, bb, cc, dd = a * a, b * b, c * c, d * d
    bc, ad, ac, ab, bd, cd = b * c, a * d, a * c, a * b, b * d, c * d
    return np.array(
        [
            [aa + bb - cc - dd, 2 * (bc + ad), 2 * (bd - ac)],
            [2 * (bc - ad), aa + cc - bb - dd, 2 * (cd + ab)],
            [2 * (bd + ac), 2 * (cd - ab), aa + dd - bb - cc],
        ]
    )


def backproject_point_to_plane(point, point_on_plane, plane_normal):
    """Back-project a point along it's ray to a point on a plane
    parametrized with a normal and point."""
    norm = plane_normal - point_on_plane
    n_dot_r = np.dot(norm, point_on_plane)
    transform = np.array(
        [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [norm[0] / n_dot_r, norm[1] / n_dot_r, norm[2] / n_dot_r, 0],
        ]
    )
    projected_p = np.dot(transform, point)
    cartes_projected_p = projected_p / projected_p[3]
    return cartes_projected_p


def convert_to_plane_basis(points, basis, origo):
    """Covert homogenous coordinate points into 2d plane basis set at origo."""
    # pick cartesian part of basis
    base_x = (basis[0])[:-1]
    base_y = (basis[1])[:-1]
    # normalize to unit lenght
    unit_basis_vecs = (
        base_x / math.sqrt(np.dot(base_x, base_x)),
        base_y / math.sqrt(np.dot(base_y, base_y)),
    )
    plane_coords = []
    for pnt in points:
        x = np.dot(unit_basis_vecs[0], (pnt - origo)[:-1])
        y = np.dot(unit_basis_vecs[1], (pnt - origo)[:-1])
        plane_coords.append((round(x), round(y)))
    return plane_coords


def find_coeffs(source_coords, target_coords):
    """Compute the perspective transfomation coefficients from source and
    target quadrilaterals.

    Quad corner order needs to be TOP LEFT, TOP RIGHT, BOTTOM RIGHT, BOTTOM LEFT.
    """
    matrix = []
    for s, t in zip(source_coords, target_coords):
        matrix.append([t[0], t[1], 1, 0, 0, 0, -s[0] * t[0], -s[0] * t[1]])
        matrix.append([0, 0, 0, t[0], t[1], 1, -s[1] * t[0], -s[1] * t[1]])
    A = np.matrix(matrix, dtype=float)
    B = np.array(source_coords).reshape(8)
    res = np.linalg.solve(A, B)
    return np.array(res).reshape(8)
