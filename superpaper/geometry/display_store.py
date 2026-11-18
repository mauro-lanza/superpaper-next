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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from superpaper.files import write_atomically
from superpaper.geometry.displays import Display, Layout
from superpaper.geometry.perspective import Perspective, Swivel, SwivelAxis, Tilt

logger = logging.getLogger(__name__)

LAYOUTS_FILE = "display_systems.dat"


@dataclass(frozen=True, slots=True)
class SavedLayout:
    """What display_systems.dat keeps about one layout."""

    ppi_norm_offsets: list
    """Each display's position on the density-normalised canvas, bezels included."""
    bezel_mms: list
    """Each display's (right, bottom) bezel in millimetres."""
    user_diagonal_inches: list | None
    """The diagonals the user entered, or None for the detected sizes."""
    use_perspective: bool
    default_perspective: str | None


def load(config_dir: Path, displays: tuple[Display, ...]) -> Layout:
    """The layout saved for ``displays``, or the one of displays with nothing saved.

    Raises configparser.Error or ValueError for files that can't be read.
    """
    layout = Layout.initial(displays)
    saved = read_layout(config_dir, layout.key)
    if saved is not None:
        try:
            layout = _with_saved(layout, saved)
        except ValueError as error:
            message = f"{config_dir / LAYOUTS_FILE}, layout {layout.key}: {error}"
            raise ValueError(message) from error
    return replace(layout, perspectives=read_perspectives(config_dir, layout.key))


def save_layout(config_dir: Path, layout: Layout) -> None:
    """Save the user's settings for these displays in display_systems.dat: where they
    are placed (bezels included), the bezels, any diagonal sizes entered, and the
    perspective choice. The layouts of other displays are kept."""
    write_layout(config_dir, layout.key, _as_saved(layout))


def save_perspectives(config_dir: Path, layout: Layout) -> None:
    """Save all the perspectives of these displays, in their <key>.persp file."""
    write_perspectives(config_dir, layout.key, layout.perspectives)


def save_perspective_choice(config_dir: Path, layout: Layout) -> None:
    """Save the perspectives in their <key>.persp file, and which one is the default
    and whether they are used in display_systems.dat. The rest of the saved layout is
    left as it is, whatever else ``layout`` holds. A display_systems.dat that can't be
    read changes nothing."""
    saved = read_layout(config_dir, layout.key)
    if saved is None:
        # Nothing is saved yet, so the layout in use is the one of a fresh system.
        saved = _as_saved(Layout.initial(layout.displays))
    save_perspectives(config_dir, layout)
    write_layout(
        config_dir,
        layout.key,
        replace(saved, use_perspective=layout.use_perspective, default_perspective=layout.default_perspective),
    )


def read_layout(config_dir: Path, key: str) -> SavedLayout | None:
    """The layout saved under ``key``, or None if there is none."""
    config = _read(config_dir / LAYOUTS_FILE)
    if key not in config:
        logger.info("No layout is saved for these displays (key %s).", key)
        return None
    section = config[key]
    try:
        bezel_mms = _str_to_list(section["bezel_mms"], item_len=2)
        if bezel_mms:
            bezel_mms = [(round(bez[0], 2), round(bez[1], 2)) for bez in bezel_mms]
        default_perspective = section.get("def_perspective", "None")
        layout = SavedLayout(
            ppi_norm_offsets=_str_to_list(section["ppi_norm_offsets"], item_len=2),
            bezel_mms=bezel_mms,
            user_diagonal_inches=_str_to_list(section["user_diagonal_inches"], item_len=1),
            use_perspective=bool(int(section.get("use_perspective", 0))),
            default_perspective=None if default_perspective == "None" else default_perspective,
        )
    except (KeyError, ValueError, TypeError) as error:
        message = f"{config_dir / LAYOUTS_FILE}, layout {key}: {error!r}"
        raise ValueError(message) from error
    logger.info("Loaded the layout %s: %s", key, layout)
    return layout


def write_layout(config_dir: Path, key: str, layout: SavedLayout) -> None:
    """Save ``layout`` under ``key``, keeping the layouts of other displays."""
    path = config_dir / LAYOUTS_FILE
    config = _read(path)
    config[key] = {
        "ppi_norm_offsets": _list_to_str(layout.ppi_norm_offsets, item_len=2),
        "bezel_mms": _list_to_str(layout.bezel_mms, item_len=2),
        "user_diagonal_inches": _list_to_str(layout.user_diagonal_inches, item_len=1),
        "use_perspective": str(int(layout.use_perspective)),
        "def_perspective": str(layout.default_perspective),
    }
    logger.info("Saving the layout %s: %s", key, layout)
    _write(path, config)


def read_perspectives(config_dir: Path, key: str) -> tuple[Perspective, ...]:
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


def write_perspectives(config_dir: Path, key: str, perspectives: Sequence[Perspective]) -> None:
    """Save ``perspectives`` as all the perspectives of the layout ``key``."""
    config = configparser.ConfigParser()
    for perspective in perspectives:
        config[perspective.name] = {
            "central_disp": str(perspective.central_display),
            "viewer_pos": _list_to_str(list(perspective.viewer_pos), item_len=1),
            "swivels": _list_to_str(
                [(s.axis.value, s.angle, s.lateral_offset, s.depth_offset) for s in perspective.swivels], item_len=4
            ),
            "tilts": _list_to_str(
                [(t.angle, t.vertical_offset, t.depth_offset) for t in perspective.tilts], item_len=3
            ),
        }
    logger.info("Saving perspectives: %s", config.sections())
    _write(config_dir / f"{key}.persp", config)


def _as_saved(layout: Layout) -> SavedLayout:
    return SavedLayout(
        ppi_norm_offsets=list(layout.ppi_norm_offsets),
        bezel_mms=layout.bezels_in_mm(),
        user_diagonal_inches=layout.diagonal_inches() if layout.uses_user_diagonals else None,
        use_perspective=layout.use_perspective,
        default_perspective=layout.default_perspective,
    )


def _with_saved(layout: Layout, saved: SavedLayout) -> Layout:
    """``layout`` with the settings saved for its displays."""
    bezels_mm = layout.bezels_mm
    if any(bez < 0 for bez_pair in saved.bezel_mms for bez in bez_pair):
        logger.warning("Ignoring the saved bezels, which can't be negative: %s", saved.bezel_mms)
    else:
        bezels_mm = tuple(saved.bezel_mms)
    diagonals = tuple(saved.user_diagonal_inches) if saved.user_diagonal_inches else None
    return replace(
        layout,
        ppi_norm_offsets=tuple(saved.ppi_norm_offsets),
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


def _list_to_str(lst, item_len=1):
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


def _str_to_list(joined_list, item_len=1):
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
                    logger.info("str_to_list: ValueError: not int or float: %s", item)
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
                        logger.info("str_to_list: ValueError: not int or float: %s", sub_item)
                conv_item.append(val)
            conv_list.append(tuple(conv_item))
        return conv_list
