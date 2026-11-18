"""The profile editor's rules, without any widgets.

A ProfileForm holds what the editor's fields show: text where the user types, numbers where
they drag, choices where they pick. A UI reads its fields into one, shows one in its
fields, and calls the functions here to turn it into a Profile, to tell whether it changed,
and to save, delete, revert or apply what it describes.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from operator import itemgetter
from typing import assert_never

from superpaper.geometry.canvas import DisplayArea
from superpaper.geometry.displays import Layout
from superpaper.geometry.perspective import Default, PerspectiveChoice
from superpaper.profiles import profile_file
from superpaper.profiles.profile_file import SORT_MODES, Profile, SpanMode
from superpaper.profiles.profile_id import NEW_PROFILE_LABEL, ProfileId, ProfileIdError
from superpaper.profiles.profile_store import ProfileStore, StoredProfile, validate_managed_profile_id
from superpaper.profiles.selection import Selection, is_file
from superpaper.session import Session
from superpaper.settings import format_hotkey, parse_hotkey
from superpaper.user_input import Offset, OffsetError, parse_offsets

logger = logging.getLogger(__name__)

SORT_LABELS = ("Shuffle", "Alphabetical", "Date seeded shuffle")
"""The slideshow orders as the user picks them: SORT_MODES, spelled out."""

SpanGroups = tuple[tuple[int, ...], ...]
RebindHotkey = Callable[[StoredProfile | None, StoredProfile | None], None]


@dataclass(frozen=True, slots=True)
class ProfileForm:
    """What the editor's fields hold, as the user sees them."""

    name: str
    span_mode: SpanMode
    slideshow: bool
    delay_minutes: str
    sort_label: str | None
    """One of SORT_LABELS, or None while the dropdown has no choice."""
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


@dataclass(frozen=True, slots=True)
class Problems:
    """What keeps a form's profile from being saved, applied or deleted, for the user to fix."""

    messages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Saved:
    stored: StoredProfile


@dataclass(frozen=True, slots=True)
class Draft:
    """A form's profile, ready to be shown once without saving it."""

    profile: Profile
    images: list[str]
    chosen: list[str] | None


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


def applied_spangroups(form: ProfileForm) -> SpanGroups | None:
    """The span groups ``form`` chose; None unless it uses span groups."""
    return spangroups_of(form.spangroup_choices) if form.spangroups_enabled else None


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
    sort_label = SORT_LABELS[SORT_MODES.index(profile.sortmode)] if profile.sortmode in SORT_MODES else None
    return ProfileForm(
        name=profile.name,
        span_mode=span_mode,
        slideshow=profile.slideshow,
        delay_minutes=str(profile.delay / 60) if profile.slideshow else "",
        sort_label=sort_label if profile.slideshow else None,
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
    delay = 600.0
    sortmode = "shuffle"
    if form.slideshow:
        if not form.delay_minutes.strip():
            problems.append("When using slideshow you need to enter a delay.")
        else:
            try:
                delay = 60 * float(form.delay_minutes)  # minutes here, seconds in the file
            except ValueError:
                problems.append(f"The slideshow delay must be a number of minutes, not '{form.delay_minutes}'.")
        if form.sort_label is not None:
            sortmode = form.sort_label.lower().replace(" ", "_")
    hotkey = parse_hotkey(form.hotkey) if form.hotkey_enabled else None

    # manual offsets; an empty field means no offset
    corrections = ()
    if form.offsets_applied:
        try:
            offsets = parse_offsets(form.offsets)
        except OffsetError as error:
            problems.append(str(error))
            offsets = len(form.offsets) * ((0, 0),)
        corrections = (("offsets", offsets),)

    # Zoom/pan only applies to a single fixed image; a slideshow always renders at defaults.
    if form.slideshow:
        zoom, pan = 1.0, (0.0, 0.0)
    else:
        zoom = form.zoom_pct / 100.0
        pan = (form.pan_pct[0] / 100.0, form.pan_pct[1] / 100.0)

    if form.per_target_sources:
        by_display: dict[str, list[str]] = {}
        for target, path in sorted(form.sources, key=itemgetter(0)):
            by_display.setdefault(target, []).append(path)
        sources = tuple(tuple(paths) for paths in by_display.values())
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


def chosen_images(profile: Profile, focused_path: str | None, loaded: StoredProfile | None) -> list[str] | None:
    """The images chosen to show, for one image spanned (single or advanced): the file
    focused in the source list, or else what the profile open in the editor shows.

    That profile is the one loaded, by its original name, so a rename in progress keeps
    the selection (#158). None for one image per display, which a slideshow or the first
    images of the sources provide.
    """
    if profile.spanmode == "multi":
        return None
    if focused_path and is_file(focused_path):
        return [focused_path]
    if loaded is not None:
        return loaded.selection.images
    return None


def preview_images(store: ProfileStore, stored: StoredProfile) -> list[str]:
    """The images ``stored`` shows now, as the store's current record has them: its
    selection follows the slideshow."""
    return (store.get(stored.profile_id) or stored).selection.current()


def saved_profile(store: ProfileStore, name: str) -> StoredProfile | None:
    """The saved profile called ``name``, if there is one."""
    try:
        return store.get(ProfileId.parse(name))
    except ProfileIdError:
        return None


def carry_on_running(store: ProfileStore, session: Session) -> None:
    """After the store loaded the profiles again, the running profile carries on with its
    current record, which may hold edits made outside the editor, or stops if its file is gone."""
    running = session.running
    if running is not None:
        session.update(running.profile_id, store.get(running.profile_id))


def save_profile(
    form: ProfileForm,
    *,
    focused_path: str | None,
    loaded: StoredProfile | None,
    store: ProfileStore,
    session: Session,
    rebind_hotkey: RebindHotkey,
) -> Saved | Problems:
    """Save the profile ``form`` describes, over ``loaded`` or as a new one, if it is valid."""
    profile, problems = parse_form(form)
    logger.info("Saving profile: %s", profile)
    current_profile_id = loaded.profile_id if loaded is not None else None
    if profile.name.strip():
        try:
            validate_managed_profile_id(store.paths.profiles, profile.name, current_profile_id)
        except (OSError, ProfileIdError, ValueError) as error:
            problems.insert(0, str(error))
    problems += profile_file.validate(profile)
    if problems:
        logger.info("The profile was not saved: %s", problems)
        return Problems(tuple(problems))
    try:
        # Saving loads the profiles again: once, here.
        stored = store.save(
            profile,
            selected=chosen_images(profile, focused_path, loaded),
            current=loaded,
            update_active=session.renames_running(current_profile_id, profile.name),
        )
    except OSError as error:
        logger.warning("Could not save profile: %s", error)
        return Problems((str(error),))
    if current_profile_id is not None:
        # If it runs, it keeps running under its (possibly new) name, and edits such as the
        # slideshow delay take effect at once. Before the running profile is looked up
        # below, which would otherwise find its old name gone.
        session.update(current_profile_id, stored)
    carry_on_running(store, session)
    # Its hotkey follows it, also to a new name.
    rebind_hotkey(loaded, stored)
    return Saved(stored)


def revert_profile(name: str, *, store: ProfileStore, session: Session) -> StoredProfile | None:
    """Load the saved profile called ``name`` again from disk, with any changes made to its
    file outside the editor; None if there is no such saved profile to revert to."""
    if not name or name == NEW_PROFILE_LABEL:
        return None
    store.reload()
    carry_on_running(store, session)
    return saved_profile(store, name)


def delete_profile(
    stored: StoredProfile, *, store: ProfileStore, session: Session, rebind_hotkey: RebindHotkey
) -> Problems | None:
    """Delete the saved profile ``stored``; what went wrong, or None."""
    try:
        store.delete(stored)
    except (OSError, ValueError) as error:
        return Problems((str(error),))
    # If it was running, its slideshow stops; its hotkey is free for other uses.
    session.update(stored.profile_id, None)
    rebind_hotkey(stored, None)
    return None


def prepare_draft(form: ProfileForm, focused_path: str | None, loaded: StoredProfile | None) -> Draft | Problems:
    """What showing ``form``'s profile without saving it takes, if it is valid."""
    profile, problems = parse_form(form)
    problems += profile_file.validate(profile)
    if problems:
        logger.info("Apply: validation failed, nothing applied.")
        return Problems(tuple(problems))
    chosen = chosen_images(profile, focused_path, loaded)
    # The chosen images, or else the first ones of the edited sources.
    images = Selection(profile.sources, profile.sortmode, profile.selection_size, images=chosen).current()
    logger.info("Apply preview (unsaved): %s", profile.name)
    return Draft(profile, images, chosen)


def show_draft(
    draft: Draft,
    *,
    loaded: StoredProfile | None,
    layout: Layout,
    session: Session,
    post: Callable[[Callable[[], None]], None],
    on_shown: Callable[[str | None], None],
) -> None:
    """Render ``draft`` for ``layout``, the editor's staged one so that unsaved display
    settings are reflected; the stored profile and the running one are left untouched.

    ``on_shown(problem)`` runs through ``post`` (the UI thread) once it has been shown.
    """

    def applied(problem: str | None) -> None:
        # The applied image becomes the current selection so reopening the dialog (or a
        # later render) shows the same wallpaper instead of reverting to the previously
        # saved one (#158).
        if problem is None and draft.chosen and loaded is not None:
            loaded.selection.pin(draft.chosen)
        on_shown(problem)

    session.apply_draft(
        draft.profile, draft.images, layout=layout, on_done=lambda problem: post(lambda: applied(problem))
    )
