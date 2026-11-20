"""Rendered wallpapers on disk, in the cache directory.

A saved profile's renders are named after its ProfileId's value. <id>-a.png and <id>-b.png
(.jpg on Windows) take turns, because some desktops ignore a wallpaper file that is
replaced in place, and <id>-a-crop-0.png and so on hold one image per display for the
desktops that set one per display. Everything else rendered (the editor's Apply, the
align test, the command line) is a draft, kept the same way in preview/ as draft-a.png
and draft-b.png. Files are found by their exact names, never by a prefix.
"""

import io
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from superpaper.files import write_atomically

if TYPE_CHECKING:
    from superpaper.geometry.displays import Layout

logger = logging.getLogger(__name__)

_DRAFTS = "preview"
"""The cache subdirectory of the drafts."""

# <stem>-<turn>[-crop-<display>].<extension>[.sig]. No file name can be read two ways, because
# no ending of one of these names is itself one.
_RENDER_NAME = re.compile(
    r"(?P<stem>.+)-(?P<turn>[ab])(?:-crop-(?P<piece>[0-9]+))?\.(?:png|jpg)(?P<signature>\.sig)?", re.DOTALL
)


@dataclass(frozen=True, slots=True)
class Slot:
    """Where the renders of one saved profile, or the drafts, are kept."""

    directory: Path
    stem: str


@dataclass(frozen=True, slots=True)
class Rendered:
    """A render on disk: the desktop image, and one image per display if it was cut up."""

    image: Path
    pieces: list[Path]
    modified: int
    """When the image was written, in nanoseconds since the epoch."""
    signature: str | None
    """What the render was made from, as given to save(); None if it wasn't kept."""


@dataclass(frozen=True, slots=True)
class _Name:
    stem: str
    turn: str
    piece: int | None
    signature: bool


def slot(cache_dir: Path, profile_id_value: str) -> Slot:
    """The renders of the saved profile; ``profile_id_value`` must be a ProfileId.value."""
    return Slot(cache_dir, profile_id_value)


def draft_slot(cache_dir: Path) -> Slot:
    """The drafts' renders."""
    return Slot(cache_dir / _DRAFTS, "draft")


def save(slot: Slot, image: Image.Image, *, extension: str, signature: str) -> Path:
    """Write ``image`` as the slot's next render, as a ``jpg`` or ``png`` file, in one step,
    and return its path. ``signature`` is kept beside it, to tell later what it was made from.

    The render that isn't the newest is replaced, so the one on screen stays as it is.
    """
    newest = latest(slot)
    turn = "b" if newest is not None and newest.image.stem.endswith("-a") else "a"
    path = slot.directory / f"{slot.stem}-{turn}.{extension}"
    slot.directory.mkdir(parents=True, exist_ok=True)
    write_atomically(path, _encode(image, "JPEG" if extension == "jpg" else "PNG"))
    write_atomically(_signature_path(path), signature.encode())
    return path


def cut_pieces(image: Path, layout: Layout) -> list[Path]:
    """Cut the render ``image`` into one image per display of ``layout``, kept beside it,
    in the layout's display order."""
    pieces = []
    with Image.open(image) as desktop:
        for index, (res, offset) in enumerate(zip(layout.resolutions(), layout.digital_offsets(), strict=True)):
            piece = desktop.crop((offset[0], offset[1], offset[0] + res[0], offset[1] + res[1]))
            path = image.with_name(f"{image.stem}-crop-{index}.png")
            write_atomically(path, _encode(piece, "PNG"))
            pieces.append(path)
    return pieces


def forget_previous(image: Path) -> None:
    """Delete the other render of ``image``'s slot, and its pieces, now that ``image`` is
    on screen."""
    name = _parse(image.name)
    if name is None:
        return
    for path, other in _renders(Slot(image.parent, name.stem)):
        if other.turn != name.turn:
            _remove(path)


def latest(slot: Slot) -> Rendered | None:
    """The slot's newest render, or None if it has none."""
    renders = _renders(slot)
    images = []
    for path, name in renders:
        if name.piece is None and not name.signature:
            try:
                images.append((path.stat().st_mtime_ns, path, name.turn))
            except OSError:  # removed meanwhile
                continue
    if not images:
        return None
    modified, image, turn = max(images)
    pieces = sorted((name.piece, path) for path, name in renders if name.turn == turn and name.piece is not None)
    return Rendered(image, [path for _, path in pieces], modified, _read_signature(image))


def sweep(cache_dir: Path, keep: Iterable[str]) -> None:
    """Delete the renders of every profile but those whose stems are ``keep``: profiles
    deleted or renamed since they were rendered. Drafts, and files that aren't renders,
    are left alone."""
    stems = set(keep)
    try:
        entries = list(os.scandir(cache_dir))
    except OSError as error:
        logger.warning("Could not look for old renders in %s: %s", cache_dir, error)
        return
    removed = 0
    for entry in entries:
        name = _parse(entry.name)
        if name is not None and name.stem not in stems and entry.is_file(follow_symlinks=False):
            removed += _remove(Path(entry.path))
    if removed:
        logger.info("Removed %d renders of profiles that no longer exist.", removed)


def _renders(slot: Slot) -> list[tuple[Path, _Name]]:
    try:
        filenames = os.listdir(slot.directory)
    except FileNotFoundError:
        return []
    renders = []
    for filename in filenames:
        name = _parse(filename)
        if name is not None and name.stem == slot.stem:
            renders.append((slot.directory / filename, name))
    return renders


def _parse(filename: str) -> _Name | None:
    match = _RENDER_NAME.fullmatch(filename)
    if match is None:
        return None
    piece = match["piece"]
    return _Name(match["stem"], match["turn"], None if piece is None else int(piece), match["signature"] is not None)


def _signature_path(image: Path) -> Path:
    return image.with_name(f"{image.name}.sig")


def _read_signature(image: Path) -> str | None:
    try:
        return _signature_path(image).read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return None


def _encode(image: Image.Image, image_format: str) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=image_format, quality=95)  # the quality applies to JPEG only
    return buffer.getvalue()


def _remove(path: Path) -> bool:
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as error:
        logger.warning("Could not remove %s: %s", path, error)
        return False
    return True
