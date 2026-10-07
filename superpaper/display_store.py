"""The saved display layouts: display_systems.dat, and a <key>.persp file per layout.

Both are INI files in the config directory, in the format Superpaper v2.3.2 wrote, and
found by the layout's key (displays.DisplaySystem.key). display_systems.dat has a section
per layout: where its displays are placed, their bezels and any diagonals the user
entered, and whether perspectives are used and which is the default. <key>.persp has a
section per perspective of that layout. Files are replaced in one step.
"""

import configparser
import io
import locale
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from superpaper.files import write_atomically

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


def read_layout(config_dir: Path, key: str) -> SavedLayout | None:
    """The layout saved under ``key``, or None if there is none."""
    config = _read(config_dir / LAYOUTS_FILE)
    if key not in config:
        logger.info("No layout is saved for these displays (key %s).", key)
        return None
    section = config[key]
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


def read_perspectives(config_dir: Path, key: str) -> dict[str, dict]:
    """The perspectives saved for the layout ``key``, by name."""
    config = _read(config_dir / f"{key}.persp")
    logger.info("Loaded perspectives: %s", config.sections())
    return {
        name: {
            "central_disp": int(config[name]["central_disp"]),
            "viewer_pos": _str_to_list(config[name]["viewer_pos"], item_len=1),
            "swivels": _str_to_list(config[name]["swivels"], item_len=4, strings=True),
            "tilts": _str_to_list(config[name]["tilts"], item_len=3),
        }
        for name in config.sections()
    }


def write_perspectives(config_dir: Path, key: str, perspectives: Mapping[str, dict]) -> None:
    """Save ``perspectives`` as all the perspectives of the layout ``key``."""
    config = configparser.ConfigParser()
    for name, perspective in perspectives.items():
        config[name] = {
            "central_disp": str(perspective["central_disp"]),
            "viewer_pos": _list_to_str(perspective["viewer_pos"], item_len=1),
            "swivels": _list_to_str(perspective["swivels"], item_len=4),
            "tilts": _list_to_str(perspective["tilts"], item_len=3),
        }
    logger.info("Saving perspectives: %s", config.sections())
    _write(config_dir / f"{key}.persp", config)


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


def _str_to_list(joined_list, item_len=1, strings=False):
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
                        if not strings:
                            logger.info("str_to_list: ValueError: not int or float: %s", sub_item)
                conv_item.append(val)
            conv_list.append(tuple(conv_item))
        return conv_list
