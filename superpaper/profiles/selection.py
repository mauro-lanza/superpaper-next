"""Which images a profile shows now, and which come next.

A profile's sources (image files and folders) are listed when its images are first
needed, never when the profile is loaded, so listing every profile's folders doesn't
slow down starting, reloading or saving. A slideshow goes through the images in the
profile's sort order and avoids showing one image on two displays at once.
"""

import datetime
import logging
import os
import random
import threading
from collections.abc import Callable, Sequence
from typing import Literal, NamedTuple, assert_never, get_args

logger = logging.getLogger(__name__)

SortMode = Literal["shuffle", "alphabetical", "date_seeded_shuffle"]
SORT_MODES: tuple[SortMode, ...] = get_args(SortMode)

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp")

# Planning a batch re-lists the sources when a chosen image has gone; this bounds that
# for an entry that keeps disappearing, such as a dangling symlink.
_MAX_RELISTS = 20


def is_supported_image(filename: str) -> bool:
    """Whether a file name has an extension Superpaper renders, in any letter case."""
    return filename.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS)


def is_folder(path: str) -> bool:
    return os.path.isdir(path)


def is_file(path: str) -> bool:
    return os.path.isfile(path)


def real_file(path: str) -> str | None:
    """The path with symlinks resolved, or None if it isn't a file."""
    resolved = os.path.realpath(path)
    return resolved if os.path.isfile(resolved) else None


def first_image(path: str) -> str | None:
    """The image file itself, or the first supported image of a folder in name order; None if neither."""
    if os.path.isdir(path):
        try:
            names = sorted(os.listdir(path))
        except OSError as error:
            logger.warning("A source folder could not be listed: '%s': %s", path, error)
            return None
        return next((os.path.join(path, name) for name in names if is_supported_image(name)), None)
    if os.path.isfile(path):
        return path
    return None


class Selection:
    """The images a profile shows now, and which come next.

    ``sources`` has, for each position (a display, or a span group), the image files and
    folders its images come from; ``size`` is how many images a complete selection has.
    ``images`` are the images to start from, and ``remember`` is called with every new
    selection, to keep it across restarts ([] when it is cleared).
    """

    def __init__(
        self,
        sources: Sequence[Sequence[str]],
        sortmode: SortMode,
        size: int,
        *,
        images: Sequence[str] | None = None,
        remember: Callable[[list[str]], None] | None = None,
    ):
        self._sources = [list(paths) for paths in sources]
        self._sortmode = sortmode
        self._size = size
        self._selected = list(images) if images else None
        self._remember = remember
        # Changes come from the wallpaper change thread and previews from the UI thread.
        self._lock = threading.Lock()
        self._lists: list[_ImageList] | None = None
        self._pending: tuple[list[str], list[int]] | None = None
        self._skipped: list[str] = []

    def take_skipped(self) -> list[str]:
        """The images passed over since the last call because they had gone, each once."""
        with self._lock:
            skipped, self._skipped = self._skipped, []
            return skipped

    def _note_skipped(self, files: Sequence[str]) -> None:
        self._skipped += [path for path in files if path not in self._skipped]

    @property
    def images(self) -> list[str] | None:
        """The selected images, or None."""
        with self._lock:
            return list(self._selected) if self._selected else None

    def is_complete(self) -> bool:
        """Whether the selection has an image for every position, and they are all there."""
        with self._lock:
            return self._is_complete()

    def current(self) -> list[str]:
        """The images to show now: the selection if it is complete, otherwise the first
        images in order. Nothing changes, so a selection whose images are missing for
        now (an unmounted drive, say) is kept for when they are back."""
        with self._lock:
            if self._is_complete():
                return list(self._selected or [])
            self._note_skipped([path for path in self._selected or [] if not os.path.isfile(path)])
            return self._next_batch(peek=True)

    def advance(self) -> list[str]:
        """Move on to the next images, which become the selection; [] if there aren't
        images for every position."""
        with self._lock:
            files = self._next_batch(peek=False)
            if not files or len(files) != self._size:
                return []
            self._select(files)
            return list(files)

    def pin(self, files: Sequence[str] | None) -> None:
        """Make ``files`` the selection, or clear it."""
        with self._lock:
            self._select(list(files) if files else None)

    def _select(self, files: list[str] | None) -> None:
        self._selected = files
        if self._remember is not None:
            self._remember(list(files or []))

    def _is_complete(self) -> bool:
        return bool(
            self._selected
            and len(self._selected) == self._size
            and all(os.path.isfile(path) and is_supported_image(path) for path in self._selected)
        )

    def _next_batch(self, *, peek: bool) -> list[str]:
        """The next image for every position, chosen once and kept until it is taken."""
        if self._lists is None:
            self._lists = self._list_images()
        elif self._pending is None:
            # Images added to a source join when its cycle has been shown, not mid-cycle.
            for image_list, paths in zip(self._lists, self._sources, strict=True):
                if image_list.is_finished():
                    image_list.relist(_list_position(paths))
        for relists in range(_MAX_RELISTS + 1):
            # An empty position would shift the others' images onto the wrong displays.
            if any(not image_list.images for image_list in self._lists):
                return []
            if self._pending is None:
                self._pending = _plan_batch(self._lists)
            files, counters = self._pending
            if all(os.path.isfile(path) for path in files):
                if not peek:
                    for image_list, counter in zip(self._lists, counters, strict=True):
                        image_list.counter = counter
                    self._pending = None
                return list(files)
            self._pending = None
            self._note_skipped([path for path in files if not os.path.isfile(path)])
            if relists == _MAX_RELISTS:
                break
            logger.info("An image has gone since the sources were listed; listing them again.")
            self._lists = self._list_images()
        logger.info("Giving up after listing the sources %d times: images keep disappearing.", _MAX_RELISTS)
        return []

    def _list_images(self) -> list[_ImageList]:
        return [_ImageList(_list_position(paths), self._sortmode) for paths in self._sources]


class _Image(NamedTuple):
    path: str
    identity: str


def _list_position(paths: Sequence[str]) -> list[_Image]:
    """List the supported images of one position's sources, each image once."""
    images = []
    for path in paths:
        if os.path.isfile(path):
            if is_supported_image(path):
                images.append(path)
            continue
        try:
            names = os.listdir(path)
        except FileNotFoundError:
            logger.warning("A source was not found: '%s'. Use absolute paths for best reliability.", path)
            continue
        except OSError as error:
            logger.warning("A source could not be listed: '%s': %s", path, error)
            continue
        images += [os.path.join(path, name) for name in names if is_supported_image(name)]
    # The same file can be included through overlapping folders, explicit
    # paths or symlinks. Keep its first occurrence only.
    unique: dict[str, _Image] = {}
    for image in images:
        identity = os.path.normcase(os.path.realpath(image))
        unique.setdefault(identity, _Image(image, identity))
    return list(unique.values())


class _ImageList:
    """One position's images in slideshow order, rearranged each time they have all been shown."""

    def __init__(self, images: list[_Image], sortmode: SortMode):
        self.counter = 0
        self.images = images
        self.sortmode = sortmode
        self.arrange()

    def is_finished(self) -> bool:
        return 0 < len(self.images) <= self.counter

    def relist(self, listed: list[_Image]) -> None:
        """Start the next round over ``listed``: the images still there in their current
        order, then the new ones."""
        present = {image.identity for image in listed}
        kept = [image for image in self.images if image.identity in present]
        kept_identities = {image.identity for image in kept}
        self.images = kept + [image for image in listed if image.identity not in kept_identities]
        self.counter = 0
        self.arrange()

    def arrange(self) -> None:
        match self.sortmode:
            case "shuffle":
                random.shuffle(self.images)
            case "date_seeded_shuffle":
                today = datetime.datetime.now()  # noqa: DTZ005  # intentional local-time seed
                random.Random(today.strftime("%Y%m%d%H")).shuffle(self.images)
            case "alphabetical":
                self.images.sort(key=lambda image: image.path)
            case _:
                assert_never(self.sortmode)


def _plan_batch(lists: list[_ImageList]) -> tuple[list[str], list[int]]:
    """Choose the next image for every position, each image at most once if that is
    possible: a maximum matching that otherwise keeps every position's own order.
    Returns the images and where each position's order continues afterwards."""
    candidates: list[list[tuple[_Image, int]]] = []
    for image_list in lists:
        count = len(image_list.images)
        ordered = [*range(image_list.counter, count), *range(image_list.counter)]
        candidates.append([(image_list.images[index], index + 1) for index in ordered])

    image_to_position: dict[str, int] = {}
    selected: list[tuple[str, int] | None] = [None] * len(candidates)

    def assign(position: int, visited: set[str]) -> bool:
        for image, counter in candidates[position]:
            if image.identity in visited:
                continue
            visited.add(image.identity)
            previous = image_to_position.get(image.identity)
            if previous is None or assign(previous, visited):
                image_to_position[image.identity] = position
                selected[position] = (image.path, counter)
                return True
        return False

    # Reverse order preserves the earliest position's first choice when several
    # maximum matchings are otherwise equivalent.
    for position in reversed(range(len(candidates))):
        assign(position, set())

    # If uniqueness is impossible, duplicates are preferable to an incomplete batch
    # that could shift images onto the wrong displays.
    chosen = []
    for position, choices in enumerate(candidates):
        choice = selected[position]
        if choice is None:
            image, counter = choices[0]
            choice = (image.path, counter)
        chosen.append(choice)
    return ([path for path, _ in chosen], [counter for _, counter in chosen])
