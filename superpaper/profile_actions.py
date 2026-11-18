"""What the profile editor does with the saved profiles and the running session: save, delete
and revert a profile, and show a draft of one. The rules of the form itself are in
superpaper.profiles.form; these put them to use on a ProfileStore and a Session."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from superpaper.geometry.displays import Layout
from superpaper.profiles import profile_file
from superpaper.profiles.form import Draft, ProfileForm, chosen_images, parse_form
from superpaper.profiles.profile_id import NEW_PROFILE_LABEL, ProfileId, ProfileIdError
from superpaper.profiles.profile_store import ProfileStore, StoredProfile, validate_managed_profile_id
from superpaper.session import Session
from superpaper.user_input import Problems

logger = logging.getLogger(__name__)

RebindHotkey = Callable[[StoredProfile | None, StoredProfile | None], None]


@dataclass(frozen=True, slots=True)
class Saved:
    stored: StoredProfile


def carry_on_running(store: ProfileStore, session: Session) -> None:
    """After the store loaded the profiles again, the running profile carries on with its
    current record, which may hold edits made outside the editor, or stops if its file is gone."""
    running = session.running
    if running is not None:
        session.update(running.profile_id, store.get(running.profile_id))


def saved_profile(store: ProfileStore, name: str) -> StoredProfile | None:
    """The saved profile called ``name``, if there is one."""
    try:
        return store.get(ProfileId.parse(name))
    except ProfileIdError:
        return None


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
