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

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp")

# Planning a batch re-lists the sources when a chosen image has gone; this bounds that
# for an entry that keeps disappearing, such as a dangling symlink (issue #135).
_MAX_RELISTS = 20


def is_supported_image(filename: str) -> bool:
    """Whether a file name has an extension Superpaper renders, in any letter case."""
    return filename.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS)


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
        sortmode: str,
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
        for relists in range(_MAX_RELISTS + 1):
            # An empty position would shift the others' images onto the wrong displays.
            if any(not image_list.files for image_list in self._lists):
                return []
            if self._pending is None:
                self._pending = _plan_batch(self._lists)
            files, counters = self._pending
            if all(os.path.isfile(path) for path in files):
                if not peek:
                    for image_list, counter in zip(self._lists, counters):
                        image_list.counter = counter
                    self._pending = None
                return list(files)
            self._pending = None
            if relists == _MAX_RELISTS:
                break
            logger.info("An image has gone since the sources were listed; listing them again.")
            self._lists = self._list_images()
        logger.info("Giving up after listing the sources %d times: images keep disappearing.", _MAX_RELISTS)
        return []

    def _list_images(self) -> list[_ImageList]:
        """List the supported images of every position's sources, each image once."""
        lists = []
        for paths in self._sources:
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
            unique = []
            seen = set()
            for image in images:
                identity = _file_identity(image)
                if identity not in seen:
                    seen.add(identity)
                    unique.append(image)
            lists.append(_ImageList(unique, self._sortmode))
        return lists


class _ImageList:
    """One position's images in slideshow order, rearranged each time they have all been shown."""

    def __init__(self, files: list[str], sortmode: str):
        self.counter = 0
        self.files = files
        self.sortmode = sortmode
        self.arrange()

    def prepare_cycle(self) -> None:
        """Start the next round once every image has been shown."""
        if self.counter >= len(self.files):
            self.counter = 0
            self.arrange()

    def arrange(self) -> None:
        if self.sortmode == "shuffle":
            random.shuffle(self.files)
        elif self.sortmode == "date_seeded_shuffle":
            today = datetime.datetime.now()  # noqa: DTZ005  # intentional local-time seed
            random.Random(today.strftime("%Y%m%d%H")).shuffle(self.files)
        elif self.sortmode == "alphabetical":
            self.files.sort()
        else:
            logger.info("Unknown sort mode: %s", self.sortmode)


def _file_identity(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _plan_batch(lists: list[_ImageList]) -> tuple[list[str], list[int]]:
    """Choose the next image for every position, each image at most once if that is
    possible: a maximum matching that otherwise keeps every position's own order.
    Returns the images and where each position's order continues afterwards."""
    candidates = []
    for image_list in lists:
        image_list.prepare_cycle()
        ordered = list(range(image_list.counter, len(image_list.files))) + list(range(image_list.counter))
        candidates.append(
            [(image_list.files[index], index + 1, _file_identity(image_list.files[index])) for index in ordered]
        )

    image_to_position: dict[str, int] = {}
    selected: list[tuple[str, int] | None] = [None] * len(candidates)

    def assign(position, visited):
        for path, counter, identity in candidates[position]:
            if identity in visited:
                continue
            visited.add(identity)
            previous = image_to_position.get(identity)
            if previous is None or assign(previous, visited):
                image_to_position[identity] = position
                selected[position] = (path, counter)
                return True
        return False

    # Reverse order preserves the earliest position's first choice when several
    # maximum matchings are otherwise equivalent.
    for position in reversed(range(len(candidates))):
        assign(position, set())

    # If uniqueness is impossible, duplicates are preferable to an incomplete batch
    # that could shift images onto the wrong displays.
    for position, choices in enumerate(candidates):
        if selected[position] is None:
            path, counter, _identity = choices[0]
            selected[position] = (path, counter)

    completed = [choice for choice in selected if choice is not None]
    return ([choice[0] for choice in completed], [choice[1] for choice in completed])
