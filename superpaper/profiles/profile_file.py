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
from dataclasses import dataclass, field, replace
from typing import Literal, assert_never, get_args

from superpaper.geometry.perspective import Default, Disabled, PerspectiveChoice, choice_label, parse_choice
from superpaper.geometry.units import MM_PER_INCH
from superpaper.profiles.selection import SORT_MODES, SortMode, is_supported_image
from superpaper.user_input import Offset, parse_float

logger = logging.getLogger(__name__)

SpanMode = Literal["single", "advanced", "multi"]
SPAN_MODES: tuple[SpanMode, ...] = get_args(SpanMode)
MIN_DELAY = 5
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

    def display_corrections(self, resolutions: Sequence[tuple[int, int]]) -> DisplayCorrections:
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
                    offsets = (list(values) + count * [(0, 0)])[:count]
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
                    ppi_array = [
                        math.sqrt(res[0] ** 2 + res[1] ** 2) / inch
                        for inch, res in zip(inches[:count], resolutions, strict=True)
                    ]
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
    profile = Profile(name="default_profile")
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            profile = _with_setting(profile, key, value.strip(), line)
        elif line.strip():
            logger.info("Skipping a profile line without a setting: %s", line)
    return profile


def _with_setting(profile: Profile, key: str, value: str, line: str) -> Profile:
    """``profile`` with the setting of one ``key=value`` line applied."""
    if key == "name":
        return replace(profile, name=value)
    if key == "spanmode":
        mode = next((mode for mode in SPAN_MODES if mode == value.lower()), None)
        if mode is None:
            logger.info("Unknown span mode '%s' in profile '%s'.", value, profile.name)
            return profile
        return replace(profile, spanmode=mode)
    if key == "spangroups":
        try:
            return replace(profile, spangroups=parse_spangroups(value.split(",")))
        except ValueError as error:
            logger.info("Unusable spangroups '%s' in profile '%s': %s", value, profile.name, error)
            return replace(profile, spangroups=None)
    if key == "slideshow":
        return replace(profile, slideshow=value.lower() == "true")
    if key == "delay":
        delay = _numbers(key, value, float)[0]
        if not math.isfinite(delay) or delay <= 0:
            message = f"The setting {key}={value} needs a positive, finite number of seconds."
            raise ProfileFormatError(message)
        return replace(profile, delay=delay)
    if key == "sortmode":
        sortmode = next((mode for mode in SORT_MODES if mode == value.lower()), None)
        if sortmode is None:
            logger.info("Unknown sort mode '%s' in profile '%s'.", value, profile.name)
            return profile
        return replace(profile, sortmode=sortmode)
    if key == "offsets":
        # x1,y1;x2,y2;... in pixels, from the leftmost display.
        offsets = OffsetsCorrection(tuple(_parse_offset(pair) for pair in value.split(";")))
        return replace(profile, corrections=(*profile.corrections, offsets))
    if key == "bezels":
        return replace(profile, bezels=(*profile.bezels, *_numbers(key, value, float)))
    if key == "ppi":
        ppi = PpiCorrection(tuple(_numbers(key, value, int)))
        return replace(profile, corrections=(*profile.corrections, ppi))
    if key == "diagonal_inches":
        inches = _numbers(key, value, float)
        # Densities are pixels per inch of diagonal, so a diagonal of 0 makes the
        # profile unusable; earlier versions failed to load such a profile as well.
        if 0 in inches:
            message = "A display diagonal of 0 inches."
            raise ProfileFormatError(message)
        return replace(profile, corrections=(*profile.corrections, DiagonalCorrection(tuple(inches))))
    if key == "hotkey":
        return profile  # written by versions with global hotkeys; no longer used
    if key == "perspective":
        return replace(profile, perspective=parse_choice(value))
    if key == "zoom":
        zoom = parse_float(value)
        return replace(profile, zoom=1.0 if zoom is None else max(1.0, zoom))
    if key == "align":
        return replace(profile, pan=_parse_pan(value))
    if key == "selected":
        return replace(profile, selected=tuple(path for path in value.split(";") if path) or None)
    if key.startswith("display"):
        return replace(profile, sources=(*profile.sources, tuple(path for path in value.split(";") if path)))
    logger.info("Unknown setting in profile '%s': %s", profile.name, line)
    return profile


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
    spangroups: Sequence[Sequence[int]] | None = None,
    offsets: Sequence[Offset] = (),
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
    if profile.slideshow and profile.delay < MIN_DELAY:
        problems.append(f"The slideshow delay must be at least {MIN_DELAY} seconds.")
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


def _numbers[T: (int, float)](key: str, value: str, kind: type[T]) -> list[T]:
    """The ';'-separated numbers of a setting."""
    try:
        return [kind(item) for item in value.split(";")]
    except ValueError:
        message = f"The setting {key}={value} needs numbers separated by ';'."
        raise ProfileFormatError(message) from None


def parse_spangroups(groups: Sequence[str]) -> tuple[tuple[int, ...], ...]:
    """Each group of display ids, one digit per display, without duplicates, sorted.

    Raises ValueError naming the group that is empty or holds a non-digit.
    """
    parsed = []
    for group in groups:
        if not group:
            message = "A span group has no displays."
            raise ValueError(message)
        try:
            parsed.append(tuple(sorted({int(display) for display in group})))
        except ValueError:
            message = f"One of the display ids was not an integer: {group}"
            raise ValueError(message) from None
    return tuple(parsed)


def _parse_pan(value: str) -> tuple[float, float]:
    """The x,y pan of an align= value, each clamped to -1..1; none if it isn't two finite numbers."""
    match [parse_float(part) for part in value.split(",")[:2]]:
        case [float(x), float(y)]:
            return (min(1.0, max(-1.0, x)), min(1.0, max(-1.0, y)))
        case _:
            return (0.0, 0.0)


def _parse_offset(pair: str) -> tuple[int, int]:
    """One display's x,y offset; 0,0 if it isn't two integers."""
    try:
        x, y = pair.split(",")[:2]
        return (int(x), int(y))
    except ValueError:
        return (0, 0)


def _shift_by_bezels(
    offsets: list[tuple[int, int]], ppi_array: Sequence[float], bezels: Sequence[float], count: int
) -> list[tuple[int, int]]:
    """Move each display right by the bezels (in mm) between it and the leftmost one."""
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
