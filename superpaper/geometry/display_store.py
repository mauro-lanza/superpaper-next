"""The saved display layouts: display_systems.dat, and a <key>.persp file per layout.

Both are INI files in the config directory, in the format Superpaper v2.3.2 wrote, and
found by the layout's key (displays.Layout.key). display_systems.dat has a section
per layout: where its displays are placed, their bezels and any diagonals the user
entered, and whether perspectives are used and which is the default. <key>.persp has a
section per perspective of that layout. Files are replaced in one step.

The files are read by load() into the Layout of the detected displays, which can't be
used if it overlaps; load_or_default() then gives the default arrangement. save_layout()
writes one back, never one that overlaps.
"""

import configparser
import io
import locale
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from superpaper.files import write_atomically
from superpaper.geometry.canvas import Point
from superpaper.geometry.displays import Display, Layout
from superpaper.geometry.perspective import Perspective, Swivel, SwivelAxis, Tilt

logger = logging.getLogger(__name__)

LAYOUTS_FILE = "display_systems.dat"
NO_DEFAULT_PERSPECTIVE = "None"
"""How display_systems.dat spells a layout without a default perspective."""


@dataclass(frozen=True, slots=True)
class _SavedLayout:
    """What display_systems.dat keeps about one layout."""

    ppi_norm_offsets: tuple[Point, ...]
    """Each display's position on the density-normalised canvas, bezels included."""
    bezel_mms: tuple[Point, ...]
    """Each display's (right, bottom) bezel in millimetres."""
    user_diagonal_inches: tuple[float, ...] | None
    """The diagonals the user entered, or None for the detected sizes."""
    use_perspective: bool
    default_perspective: str | None


@dataclass(frozen=True, slots=True)
class LoadedLayout:
    """A layout for the detected displays, and why the saved one wasn't used, if it wasn't."""

    layout: Layout
    problem: str | None


def load(config_dir: Path, displays: tuple[Display, ...]) -> Layout:
    """The layout saved for ``displays``, or the one of displays with nothing saved.

    Raises configparser.Error or ValueError for files that can't be read, and for a saved
    layout whose displays overlap.
    """
    layout = Layout.initial(displays)
    saved = _read_layout(config_dir, layout.key)
    if saved is not None:
        try:
            layout = _with_saved(layout, saved)
        except ValueError as error:
            message = f"{config_dir / LAYOUTS_FILE}, layout {layout.key}: {error}"
            raise ValueError(message) from error
        if not layout.is_valid():
            message = f"{config_dir / LAYOUTS_FILE}, layout {layout.key}: the displays overlap"
            raise ValueError(message)
    return replace(layout, perspectives=_read_perspectives(config_dir, layout.key))


def load_or_default(config_dir: Path, displays: tuple[Display, ...]) -> LoadedLayout:
    """Like load(), but files that can't be used give the default arrangement and why.

    The files stay as they are until the user saves, which replaces what can't be used.
    """
    try:
        return LoadedLayout(load(config_dir, displays), None)
    except (configparser.Error, ValueError) as error:
        problem = (
            "The saved display layout can't be used, so the default arrangement is shown "
            f"until you save the display settings.\n\n{error}"
        )
        return LoadedLayout(Layout.initial(displays), problem)


def save_layout(config_dir: Path, layout: Layout) -> None:
    """Save the user's settings for these displays: in display_systems.dat where they are
    placed (bezels included), the bezels, any diagonal sizes entered and the perspective
    choice, and in the <key>.persp file the perspectives. The layouts of other displays are
    kept. Raises ValueError for a layout whose displays overlap."""
    if not layout.is_valid():
        message = "The displays overlap."
        raise ValueError(message)
    # The .persp file is written first, then the default it is named in.
    _write_perspectives(config_dir, layout.key, layout.perspectives)
    _write_layout(config_dir, layout.key, _as_saved(layout))


def _read_layout(config_dir: Path, key: str) -> _SavedLayout | None:
    """The layout saved under ``key``, or None if there is none."""
    config = _read(config_dir / LAYOUTS_FILE)
    if key not in config:
        logger.info("No layout is saved for these displays (key %s).", key)
        return None
    section = config[key]
    try:
        default_perspective = section.get("def_perspective", NO_DEFAULT_PERSPECTIVE)
        layout = _SavedLayout(
            ppi_norm_offsets=_str_to_points(section["ppi_norm_offsets"]),
            bezel_mms=tuple((round(x, 2), round(y, 2)) for x, y in _str_to_points(section["bezel_mms"])),
            user_diagonal_inches=_str_to_numbers(section["user_diagonal_inches"]),
            use_perspective=bool(int(section.get("use_perspective", 0))),
            default_perspective=None if default_perspective == NO_DEFAULT_PERSPECTIVE else default_perspective,
        )
    except (KeyError, ValueError, TypeError) as error:
        message = f"{config_dir / LAYOUTS_FILE}, layout {key}: {error!r}"
        raise ValueError(message) from error
    logger.info("Loaded the layout %s: %s", key, layout)
    return layout


def _write_layout(config_dir: Path, key: str, layout: _SavedLayout) -> None:
    """Save ``layout`` under ``key``, keeping the layouts of other displays."""
    path = config_dir / LAYOUTS_FILE
    try:
        config = _read(path)
    except (configparser.Error, ValueError) as error:
        _replace_unreadable(path, error)
        config = configparser.ConfigParser()
    config[key] = {
        "ppi_norm_offsets": _rows_to_str(layout.ppi_norm_offsets),
        "bezel_mms": _rows_to_str(layout.bezel_mms),
        "user_diagonal_inches": _numbers_to_str(layout.user_diagonal_inches),
        "use_perspective": str(int(layout.use_perspective)),
        "def_perspective": layout.default_perspective or NO_DEFAULT_PERSPECTIVE,
    }
    logger.info("Saving the layout %s: %s", key, layout)
    _write(path, config)


def _replace_unreadable(path: Path, error: Exception) -> None:
    """Move an unreadable ``path`` aside to ``<name>.corrupt``, replacing an earlier one, and log it.

    Saving is the user's way out of a file that can't be read.
    """
    kept = path.with_name(path.name + ".corrupt")
    path.replace(kept)
    logger.warning("Replacing the unreadable %s: %s; the old file is kept as %s", path, error, kept)


def _read_perspectives(config_dir: Path, key: str) -> tuple[Perspective, ...]:
    """The perspectives saved for the layout ``key``, in file order.

    Raises ValueError for a perspective that isn't made of the numbers it needs.
    """
    config = _read(config_dir / f"{key}.persp")
    logger.info("Loaded perspectives: %s", config.sections())
    perspectives = []
    for name in config.sections():
        try:
            perspectives.append(_parse_perspective(name, config[name]))
        except (KeyError, ValueError) as error:
            message = f"{config_dir / f'{key}.persp'}, perspective '{name}': {error!r}"
            raise ValueError(message) from error
    return tuple(perspectives)


def _write_perspectives(config_dir: Path, key: str, perspectives: Sequence[Perspective]) -> None:
    """Save ``perspectives`` as all the perspectives of the layout ``key``; no file is made for none."""
    path = config_dir / f"{key}.persp"
    if path.exists():
        try:
            _read_perspectives(config_dir, key)
        except (configparser.Error, ValueError) as error:
            _replace_unreadable(path, error)
    if not perspectives and not path.exists():
        return
    config = configparser.ConfigParser()
    for perspective in perspectives:
        config[perspective.name] = {
            "central_disp": str(perspective.central_display),
            "viewer_pos": _numbers_to_str(perspective.viewer_pos),
            "swivels": _rows_to_str(
                [(s.axis.value, s.angle, s.lateral_offset, s.depth_offset) for s in perspective.swivels]
            ),
            "tilts": _rows_to_str([(t.angle, t.vertical_offset, t.depth_offset) for t in perspective.tilts]),
        }
    logger.info("Saving perspectives: %s", config.sections())
    _write(path, config)


def _as_saved(layout: Layout) -> _SavedLayout:
    return _SavedLayout(
        ppi_norm_offsets=layout.ppi_norm_offsets,
        bezel_mms=tuple(layout.bezels_in_mm()),
        user_diagonal_inches=layout.user_diagonal_inches,
        use_perspective=layout.use_perspective,
        default_perspective=layout.default_perspective,
    )


def _with_saved(layout: Layout, saved: _SavedLayout) -> Layout:
    """``layout`` with the settings saved for its displays."""
    bezels_mm = layout.bezels_mm
    if any(bez < 0 for bez_pair in saved.bezel_mms for bez in bez_pair):
        logger.warning("Ignoring the saved bezels, which can't be negative: %s", saved.bezel_mms)
    else:
        bezels_mm = saved.bezel_mms
    return replace(
        layout,
        ppi_norm_offsets=saved.ppi_norm_offsets,
        bezels_mm=bezels_mm,
        user_diagonal_inches=saved.user_diagonal_inches,
        use_perspective=saved.use_perspective,
        default_perspective=saved.default_perspective,
    )


def _parse_perspective(name: str, section: configparser.SectionProxy) -> Perspective:
    (viewer_pos,) = _number_rows(section["viewer_pos"], 3)
    swivels = tuple(
        Swivel(SwivelAxis(axis), angle, lateral, depth)
        for axis, angle, lateral, depth in _number_rows(section["swivels"], 4)
    )
    tilts = tuple(Tilt(*row) for row in _number_rows(section["tilts"], 3))
    return Perspective(name, int(section["central_disp"]), viewer_pos, swivels, tilts)


def _number_rows(text: str, width: int) -> list[tuple]:
    """The ';' separated rows of ',' separated numbers of ``text``, each of ``width`` numbers."""
    rows = [tuple(_number(item) for item in row.split(",")) for row in text.split(";")]
    if any(len(row) != width for row in rows):
        message = f"Expected {width} numbers in each item of '{text}'."
        raise ValueError(message)
    return rows


def _number(text: str) -> int | float:
    try:
        return int(text)
    except ValueError:
        return float(text)


def _read(path: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        return config
    config.read_string(content.decode(_encoding()), source=str(path))
    return config


def _write(path: Path, config: configparser.ConfigParser) -> None:
    text = io.StringIO()
    config.write(text)
    write_atomically(path, text.getvalue().encode(_encoding()))


def _encoding() -> str:
    """The encoding earlier versions used for these files: Python's default text
    encoding, which is the ANSI code page on Windows."""
    return locale.getpreferredencoding(False)


def _numbers_to_str(numbers: Sequence[float] | None) -> str:
    """The numbers ','-separated; "None" for no numbers."""
    return ",".join(map(str, numbers)) if numbers else "None"


def _rows_to_str(rows: Sequence[Sequence[float]]) -> str:
    """The rows of numbers ','-separated, the rows ';'-separated."""
    return ";".join(",".join(map(str, row)) for row in rows)


def _str_to_numbers(text: str) -> tuple[float, ...] | None:
    """The ','-separated numbers of ``text``; None for "None"."""
    if text == "None":
        return None
    return tuple(_number(item) for item in text.split(","))


def _str_to_points(text: str) -> tuple[Point, ...]:
    """The ';'-separated (x, y) pairs of ``text``."""
    return tuple((x, y) for x, y in _number_rows(text, 2))
