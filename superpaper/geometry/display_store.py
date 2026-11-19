"""The saved display layouts: display_systems.dat, and a <key>.persp file per layout.

Both are INI files in the config directory, in the format Superpaper v2.3.2 wrote, and
found by the layout's key (displays.Layout.key). display_systems.dat has a section
per layout: where its displays are placed, their bezels and any diagonals the user
entered, and whether perspectives are used and which is the default. <key>.persp has a
section per perspective of that layout. Files are replaced in one step.

load() builds the Layout of the detected displays; the save functions write one back.
"""

import configparser
import io
import locale
import logging
from collections.abc import Callable, Sequence
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
class SaveFailed:
    """Settings that couldn't be written to disk, and why."""

    message: str


def load(config_dir: Path, displays: tuple[Display, ...]) -> Layout:
    """The layout saved for ``displays``, or the one of displays with nothing saved.

    Raises configparser.Error or ValueError for files that can't be read.
    """
    layout = Layout.initial(displays)
    saved = _read_layout(config_dir, layout.key)
    if saved is not None:
        try:
            layout = _with_saved(layout, saved)
        except ValueError as error:
            message = f"{config_dir / LAYOUTS_FILE}, layout {layout.key}: {error}"
            raise ValueError(message) from error
    return replace(layout, perspectives=_read_perspectives(config_dir, layout.key))


def save_layout(config_dir: Path, layout: Layout) -> None:
    """Save the user's settings for these displays in display_systems.dat: where they
    are placed (bezels included), the bezels, any diagonal sizes entered, and the
    perspective choice. The layouts of other displays are kept."""
    _write_layout(config_dir, layout.key, _as_saved(layout))


def save_perspective_choice(config_dir: Path, layout: Layout) -> None:
    """Save the perspectives in their <key>.persp file, and which one is the default
    and whether they are used in display_systems.dat. The rest of the saved layout is
    left as it is, whatever else ``layout`` holds. A display_systems.dat that can't be
    read changes nothing."""
    saved = _read_layout(config_dir, layout.key)
    if saved is None:
        # Nothing is saved yet, so the layout in use is the one of a fresh system.
        saved = _as_saved(Layout.initial(layout.displays))
    _write_perspectives(config_dir, layout.key, layout.perspectives)
    _write_layout(
        config_dir,
        layout.key,
        replace(saved, use_perspective=layout.use_perspective, default_perspective=layout.default_perspective),
    )


def save_or_failure(
    save: Callable[[Path, Layout], None], config_dir: Path, layout: Layout, what: str
) -> SaveFailed | None:
    """Run ``save``; why it failed, worded for ``what`` was being saved, or None."""
    try:
        save(config_dir, layout)
    except (OSError, configparser.Error, ValueError) as error:
        return SaveFailed(f"The {what} could not be saved: {error}")
    return None


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
    config = _read(path)
    config[key] = {
        "ppi_norm_offsets": _rows_to_str(layout.ppi_norm_offsets),
        "bezel_mms": _rows_to_str(layout.bezel_mms),
        "user_diagonal_inches": _numbers_to_str(layout.user_diagonal_inches),
        "use_perspective": str(int(layout.use_perspective)),
        "def_perspective": layout.default_perspective or NO_DEFAULT_PERSPECTIVE,
    }
    logger.info("Saving the layout %s: %s", key, layout)
    _write(path, config)


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
    """Save ``perspectives`` as all the perspectives of the layout ``key``."""
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
    _write(config_dir / f"{key}.persp", config)


def _as_saved(layout: Layout) -> _SavedLayout:
    return _SavedLayout(
        ppi_norm_offsets=layout.ppi_norm_offsets,
        bezel_mms=tuple(layout.bezels_in_mm()),
        user_diagonal_inches=layout.user_diagonal_inches or None,
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
    diagonals = saved.user_diagonal_inches or None
    return replace(
        layout,
        ppi_norm_offsets=saved.ppi_norm_offsets,
        bezels_mm=bezels_mm,
        user_diagonal_inches=diagonals,
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
