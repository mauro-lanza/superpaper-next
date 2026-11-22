"""What the profile editor does with the saved profiles and the running session: save, delete,
revert and apply a profile. The rules of the form itself are in
superpaper.profiles.form; these put them to use on a ProfileStore and a Session."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from superpaper.geometry.perspective import PerspectiveChoice
from superpaper.profiles import profile_file
from superpaper.profiles.form import ProfileForm, chosen_images, parse_form
from superpaper.profiles.profile_id import NEW_PROFILE_LABEL, ProfileId, ProfileIdError
from superpaper.profiles.profile_store import ProfileStore, StoredProfile, validate_managed_profile_id
from superpaper.session import Session
from superpaper.user_input import Offset, Problems

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
        return store.get(ProfileId.parse(name, windows_names=store.windows_names))
    except ProfileIdError:
        return None


def save_profile(
    form: ProfileForm,
    *,
    picked: str | None,
    loaded: StoredProfile | None,
    store: ProfileStore,
    session: Session,
    rebind_hotkey: RebindHotkey,
) -> Saved | Problems:
    """Save the profile ``form`` describes, over ``loaded`` or as a new one, if it is valid.

    The desktop and a running slideshow's countdown stay as they are: ``picked``, the image
    clicked in the sources, becomes the selection, shown at the next change."""
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
            selected=chosen_images(profile, picked, loaded),
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


def align_test_profile(image: str, perspective: PerspectiveChoice, offsets: Sequence[Offset]) -> profile_file.Profile:
    """The one-off profile that shows ``image`` across the displays at ``offsets`` with ``perspective``."""
    return profile_file.draft([image], spanmode="advanced", perspective=perspective, offsets=offsets)


def check_applicable(stored: StoredProfile) -> Problems | None:
    """What keeps the saved profile ``stored`` from being shown, if anything."""
    problems = profile_file.validate(stored.profile)
    return Problems(tuple(problems)) if problems else None


def apply_profile(stored: StoredProfile, *, picked: str | None, session: Session) -> None:
    """Show ``picked`` (the image clicked in the sources), or else the current image of
    ``stored``, and run it."""
    session.apply(stored, chosen_images(stored.profile, picked, None))
