"""Perspective corrections for displays that are tilted or swiveled towards the viewer.

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

logger = logging.getLogger(__name__)

MM_PER_INCH = 25.4

DEFAULT_LABEL = "default"
DISABLED_LABEL = "disabled"


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


def get_backprojected_display_system(
    crops: Sequence[Sequence[float]], perspective: Perspective
) -> tuple[list[tuple[float, float, float, float]], list[list[float]]]:
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

    disp_positions, init_plane_basis = _position_displays_viewer(central_disp, viewer_pos_wrt_central, crops)
    init_plane_point = disp_positions[central_disp]

    projected_quads = []
    for sz, pos, swiv, tilt in zip(sizes, disp_positions, swivels, tilts):
        p_quad = _get_backprojected_display(sz, pos, swiv, tilt, init_plane_basis, init_plane_point)
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
    ordered_crops = [_crop_from_quad(ordqu) for ordqu in ordered_quads]
    logger.info("ordered_crops: %s", ordered_crops)
    ppi_norm_corners = [
        ((crop[0], crop[1]), (crop[2], crop[1]), (crop[2], crop[3]), (crop[0], crop[3])) for crop in crops
    ]
    projected_coeffs = []
    for ordquad, ppi_norm_quad in zip(ordered_quads, ppi_norm_corners):
        coeffs = _find_coeffs(ordquad, ppi_norm_quad)
        projected_coeffs.append(coeffs)

    return (ordered_crops, projected_coeffs)


def _position_displays_viewer(
    central_disp: int, viewer_pos_wrt_central: tuple[float, float, float], crops: Sequence[Sequence[float]]
) -> tuple[list[np.ndarray], list[np.ndarray]]:
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


def _crop_from_quad(quad: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    """Return (left, top, right, bottom) from a list of 4 corners."""
    leftmost = min([corner[0] for corner in quad])
    topmost = min([corner[1] for corner in quad])
    rightmost = max([corner[0] for corner in quad])
    bottommost = max([corner[1] for corner in quad])
    return (leftmost, topmost, rightmost, bottommost)


def _get_backprojected_display(
    display_size: tuple[float, float],
    display_center: np.ndarray,
    swivel_ax_ang_off: Swivel,
    tilt_ang_off: Tilt,
    bproj_pln_basis: Sequence[np.ndarray],
    bproj_pln_point: np.ndarray,
) -> list[tuple[int, int]]:
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

    display_plane = _XYPlaneRectangle(display_center, display_size)
    axis_swivel = display_plane.swivel_axis(swiv_ax, depth_offset=swiv_depth, lateral_offset=swiv_loff)
    axis_tilt = display_plane.tilt_axis(depth_offset=tilt_depth, vertical_offset=tilt_voff)

    # Swivel and tilt each corner of the display, specifically in this order
    disp_corners = display_plane.corners
    rotated_corners = tuple(
        _swivel_and_tilt(corner, axis_tilt, tilt_ang, axis_swivel, swiv_ang) for corner in disp_corners
    )

    posterplane_normal = bproj_pln_basis[2]
    posterplane_basis = bproj_pln_basis[:-1]
    posterplane_center = bproj_pln_point

    # Back project display plane corners onto poster plane
    proj_corners = tuple(
        _backproject_point_to_plane(crnr, posterplane_center, posterplane_normal) for crnr in rotated_corners
    )

    # Convert corners into poster plane coordinates
    poster_plane_corners = _convert_to_plane_basis(proj_corners, posterplane_basis, posterplane_center)

    return poster_plane_corners


class _XYPlaneRectangle:
    """Represent a rectangle in viewer coordinates."""

    def __init__(self, center: np.ndarray, size: tuple[float, float]):
        self.center = center
        self.size = size
        self.corners = self.get_corners()

    def get_corners(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return rect corners as top left, top right, bot left, bot right."""
        width, height = self.size
        cent_x, cent_y, cent_z, _ = self.center
        corners = (
            np.array([cent_x - width / 2, cent_y + height / 2, cent_z, 1]),
            np.array([cent_x + width / 2, cent_y + height / 2, cent_z, 1]),
            np.array([cent_x - width / 2, cent_y - height / 2, cent_z, 1]),
            np.array([cent_x + width / 2, cent_y - height / 2, cent_z, 1]),
        )
        return corners

    def side_middle_pt(self, side: str) -> np.ndarray:
        """Return the midpoint of side (left/right)."""
        if side == "left":
            mid = (self.corners[0] + self.corners[2]) / 2
        elif side == "right":
            mid = (self.corners[1] + self.corners[3]) / 2
        else:
            msg = f"Unknown side: {side}"
            raise ValueError(msg)
        return mid

    def swivel_axis(
        self, side: str, depth_offset: float = 0, lateral_offset: float = 0
    ) -> tuple[np.ndarray, np.ndarray]:
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

    def tilt_axis(
        self, side: str = "left", depth_offset: float = 0, vertical_offset: float = 0
    ) -> tuple[np.ndarray, np.ndarray]:
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


def _swivel_and_tilt(
    vector: np.ndarray,
    axis_tilt: tuple[np.ndarray, np.ndarray],
    tilt: float,
    axis_swivel: tuple[np.ndarray, np.ndarray],
    swivel: float,
) -> np.ndarray:
    """Swivel and tilt a vector around given axii."""
    swivel_vec = _rotate_point_around_line(vector, axis_swivel, swivel)
    tilt_swiveled_vec = _rotate_point_around_line(swivel_vec, axis_tilt, tilt)
    return tilt_swiveled_vec


def _rotate_point_around_line(
    point: np.ndarray, axis_with_pt: tuple[np.ndarray, np.ndarray], theta: float
) -> np.ndarray:
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
    rot_m = _rotation_matrix(ax_3d, theta)
    p = np.array([point_on_line[0], point_on_line[1], point_on_line[2]])
    p_rp = p - np.dot(rot_m, p)
    col_p_rp = np.array([[p_rp[0]], [p_rp[1]], [p_rp[2]]])

    zeros_transp = np.array([0, 0, 0])

    transl_and_rot = np.block([[rot_m, col_p_rp], [zeros_transp, 1]])

    return np.dot(transl_and_rot, point)


def _rotation_matrix(axis: np.ndarray, theta: float) -> np.ndarray:
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


def _backproject_point_to_plane(point: np.ndarray, point_on_plane: np.ndarray, plane_normal: np.ndarray) -> np.ndarray:
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


def _convert_to_plane_basis(
    points: Sequence[np.ndarray], basis: Sequence[np.ndarray], origo: np.ndarray
) -> list[tuple[int, int]]:
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


def _find_coeffs(source_coords: Sequence[Sequence[float]], target_coords: Sequence[Sequence[float]]) -> list[float]:
    """Compute the perspective transfomation coefficients from source and
    target quadrilaterals.

    Quad corner order needs to be TOP LEFT, TOP RIGHT, BOTTOM RIGHT, BOTTOM LEFT.
    """
    matrix = []
    for s, t in zip(source_coords, target_coords):
        matrix.append([t[0], t[1], 1, 0, 0, 0, -s[0] * t[0], -s[0] * t[1]])
        matrix.append([0, 0, 0, t[0], t[1], 1, -s[1] * t[0], -s[1] * t[1]])
    A = np.array(matrix, dtype=float)
    B = np.array(source_coords).reshape(8)
    res = np.linalg.solve(A, B)
    return np.array(res).reshape(8).tolist()
