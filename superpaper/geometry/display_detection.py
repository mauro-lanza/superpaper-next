"""Finding the displays: asks the desktop for its monitors, and loads the layout saved for them."""

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path

from superpaper.desktop.backend import Desktop
from superpaper.desktop.monitors import Monitor
from superpaper.geometry import display_store
from superpaper.geometry.display_store import LoadedLayout
from superpaper.geometry.displays import Display

logger = logging.getLogger(__name__)

FALLBACK_PHYS_SIZE_MM = (509, 286)
"""A 23 inch display: a display of unknown size is assumed to be one, to have it stand out."""

MAX_ASPECT_MISMATCH = 0.1
"""Some EDIDs report junk sizes; one whose aspect ratio is this far off the pixels' is rejected."""

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.25


class DisplayDetectionError(RuntimeError):
    """Raised when monitor enumeration cannot produce a usable display list."""

    def __init__(self, attempts: int):
        super().__init__(f"Unable to detect any displays after {attempts} attempts.")


def detect_layout_or_default(config_dir: Path, desktop: Desktop) -> LoadedLayout:
    """Detect the displays and load the layout saved for them; the default arrangement,
    with the reason, if the saved one can't be used."""
    return display_store.load_or_default(config_dir, detect_displays(desktop))


def detect_displays(desktop: Desktop) -> tuple[Display, ...]:
    """
    Detect the displays, sorted by their position on the desktop. Offsets are sanitized so
    that they are always non-negative.

    Only on the main thread: on Linux, the monitors are queried with libXrandr, which
    corrupts memory when two threads use it at once, and GTK uses it on the main thread.
    """
    if threading.current_thread() is not threading.main_thread():
        message = "Displays can only be detected on the main thread."
        raise RuntimeError(message)

    displays = [_display_of(monitor) for monitor in _detect_monitors(desktop)]
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
    return tuple(displays)


def _detect_monitors(desktop: Desktop) -> list[Monitor]:
    """The monitors of the desktop, asking again when it reports none or fails."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        monitors = None
        last_error = None
        try:
            monitors = desktop.detect_monitors()
        except Exception as error:
            last_error = error
            logger.warning("Display detection attempt %d/%d failed: %s", attempt, MAX_ATTEMPTS, error)
        if monitors:
            return monitors
        if attempt < MAX_ATTEMPTS:
            logger.info("Display detection returned no displays; retrying.")
            time.sleep(RETRY_DELAY_SECONDS)
    raise DisplayDetectionError(MAX_ATTEMPTS) from last_error


def _display_of(monitor: Monitor) -> Display:
    resolution = (monitor.width, monitor.height)
    landscape = resolution[0] > resolution[1]
    width_mm, height_mm = monitor.width_mm, monitor.height_mm
    has_size = bool(width_mm and height_mm)
    failed = not has_size
    if has_size:
        mm_aspect = max(width_mm, height_mm) / min(width_mm, height_mm)
        pixel_aspect = max(resolution) / min(resolution)
        if abs(mm_aspect - pixel_aspect) / pixel_aspect > MAX_ASPECT_MISMATCH:
            logger.warning(
                "Ignoring implausible size of %s: reported %sx%s mm for %sx%s pixels.",
                monitor.name,
                monitor.width_mm,
                monitor.height_mm,
                monitor.width,
                monitor.height,
            )
            failed = True
    sizes = FALLBACK_PHYS_SIZE_MM if failed else (width_mm, height_mm)
    # Physical rotation has to match the resolution.
    small, large = sorted(sizes)
    phys_size_mm = (large, small) if landscape else (small, large)
    return Display(resolution, (monitor.x, monitor.y), phys_size_mm, failed, monitor.name)
