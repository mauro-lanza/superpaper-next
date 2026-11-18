"""The .profile format: a profile's settings as a value, and how they are read, written
and checked.

A profile file has a ``key=value`` line per setting; only the first "=" separates the
key, so values (paths) may contain "=". A line Superpaper doesn't know is skipped, so
files written by other versions keep loading, and only a value that can't be used makes
a file unusable.
"""

import logging
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, assert_never, get_args

from superpaper.geometry.perspective import (
    MM_PER_INCH,
    Default,
    Disabled,
    PerspectiveChoice,
    choice_label,
    parse_choice,
)
from superpaper.profiles.selection import SORT_MODES, SortMode, is_supported_image
from superpaper.settings import format_hotkey, parse_hotkey
from superpaper.user_input import Offset, parse_float

logger = logging.getLogger(__name__)

SpanMode = Literal["single", "advanced", "multi"]
SPAN_MODES: tuple[SpanMode, ...] = get_args(SpanMode)
MIN_DELAY = 20
"""The shortest slideshow delay, in seconds: rendering a wallpaper takes a while."""


class ProfileFormatError(ValueError):
    """A profile file has a setting Superpaper can't use."""


@dataclass(frozen=True, slots=True)
class OffsetsCorrection:
    """An offsets= line: each display's position offset in pixels."""

    offsets: tuple[Offset, ...]


@dataclass(frozen=True, slots=True)
class PpiCorrection:
    """A ppi= line: each display's pixel density."""

    ppi: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DiagonalCorrection:
    """A diagonal_inches= line: each display's diagonal, from which densities follow."""

    inches: tuple[float, ...]


Correction = OffsetsCorrection | PpiCorrection | DiagonalCorrection


@dataclass(frozen=True, slots=True)
class DisplayCorrections:
    """A profile's position corrections, worked out for the displays present."""

    ppimode: bool
    """Whether a single image is spanned with the advanced, PPI-corrected renderer."""
    ppi_array: Sequence[float]
    manual_offsets: list[tuple[int, int]]
    """Each display's offset in pixels, bezels included."""


@dataclass(frozen=True, slots=True)
class Profile:
    """A profile's settings: what a .profile file holds."""

    name: str
    spanmode: SpanMode = "single"
    spangroups: tuple[tuple[int, ...], ...] | None = None
    """The displays each image spans, with advanced spanning; None for one image on all."""
    slideshow: bool = True
    delay: float = 600.0
    """Seconds between slideshow images."""
    sortmode: SortMode = "shuffle"
    sources: tuple[tuple[str, ...], ...] = ()
    """For each display (multi) or span group, the image files and folders to show."""
    hotkey: tuple[str, ...] | None = None
    perspective: PerspectiveChoice = field(default_factory=Default)
    zoom: float = 1.0
    pan: tuple[float, float] = (0.0, 0.0)
    """Where the image sits when it overflows the desktop: -1 to 1 for each axis."""
    corrections: tuple[Correction, ...] = ()
    """The offsets=, ppi= and diagonal_inches= lines of profiles from before display
    layouts existed, in file order. What they mean depends on the displays present, so
    display_corrections works it out for a layout."""
    bezels: tuple[float, ...] = ()
    """A bezels= line: the millimetres between neighbouring displays."""
    selected: tuple[str, ...] | None = None
    """A selected= line written by an older version: the images it showed last."""

    @property
    def offsets(self) -> tuple[Offset, ...]:
        """Each display's position offset in pixels, as an offsets= line gives it."""
        return next((c.offsets for c in reversed(self.corrections) if isinstance(c, OffsetsCorrection)), ())

    @property
    def selection_size(self) -> int:
        """How many images the profile shows at once: one per configured display for
        multiple images, one per span group, or one."""
        if self.spanmode == "multi":
            return len(self.sources)
        if self.spanmode == "advanced" and self.spangroups:
            return len(self.spangroups)
        return 1

    def display_corrections(self, resolutions) -> DisplayCorrections:
        """Work out the position corrections for displays of ``resolutions``.

        Profiles from before display layouts existed correct positions with offsets=,
        ppi=, diagonal_inches= and bezels=. They apply in file order, as when earlier
        versions parsed the profile for the displays present then; the profile itself
        doesn't depend on which displays those are.
        """
        count = len(resolutions)
        ppimode = False
        ppi_array = count * [100]
        offsets = count * [(0, 0)]
        for correction in self.corrections:
            match correction:
                case OffsetsCorrection(values):
                    ppimode = True
                    offsets = list(values) + (count - len(values)) * [(0, 0)]
                case PpiCorrection(values):
                    ppimode = True
                    ppi_array = list(values)
                case DiagonalCorrection(inches) if len(inches) < count:
                    logger.info(
                        "%s display diagonals for %s displays: falling back to no PPI correction.", len(inches), count
                    )
                    ppimode = False
                    ppi_array = count * [100]
                case DiagonalCorrection(inches):
                    ppimode = True
                    ppi_array = [math.sqrt(res[0] ** 2 + res[1] ** 2) / inch for inch, res in zip(inches, resolutions)]
                case _:
                    assert_never(correction)
        if ppimode and self.bezels:
            offsets = _shift_by_bezels(offsets, ppi_array, self.bezels, count)
        logger.info("Corrections of '%s': PPIs %s, offsets %s", self.name, ppi_array, offsets)
        return DisplayCorrections(ppimode, ppi_array, offsets)


def parse(text: str) -> Profile:
    """The profile a .profile file's ``text`` describes.

    Raises ProfileFormatError for a value that can't be used, such as a delay that isn't
    a number or a display diagonal of 0 inches.
    """
    defaults = Profile(name="default_profile")
    name = defaults.name
    spanmode = defaults.spanmode
    spangroups = defaults.spangroups
    slideshow = defaults.slideshow
    delay = defaults.delay
    sortmode = defaults.sortmode
    sources = list(defaults.sources)
    hotkey = defaults.hotkey
    perspective = defaults.perspective
    zoom = defaults.zoom
    pan = defaults.pan
    corrections = list(defaults.corrections)
    bezels = list(defaults.bezels)
    selected = defaults.selected
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            if line.strip():
                logger.info("Skipping a profile line without a setting: %s", line)
            continue
        value = value.strip()
        if key == "name":
            name = value
        elif key == "spanmode":
            mode = next((mode for mode in SPAN_MODES if mode == value.lower()), None)
            if mode is None:
                logger.info("Unknown span mode '%s' in profile '%s'.", value, name)
            else:
                spanmode = mode
        elif key == "spangroups":
            try:
                spangroups = parse_spangroups(value.split(","))
            except ValueError:
                spangroups = None
        elif key == "slideshow":
            slideshow = value.lower() == "true"
        elif key == "delay":
            delay = _numbers(key, value, float)[0]
            if not math.isfinite(delay) or delay <= 0:
                message = f"The setting {key}={value} needs a positive, finite number of seconds."
                raise ProfileFormatError(message)
        elif key == "sortmode":
            chosen = next((mode for mode in SORT_MODES if mode == value.lower()), None)
            if chosen is None:
                logger.info("Unknown sort mode '%s' in profile '%s'.", value, name)
            else:
                sortmode = chosen
        elif key == "offsets":
            # x1,y1;x2,y2;... in pixels, from the leftmost display.
            corrections.append(OffsetsCorrection(tuple(_parse_offset(pair) for pair in value.split(";"))))
        elif key == "bezels":
            bezels += _numbers(key, value, float)
        elif key == "ppi":
            corrections.append(PpiCorrection(tuple(_numbers(key, value, int))))
        elif key == "diagonal_inches":
            inches = _numbers(key, value, float)
            # Densities are pixels per inch of diagonal, so a diagonal of 0 makes the
            # profile unusable; earlier versions failed to load such a profile as well.
            if 0 in inches:
                message = "A display diagonal of 0 inches."
                raise ProfileFormatError(message)
            corrections.append(DiagonalCorrection(tuple(inches)))
        elif key == "hotkey":
            hotkey = parse_hotkey(value)
        elif key == "perspective":
            perspective = parse_choice(value)
        elif key == "zoom":
            zoom = parse_float(value)
            zoom = 1.0 if zoom is None else max(1.0, zoom)
        elif key == "align":
            try:
                parts = value.split(",")
                pan = (min(1.0, max(-1.0, float(parts[0]))), min(1.0, max(-1.0, float(parts[1]))))
            except ValueError, IndexError:
                pan = (0.0, 0.0)
        elif key == "selected":
            selected = tuple(path for path in value.split(";") if path) or None
        elif key.startswith("display"):
            sources.append(tuple(path for path in value.split(";") if path))
        else:
            logger.info("Unknown setting in profile '%s': %s", name, line)
    return Profile(
        name=name,
        spanmode=spanmode,
        spangroups=spangroups,
        slideshow=slideshow,
        delay=delay,
        sortmode=sortmode,
        sources=tuple(sources),
        hotkey=hotkey,
        perspective=perspective,
        zoom=zoom,
        pan=pan,
        corrections=tuple(corrections),
        bezels=tuple(bezels),
        selected=selected,
    )


def serialize(profile: Profile) -> str:
    """The text of ``profile``'s .profile file. The selection isn't part of it: a saved
    profile's is remembered separately."""
    lines = [f"name={profile.name}", f"spanmode={profile.spanmode}"]
    if profile.spangroups:
        lines.append("spangroups=" + ",".join("".join(map(str, group)) for group in profile.spangroups))
    lines.append(f"slideshow={profile.slideshow}")
    if profile.slideshow:
        lines.append(f"delay={profile.delay}")
        lines.append(f"sortmode={profile.sortmode}")
    for correction in profile.corrections:
        match correction:
            case OffsetsCorrection(offsets):
                lines.append("offsets=" + ";".join(f"{x},{y}" for x, y in offsets))
            case PpiCorrection(ppi):
                lines.append("ppi=" + ";".join(map(str, ppi)))
            case DiagonalCorrection(inches):
                lines.append("diagonal_inches=" + ";".join(map(str, inches)))
            case _:
                assert_never(correction)
    if profile.bezels:
        lines.append("bezels=" + ";".join(map(str, profile.bezels)))
    if profile.hotkey:
        lines.append("hotkey=" + format_hotkey(profile.hotkey))
    lines.append(f"perspective={choice_label(profile.perspective)}")
    if profile.zoom != 1.0:
        lines.append(f"zoom={profile.zoom}")
    if profile.pan != (0.0, 0.0):
        lines.append(f"align={profile.pan[0]},{profile.pan[1]}")
    lines.extend(f"display{index}paths={';'.join(paths)}" for index, paths in enumerate(profile.sources))
    return "\n".join(lines) + "\n"


def draft(
    images: Sequence[str],
    *,
    spanmode: SpanMode,
    perspective: PerspectiveChoice | None = None,
    spangroups=None,
    offsets=(),
) -> Profile:
    """Settings to show ``images`` with once, outside any saved profile: from the command
    line or by the align test.

    Advanced spanning uses ``offsets``, each display's (x, y) in pixels, and applies the
    ``perspective`` chosen; without one, none is applied.
    """
    corrections = (OffsetsCorrection(tuple(offsets)),) if offsets and spanmode == "advanced" else ()
    return Profile(
        name="cli",
        spanmode=spanmode,
        spangroups=tuple(tuple(group) for group in spangroups) if spangroups else None,
        slideshow=False,
        sources=tuple((image,) for image in images),
        perspective=perspective if perspective is not None else Disabled(),
        corrections=corrections,
    )


def validate(profile: Profile) -> list[str]:
    """What keeps ``profile`` from being saved or shown, for the user to fix; [] if nothing.

    Checks the sources on disk: each must be a supported image, or a folder with one.
    """
    problems = []
    if not profile.name.strip():
        problems.append("You must enter a name for the profile.")
    if profile.spanmode == "single" and len(profile.sources) > 1:
        problems.append("When spanning a single image across all monitors, only one paths field is needed.")
    if profile.spanmode == "multi" and len(profile.sources) < 2:
        problems.append("When setting a different image on every display, each display needs its own paths field.")
    if profile.slideshow and profile.delay < MIN_DELAY:
        problems.append(
            "It is advisable to set the slideshow delay to be at least 20 seconds due to the time "
            "the image processing takes."
        )
    return problems + _source_problems(profile)


def _source_problems(profile: Profile) -> list[str]:
    if not profile.sources:
        return ["You must enter at least one path for images."]
    if profile.sources == ((),):
        return ["At least one path for wallpapers must be given."]
    if () in profile.sources:
        return ["Add an image source for every display present."]
    if profile.spangroups and len(profile.sources) < len(profile.spangroups):
        return ["Add an image source for every span group."]
    for paths in profile.sources:
        for path in paths:
            if os.path.isdir(path):
                try:
                    has_images = any(is_supported_image(name) for name in os.listdir(path))
                except OSError as error:
                    return [f"Path '{path}' could not be read: {error}"]
                if not has_images:
                    return [f"Path '{path}' does not contain supported image files."]
            elif os.path.isfile(path):
                if not is_supported_image(path):
                    return [f"Image '{path}' is not a supported image file."]
            else:
                return [f"Path '{path}' was not recognized as a directory."]
    return []


def _numbers(key: str, value: str, kind):
    """The ';'-separated numbers of a setting."""
    try:
        return [kind(item) for item in value.split(";")]
    except ValueError:
        message = f"The setting {key}={value} needs numbers separated by ';'."
        raise ProfileFormatError(message) from None


def parse_spangroups(groups: Sequence[str]) -> tuple[tuple[int, ...], ...]:
    """Each group of display ids, one digit per display, without duplicates, sorted.

    Raises ValueError naming the group that holds a non-digit.
    """
    parsed = []
    for group in groups:
        try:
            parsed.append(tuple(sorted({int(display) for display in group})))
        except ValueError:
            message = f"One of the display ids was not an integer: {group}"
            raise ValueError(message) from None
    return tuple(parsed)


def _parse_offset(pair: str) -> tuple[int, int]:
    """One display's x,y offset; 0,0 if it isn't two integers."""
    try:
        x, y = pair.split(",")[:2]
        return (int(x), int(y))
    except ValueError:
        return (0, 0)


def _shift_by_bezels(offsets, ppi_array, bezels, count):
    """Move each display right by the bezels (in mm) between it and the leftmost one."""
    if not ppi_array:
        logger.error("Couldn't compute bezel offsets without pixel densities.")
        return offsets
    max_ppi = max(ppi_array)
    inch_per_mm = 1.0 / MM_PER_INCH
    bezel_px = [0]  # never offset 1st disp, anchor to it.
    for bezel_mm in bezels:
        bezel_px.append(round(float(max_ppi) * inch_per_mm * bezel_mm))
    # Too few bezels: the rest are 0. Too many: the tail is ignored.
    bezel_px += (count - len(bezel_px)) * [0]
    shifted = list(offsets)
    for i in range(1, min(len(bezel_px), count)):
        # Each display moves by its own bezel plus those of the displays to its left.
        bezel_px[i] += bezel_px[i - 1]
        shifted[i] = (shifted[i][0] + bezel_px[i], shifted[i][1])
    return shifted
