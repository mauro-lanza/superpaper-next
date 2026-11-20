"""The profile editor's rules, without any widgets.

A ProfileForm holds what the editor's fields show: text where the user types, numbers where
they drag, choices where they pick. A UI reads its fields into one, shows one in its
fields, and calls the functions here to turn it into a Profile and to tell whether it
changed. Saving, deleting, reverting and applying what it describes is superpaper.profile_actions.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import assert_never

from superpaper.geometry.canvas import DisplayArea
from superpaper.geometry.displays import Layout
from superpaper.geometry.perspective import Default, PerspectiveChoice
from superpaper.hotkey_keys import format_hotkey, parse_hotkey
from superpaper.profiles import profile_file
from superpaper.profiles.profile_file import Correction, OffsetsCorrection, Profile, SpanMode
from superpaper.profiles.profile_store import StoredProfile
from superpaper.profiles.selection import SortMode, is_file
from superpaper.user_input import Offset, OffsetError, parse_float

SORT_LABELS: dict[SortMode, str] = {
    "shuffle": "Shuffle",
    "alphabetical": "Alphabetical",
    "date_seeded_shuffle": "Date seeded shuffle",
}
"""The slideshow orders as the user picks them."""
_SORT_MODE_OF_LABEL = {label: mode for mode, label in SORT_LABELS.items()}

SpanGroups = tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class ProfileForm:
    """What the editor's fields hold, as the user sees them."""

    name: str
    span_mode: SpanMode
    slideshow: bool
    delay_minutes: str
    sort_label: str | None
    """One of the SORT_LABELS, or None while the dropdown has no choice."""
    hotkey_enabled: bool
    hotkey: str
    offsets_applied: bool
    offsets: tuple[str, ...]
    """The "x,y" field of each display."""
    spangroups_enabled: bool
    spangroup_choices: tuple[int, ...]
    """The group chosen for each display."""
    perspective: PerspectiveChoice
    zoom_pct: int
    pan_pct: tuple[int, int]
    per_target_sources: bool
    """Whether each source is listed for a display or span group, or all are for one image."""
    sources: tuple[tuple[str, str], ...]
    """The source list's rows: the display or group as listed ("" if not per target) and the path."""


def uses_spangroups(span_mode: SpanMode, spangroups_enabled: bool) -> bool:
    return spangroups_enabled and span_mode == "advanced"


def sources_per_target(span_mode: SpanMode, spangroups_enabled: bool) -> bool:
    """Whether the sources are listed for each display or span group."""
    return span_mode == "multi" or uses_spangroups(span_mode, spangroups_enabled)


def spangroups_of(choices: Sequence[int]) -> SpanGroups:
    """The groups of displays the ``choices`` make, in the order the groups first appear."""
    groups: dict[int, list[int]] = {}
    for display, choice in enumerate(choices):
        groups.setdefault(choice, []).append(display)
    return tuple(tuple(members) for members in groups.values())


def preview_spangroups(choices: Sequence[int]) -> SpanGroups | None:
    """The span groups for the preview: none unless there are at least two."""
    groups = spangroups_of(choices)
    return groups if len(groups) >= 2 else None


def display_areas(layout: Layout, span_mode: SpanMode) -> list[DisplayArea]:
    """The displays as the preview shows them: density-normalised in advanced mode, as
    they are on the desktop otherwise."""
    match span_mode:
        case "advanced":
            return layout.ppi_norm_areas()
        case "single" | "multi":
            return layout.real_areas()
        case _:
            assert_never(span_mode)


def applied_offsets(applied: bool, fields: Sequence[str]) -> tuple[Offset, ...]:
    """The manual offsets of the displays: none (0,0) unless they are applied, when the
    fields are read; raises OffsetError if one can't be."""
    if not applied:
        return len(fields) * ((0, 0),)
    return parse_offsets(fields)


def parse_offsets(fields: Sequence[str]) -> tuple[Offset, ...]:
    """Each display's "x,y" offset in pixels from its field; an empty field is 0,0.

    Raises OffsetError naming every display whose field can't be read.
    """
    offsets = []
    problems = []
    for display, text in enumerate(fields):
        offset = _parse_offset(text)
        if offset is None:
            problems.append(f"Manual offset of display {display}: expected whole pixel numbers as x,y, not '{text}'.")
        else:
            offsets.append(offset)
    if problems:
        raise OffsetError("\n".join(problems))
    return tuple(offsets)


def _parse_offset(text: str) -> Offset | None:
    if not text.strip():
        return (0, 0)
    parts = text.split(",")
    if len(parts) != 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def applied_spangroups(form: ProfileForm) -> SpanGroups | None:
    """The span groups ``form`` chose; None unless it uses span groups."""
    return spangroups_of(form.spangroup_choices) if uses_spangroups(form.span_mode, form.spangroups_enabled) else None


def blank_form(layout: Layout) -> ProfileForm:
    """The form of a new profile for the displays of ``layout``."""
    count = len(layout.displays)
    return ProfileForm(
        name="",
        span_mode="single",
        slideshow=False,
        delay_minutes="",
        sort_label=None,
        hotkey_enabled=False,
        hotkey="",
        offsets_applied=False,
        offsets=count * ("0,0",),
        spangroups_enabled=False,
        spangroup_choices=count * (0,),
        perspective=Default(),
        zoom_pct=100,
        pan_pct=(0, 0),
        per_target_sources=False,
        sources=(),
    )


def form_from(profile: Profile, layout: Layout) -> ProfileForm:
    """The form that shows ``profile`` for the displays of ``layout``."""
    corrections = profile.display_corrections(layout.resolutions())
    # An old profile that corrects positions without saying advanced, is shown as advanced.
    legacy_advanced = profile.spanmode == "single" and bool(corrections.ppimode or profile.bezels or profile.offsets)
    span_mode: SpanMode = "advanced" if legacy_advanced else profile.spanmode
    count = len(layout.displays)
    spangroups = profile.spangroups or ()
    # A profile may give fewer offsets than there are displays; the rest are 0,0.
    padded = list(profile.offsets) + count * [(0, 0)]
    offsets = tuple(f"{x},{y}" for x, y in padded[:count]) if profile.offsets else count * ("0,0",)
    per_target = sources_per_target(span_mode, bool(spangroups))
    if per_target:
        rows = tuple((str(target), path) for target, paths in enumerate(profile.sources) for path in paths)
    else:
        rows = tuple(("", path) for paths in profile.sources for path in paths)
    return ProfileForm(
        name=profile.name,
        span_mode=span_mode,
        slideshow=profile.slideshow,
        delay_minutes=str(profile.delay / 60) if profile.slideshow else "",
        sort_label=SORT_LABELS[profile.sortmode] if profile.slideshow else None,
        hotkey_enabled=bool(profile.hotkey),
        hotkey=format_hotkey(profile.hotkey),
        offsets_applied=bool(profile.offsets),
        offsets=offsets,
        spangroups_enabled=bool(spangroups),
        spangroup_choices=tuple(
            next((number for number, members in enumerate(spangroups) if display in members), 0)
            for display in range(count)
        ),
        perspective=profile.perspective,
        zoom_pct=round(profile.zoom * 100),
        pan_pct=(round(profile.pan[0] * 100), round(profile.pan[1] * 100)),
        per_target_sources=per_target,
        sources=rows,
    )


def parse_form(form: ProfileForm) -> tuple[Profile, list[str]]:
    """The profile ``form`` describes, with what keeps fields from being read, such as a
    delay that isn't a number. Never raises on partial input, so it is safe to call on
    every field edit."""
    problems = []
    defaults = Profile(name=form.name)
    delay = defaults.delay
    sortmode = defaults.sortmode
    if form.slideshow:
        if not form.delay_minutes.strip():
            problems.append("When using slideshow you need to enter a delay.")
        else:
            minutes = parse_float(form.delay_minutes)
            if minutes is None or minutes <= 0:
                problems.append(f"The slideshow delay must be a number of minutes, not '{form.delay_minutes}'.")
            else:
                delay = 60 * minutes  # minutes here, seconds in the file
        if form.sort_label is not None:
            sortmode = _SORT_MODE_OF_LABEL[form.sort_label]
    hotkey = parse_hotkey(form.hotkey) if form.hotkey_enabled else None

    # manual offsets; an empty field means no offset
    corrections: tuple[Correction, ...] = ()
    if form.offsets_applied:
        try:
            offsets = parse_offsets(form.offsets)
        except OffsetError as error:
            problems.append(str(error))
            offsets = len(form.offsets) * ((0, 0),)
        corrections = (OffsetsCorrection(offsets),)

    # Zoom/pan only applies to a single fixed image; a slideshow always renders at defaults.
    if form.slideshow:
        zoom, pan = 1.0, (0.0, 0.0)
    else:
        zoom = form.zoom_pct / 100.0
        pan = (form.pan_pct[0] / 100.0, form.pan_pct[1] / 100.0)

    if form.per_target_sources:
        by_target: dict[int, list[str]] = {}
        for target, path in form.sources:
            by_target.setdefault(int(target), []).append(path)
        targets = len(form.spangroup_choices) if form.span_mode == "multi" else len(applied_spangroups(form) or ())
        count = max(targets, max(by_target, default=-1) + 1)
        sources = tuple(tuple(by_target.get(target, ())) for target in range(count))
    else:
        sources = (tuple(path for _, path in form.sources),)

    profile = Profile(
        name=form.name,
        spanmode=form.span_mode,
        spangroups=applied_spangroups(form),
        slideshow=form.slideshow,
        delay=delay,
        sortmode=sortmode,
        sources=sources,
        hotkey=hotkey,
        perspective=form.perspective,
        zoom=zoom,
        pan=pan,
        corrections=corrections,
    )
    return profile, problems


def fingerprint(form: ProfileForm) -> str:
    """What saving ``form`` would write, minus the selection, with its problems: forms
    with the same fingerprint are the same to the user, so comparing it finds unsaved
    changes. Fields that can't be read yet (typing in progress) count through their
    problems, which quote them."""
    profile, problems = parse_form(form)
    return profile_file.serialize(profile) + "\n".join(problems)


def chosen_images(profile: Profile, picked: str | None, loaded: StoredProfile | None) -> list[str] | None:
    """The images chosen to show, for one image spanned (single or advanced): the file
    clicked in the source list, or else what the profile open in the editor shows.

    That profile is the one loaded, by its original name, so a rename in progress keeps
    the selection. None for one image per display, which a slideshow or the first
    images of the sources provide.
    """
    if profile.spanmode == "multi":
        return None
    if picked and is_file(picked):
        return [picked]
    if loaded is not None:
        return loaded.selection.images
    return None
