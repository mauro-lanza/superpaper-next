"""Finding the displays: asks the desktop for its monitors, and loads the layout saved for them."""

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path

from screeninfo import Monitor, get_monitors

from superpaper import display_store
from superpaper.displays import Display, Layout

logger = logging.getLogger(__name__)

FALLBACK_PHYS_SIZE_MM = (509, 286)
"""A 23 inch display: a display of unknown size is assumed to be one, to have it stand out."""


class DisplayDetectionError(RuntimeError):
    """Raised when monitor enumeration cannot produce a usable display list."""

    def __init__(self, attempts: int):
        super().__init__(f"Unable to detect any displays after {attempts} attempts.")
        self.attempts = attempts


def detect_layout(config_dir: Path, *, max_attempts: int = 3, retry_delay: float = 0.25) -> Layout:
    """Detect the displays and load the layout saved for them from ``config_dir``."""
    return display_store.load(config_dir, detect_displays(max_attempts=max_attempts, retry_delay=retry_delay))


def detect_displays(*, max_attempts: int = 3, retry_delay: float = 0.25) -> tuple[Display, ...]:
    """
    Detect the displays, sorted by their position on the desktop. Offsets are sanitized so
    that they are always non-negative.

    Only on the main thread: on Linux, screeninfo detects displays with libXrandr, which
    corrupts memory when two threads use it at once, and GTK uses it on the main thread.
    """
    # https://github.com/rr-/screeninfo
    if threading.current_thread() is not threading.main_thread():
        message = "Displays can only be detected on the main thread."
        raise RuntimeError(message)
    if max_attempts < 1:
        message = "max_attempts must be at least 1"
        raise ValueError(message)
    if retry_delay < 0:
        message = "retry_delay cannot be negative"
        raise ValueError(message)

    monitors = None
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            monitors = get_monitors()
        except Exception as error:
            last_error = error
            logger.warning("Display detection attempt %d/%d failed: %s", attempt, max_attempts, error)
        if monitors:
            break
        if attempt < max_attempts:
            logger.info("Display detection returned no displays; retrying.")
            time.sleep(retry_delay)
    else:
        error = DisplayDetectionError(max_attempts)
        if last_error is not None:
            raise error from last_error
        raise error

    displays = [_display_of(monitor) for monitor in monitors]
    leftmost_offset = min(display.digital_offset[0] for display in displays)
    topmost_offset = min(display.digital_offset[1] for display in displays)
    if leftmost_offset < 0 or topmost_offset < 0:
        displays = [
            replace(
                display,
                digital_offset=(
                    display.digital_offset[0] - leftmost_offset,
                    display.digital_offset[1] - topmost_offset,
                ),
            )
            for display in displays
        ]
    displays.sort(key=lambda display: display.digital_offset)

    logger.info(
        "detect_displays output: %s displays, resolutions %s, offsets %s",
        len(displays),
        [display.resolution for display in displays],
        [display.digital_offset for display in displays],
    )
    for display in displays:
        logger.info("%s", display)
    return tuple(displays)


def _display_of(monitor: Monitor) -> Display:
    resolution = (monitor.width, monitor.height)
    landscape = resolution[0] > resolution[1]
    failed = not (monitor.width_mm and monitor.height_mm)
    sizes = FALLBACK_PHYS_SIZE_MM if failed else (monitor.width_mm, monitor.height_mm)
    # Physical rotation has to match the resolution.
    small, large = sorted(sizes)
    phys_size_mm = (large, small) if landscape else (small, large)
    return Display(resolution, (monitor.x, monitor.y), phys_size_mm, failed, monitor.name)
