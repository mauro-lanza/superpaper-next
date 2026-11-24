"""Perspective corrections for displays that are tilted or swiveled towards the viewer.

Written by Henri Hänninen, copyright 2020 under MIT licence.
"""

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import assert_never

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_LABEL = "default"
DISABLED_LABEL = "disabled"

_VERTICAL = np.array([0.0, 1.0, 0.0])
_IMAGE_PLANE_NORMAL_END = np.array([0, 0, 1, 1])
_DEGENERATE_MESSAGE = (
    "A display is swiveled or tilted so far that the viewer would see it edge-on; "
    "use smaller angles or move the viewer."
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


class DegeneratePerspective(ValueError):
    """A display is turned so far that the viewer sees it edge-on."""


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
    """Each display's crop on the image plane, and the Pillow perspective coefficients that
    map the display's ``crops`` entry onto it.

    The viewer is a point camera at the origin looking along +z. Every display starts flat,
    facing the viewer at its distance, placed by its crop relative to the central display.
    Each is then swiveled around a vertical axis and tilted around a horizontal one in 3D.
    Casting a ray from the viewer through each turned corner back onto the flat image plane
    gives a stretched quadrilateral: the part of the source image that the display must show
    for the picture to look flat to the viewer. The coefficients map each display's own
    rectangle onto its quadrilateral, so Pillow can warp the source image into it.

    Raises DegeneratePerspective when a display is turned edge-on to the viewer.
    """
    centers = _display_centers(crops, perspective)
    plane_point = centers[perspective.central_display]
    quads = [
        _backproject_display((crop[2] - crop[0], crop[3] - crop[1]), center, swivel, tilt, plane_point)
        for crop, center, swivel, tilt in zip(crops, centers, perspective.swivels, perspective.tilts, strict=True)
    ]
    left = min(x for quad in quads for x, _ in quad)
    top = min(y for quad in quads for _, y in quad)
    plane_quads = [[(x - left, y - top) for x, y in quad] for quad in quads]
    logger.info("Back-projected display quadrilaterals: %s", plane_quads)
    coefficients = [
        _find_coeffs(quad, ((crop[0], crop[1]), (crop[2], crop[1]), (crop[2], crop[3]), (crop[0], crop[3])))
        for quad, crop in zip(plane_quads, crops, strict=True)
    ]
    return [_crop_from_quad(quad) for quad in plane_quads], coefficients


def _display_centers(crops: Sequence[Sequence[float]], perspective: Perspective) -> list[np.ndarray]:
    """Each display's centre in homogeneous viewer coordinates, before it is turned."""
    lateral, vertical, distance = perspective.viewer_pos
    centers = [((crop[2] + crop[0]) / 2, (crop[3] + crop[1]) / 2) for crop in crops]
    central_x, central_y = centers[perspective.central_display]
    return [np.array((x - central_x + lateral, y - central_y + vertical, distance, 1)) for x, y in centers]


def _crop_from_quad(quad: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    """The (left, top, right, bottom) box around ``quad``."""
    xs = [x for x, _ in quad]
    ys = [y for _, y in quad]
    return (min(xs), min(ys), max(xs), max(ys))


def _backproject_display(
    size: tuple[float, float], center: np.ndarray, swivel: Swivel, tilt: Tilt, plane_point: np.ndarray
) -> list[tuple[int, int]]:
    """The display's corners, top left first and clockwise, turned and cast back onto the
    image plane through ``plane_point``, in that plane's coordinates."""
    width, height = size
    x, y, z, _ = center
    # Viewer y grows downwards like image y, so the corners are in image order.
    corners = [
        np.array([x - width / 2, y - height / 2, z, 1]),
        np.array([x + width / 2, y - height / 2, z, 1]),
        np.array([x + width / 2, y + height / 2, z, 1]),
        np.array([x - width / 2, y + height / 2, z, 1]),
    ]
    left_middle = (corners[0] + corners[3]) / 2
    right_middle = (corners[1] + corners[2]) / 2

    match swivel.axis:
        case SwivelAxis.NONE:
            swiveled = corners
        case SwivelAxis.LEFT | SwivelAxis.RIGHT:
            edge_middle = left_middle if swivel.axis is SwivelAxis.LEFT else right_middle
            pivot = edge_middle[:3] + np.array((swivel.lateral_offset, 0, swivel.depth_offset))
            # Negated: a positive .persp swivel angle turns the display the other way round this axis.
            rotation = _rotation_about_line(_VERTICAL, pivot, math.radians(-swivel.angle))
            swiveled = [rotation @ corner for corner in corners]
        case _:
            assert_never(swivel.axis)

    tilt_pivot = left_middle[:3] + np.array((0, tilt.vertical_offset, tilt.depth_offset))
    tilt_rotation = _rotation_about_line(left_middle[:3] - center[:3], tilt_pivot, math.radians(tilt.angle))
    turned = [tilt_rotation @ corner for corner in swiveled]

    projected = [_backproject_point_to_plane(corner, plane_point) for corner in turned]
    return [(round(point[0] - plane_point[0]), round(point[1] - plane_point[1])) for point in projected]


def _rotation_about_line(direction: np.ndarray, pivot: np.ndarray, theta: float) -> np.ndarray:
    """The homogeneous matrix that rotates by ``theta`` radians about the line through ``pivot``
    along ``direction``: [[R, p - Rp], [0, 1]]."""
    rotation = _rotation_matrix(direction, theta)
    translation = pivot - rotation @ pivot
    return np.block([[rotation, translation.reshape(3, 1)], [np.zeros(3), 1]])


def _rotation_matrix(axis: np.ndarray, theta: float) -> np.ndarray:
    """The matrix of a counterclockwise rotation by ``theta`` radians about ``axis``
    (Euler-Rodrigues formula)."""
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


def _backproject_point_to_plane(point: np.ndarray, plane_point: np.ndarray) -> np.ndarray:
    """Where the ray from the viewer through ``point`` meets the image plane through ``plane_point``.

    The plane's normal is (0, 0, 1) - ``plane_point``, so it faces the viewer only when the viewer
    sits straight in front of the central display; changing it would change every saved
    perspective's output.
    """
    normal = _IMAGE_PLANE_NORMAL_END - plane_point
    with np.errstate(divide="ignore", invalid="ignore"):
        n_dot_r = np.dot(normal, plane_point)
        transform = np.array(
            [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [normal[0] / n_dot_r, normal[1] / n_dot_r, normal[2] / n_dot_r, 0],
            ]
        )
        projected = transform @ point
        cartesian = projected / projected[3]
    if not np.isfinite(cartesian).all():
        raise DegeneratePerspective(_DEGENERATE_MESSAGE)
    return cartesian


def _find_coeffs(source_coords: Sequence[Sequence[float]], target_coords: Sequence[Sequence[float]]) -> list[float]:
    """The perspective coefficients that map the ``target_coords`` quad onto ``source_coords``,
    both ordered top left, top right, bottom right, bottom left."""
    matrix = []
    for s, t in zip(source_coords, target_coords, strict=True):
        matrix.append([t[0], t[1], 1, 0, 0, 0, -s[0] * t[0], -s[0] * t[1]])
        matrix.append([0, 0, 0, t[0], t[1], 1, -s[1] * t[0], -s[1] * t[1]])
    try:
        solution = np.linalg.solve(np.array(matrix, dtype=float), np.array(source_coords).reshape(8))
    except np.linalg.LinAlgError as error:
        raise DegeneratePerspective(_DEGENERATE_MESSAGE) from error
    return solution.tolist()
