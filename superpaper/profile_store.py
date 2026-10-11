"""The profiles directory: the saved profiles in it, and saving, renaming and deleting
them; which profile runs, and what each one shows.

A profile's identity is its filename stem, a ProfileId. A ProfileStore holds one record
per profile, which the tray, the editor and the slideshow share.
"""

import hashlib
import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum, auto
from functools import partial
from pathlib import Path

from superpaper import profiles
from superpaper.files import write_atomically
from superpaper.paths import AppPaths
from superpaper.profile_id import ManagedPathError, ProfileId, ProfileIdError, collision_key, profile_path
from superpaper.profiles import Profile
from superpaper.selection import Selection

logger = logging.getLogger(__name__)


class ProfileDiagnosticKind(Enum):
    INVALID_FILENAME = auto()
    NOT_REGULAR_FILE = auto()
    MALFORMED_CONTENT = auto()
    IO_ERROR = auto()


@dataclass(frozen=True, slots=True)
class ProfileDiscoveryDiagnostic:
    """A file in the profiles directory that isn't a usable profile, and why."""

    path: Path
    kind: ProfileDiagnosticKind
    detail: str
    profile_id: ProfileId | None = None
    # Digest of the diagnosed bytes, so that deleting the file later can confirm it
    # removes the content the user was asked about.
    digest: bytes | None = None


@dataclass(frozen=True, eq=False, slots=True)
class StoredProfile:
    """A profile in the profiles directory, as loaded."""

    profile_id: ProfileId
    path: Path
    profile: Profile
    digest: bytes
    """Of the file as loaded, to notice edits made elsewhere before saving over it."""
    selection: Selection
    """What it shows now, remembered across restarts."""


@dataclass(frozen=True, slots=True)
class ProfileInventory:
    entries: tuple[StoredProfile, ...]
    diagnostics: tuple[ProfileDiscoveryDiagnostic, ...]

    def find(self, profile_id: ProfileId) -> StoredProfile | None:
        return next((entry for entry in self.entries if entry.profile_id == profile_id), None)


class ProfileTransactionError(OSError):
    """A managed save failed, possibly with bounded rollback failures."""

    def __init__(self, stage: str, error: OSError | ValueError, rollback_errors: tuple[OSError, ...] = ()):
        message = f"Profile save failed during {stage}: {error}"
        if rollback_errors:
            message += "; rollback also failed: " + "; ".join(map(str, rollback_errors))
        super().__init__(getattr(error, "errno", None), message)
        self.stage = stage
        self.original_error = error
        self.rollback_errors = rollback_errors

    def __str__(self) -> str:
        # The editor shows this; OSError's own would start with "[Errno None]".
        return self.strerror or ""


_DESTINATION_WRITE = "destination write"
_SOURCE_VERIFICATION = "source verification"
_SOURCE_REMOVAL = "source removal"
_ACTIVE_POINTER_UPDATE = "active pointer update"


class ProfileStore:
    """The saved profiles, one record per profile.

    Everything that uses a profile gets its record here, so all of them see what it
    shows now. Reloading keeps the record of a profile whose file hasn't changed, and so
    where its slideshow is.
    """

    def __init__(self, paths: AppPaths):
        self.paths = paths
        self._records: dict[ProfileId, StoredProfile] = {}

    @property
    def profiles(self) -> list[StoredProfile]:
        """The profiles that loaded, in filename order."""
        return list(self._records.values())

    def get(self, profile_id: ProfileId) -> StoredProfile | None:
        return self._records.get(profile_id)

    def active(self) -> StoredProfile | None:
        """The profile that was running when Superpaper last exited, if it still loads."""
        profile_id = read_active_profile_id(self.paths.cache)
        if profile_id is None:
            return None
        stored = self.get(profile_id)
        if stored is None:
            logger.info("The previously running profile '%s' no longer exists.", profile_id.value)
        return stored

    def reload(self) -> tuple[ProfileDiscoveryDiagnostic, ...]:
        """Read the profiles directory again; returns the files that couldn't be loaded."""
        inventory = discover(self.paths)
        previous = self._records
        self._records = {}
        for loaded in inventory.entries:
            kept = previous.get(loaded.profile_id)
            unchanged = kept is not None and kept.path == loaded.path and kept.digest == loaded.digest
            self._records[loaded.profile_id] = kept if kept is not None and unchanged else loaded
        return inventory.diagnostics

    def save(
        self,
        profile: Profile,
        *,
        selected: list[str] | None = None,
        current: StoredProfile | None = None,
        update_active: bool = False,
    ) -> StoredProfile:
        """Save ``profile`` as a new profile, or over ``current``, renaming it if its name
        changed; returns its record. See save_managed_profile."""
        path = save_managed_profile(
            self.paths,
            profile,
            selected=selected,
            current_profile_id=current.profile_id if current is not None else None,
            expected_source_digest=current.digest if current is not None else None,
            update_active=update_active,
        )
        self.reload()
        stored = self.get(ProfileId.parse(path.stem))
        if stored is None:
            message = f"The saved profile {path} could not be loaded again."
            raise ProfileTransactionError(_DESTINATION_WRITE, ValueError(message))
        return stored

    def delete(self, stored: StoredProfile) -> None:
        """Delete a profile and forget what it showed, unless its file changed after it was
        loaded (ManagedPathError)."""
        delete_managed_profile(self.paths, stored)
        self._records.pop(stored.profile_id, None)


def _content_digest(content: bytes) -> bytes:
    """Fingerprint a profile file's bytes, to notice edits made outside the editor."""
    return hashlib.sha256(content).digest()


def discover(paths: AppPaths) -> ProfileInventory:
    """Load every profile in the profiles directory and explain the ones that can't load.

    Symlinked profiles are followed, so profiles kept in a dotfile repository work.
    Loading lists none of a profile's sources: that happens when its images are needed.
    """
    root = paths.profiles
    try:
        leaves = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError as error:
        diagnostic = ProfileDiscoveryDiagnostic(root, ProfileDiagnosticKind.IO_ERROR, str(error))
        return ProfileInventory((), (diagnostic,))
    entries: list[StoredProfile] = []
    diagnostics: list[ProfileDiscoveryDiagnostic] = []
    for path in leaves:
        if path.suffix != ".profile":
            continue
        try:
            profile_id = ProfileId.parse(path.stem)
        except ProfileIdError as error:
            diagnostics.append(ProfileDiscoveryDiagnostic(path, ProfileDiagnosticKind.INVALID_FILENAME, str(error)))
            continue
        loaded = _load(path, profile_id, paths.cache)
        if isinstance(loaded, StoredProfile):
            entries.append(loaded)
        else:
            diagnostics.append(loaded)
    return ProfileInventory(tuple(entries), tuple(diagnostics))


def _load(path: Path, profile_id: ProfileId, cache_dir: Path) -> StoredProfile | ProfileDiscoveryDiagnostic:
    if not path.is_file():
        return ProfileDiscoveryDiagnostic(
            path, ProfileDiagnosticKind.NOT_REGULAR_FILE, "Not a regular file.", profile_id
        )
    try:
        content = path.read_bytes()
    except OSError as error:
        return ProfileDiscoveryDiagnostic(path, ProfileDiagnosticKind.IO_ERROR, str(error), profile_id)
    digest = _content_digest(content)
    try:
        profile = profiles.parse(content.decode("utf-8"))
    except (UnicodeDecodeError, profiles.ProfileFormatError) as error:
        return ProfileDiscoveryDiagnostic(path, ProfileDiagnosticKind.MALFORMED_CONTENT, str(error), profile_id, digest)
    # The filename is the identity; a name= line that disagrees (a file renamed by hand,
    # or a case-only rename on Windows) is corrected on the next save.
    if profile.name != profile_id.value:
        logger.info("%s calls itself '%s'; using its filename.", path, profile.name)
        profile = replace(profile, name=profile_id.value)
    # A remembered selection supersedes a selected= line written by an older version.
    selection_file = _selection_path(cache_dir, profile_id)
    stored = _read_stored_selection(selection_file)
    images = profile.selected if stored is None else stored
    selection = Selection(
        profile.sources,
        profile.sortmode,
        profile.selection_size,
        images=images,
        remember=partial(_store_selection, selection_file),
    )
    return StoredProfile(profile_id, path, profile, digest, selection)


def delete_malformed(diagnostic: ProfileDiscoveryDiagnostic) -> bool:
    """Delete a profile file that couldn't be loaded, if it still holds what was
    diagnosed (the user may have fixed it meanwhile). Returns whether it was deleted."""
    path = diagnostic.path
    try:
        if _content_digest(path.read_bytes()) != diagnostic.digest:
            logger.info("Keeping %s: it changed while the question was open.", path)
            return False
        path.unlink()
    except OSError as error:
        logger.info("Keeping %s: %s", path, error)
        return False
    logger.info("Removed profile: %s", path)
    return True


def stored_profile_ids(paths: AppPaths) -> list[ProfileId] | None:
    """The ids of the profile files in the profiles directory, whether or not they load;
    None if the directory can't be read."""
    try:
        stems = [path.stem for path in paths.profiles.iterdir() if path.suffix == ".profile"]
    except OSError as error:
        logger.warning("Could not list the profiles in %s: %s", paths.profiles, error)
        return None
    profile_ids = []
    for stem in stems:
        try:
            profile_ids.append(ProfileId.parse(stem))
        except ProfileIdError:
            continue
    return profile_ids


def validate_managed_profile_id(
    profiles_dir: Path, name: object, current_profile_id: ProfileId | None = None
) -> ProfileId:
    """Return the identity a profile will be saved under, refusing names that can't be used.

    Re-saving a profile under its current name always works, so profiles from older
    versions stay editable. A new name, for a new profile or a rename, must be
    portable and must not differ only in case or normalization from an existing file.
    """
    if current_profile_id is not None and name == current_profile_id.value:
        return current_profile_id
    profile_id = ProfileId.parse_new(name)
    try:
        leaves = list(profiles_dir.iterdir())
    except FileNotFoundError:
        return profile_id
    for path in leaves:
        if path.suffix == ".profile" and collision_key(path.stem) == profile_id.collision_key:
            message = f"Profile name collides with existing profile '{path.stem}'."
            raise ValueError(message)
    return profile_id


def delete_managed_profile(paths: AppPaths, stored: StoredProfile) -> None:
    """Delete a loaded profile's file, refusing if the file changed after it was loaded."""
    path = profile_path(paths.profiles, stored.profile_id, allow_missing=False)
    if _content_digest(path.read_bytes()) != stored.digest:
        message = f"'{stored.profile_id.value}' changed on disk after it was loaded. Reload it before deleting."
        raise ManagedPathError(message)
    path.unlink()
    _forget_selection(_selection_path(paths.cache, stored.profile_id))


def _active_pointer_path(cache_dir: Path) -> Path:
    return cache_dir / "running_profile"


def read_active_profile_id(cache_dir: Path) -> ProfileId | None:
    """The profile that was running when Superpaper last exited, as remembered."""
    path = _active_pointer_path(cache_dir)
    if not path.is_file():
        return None
    try:
        return ProfileId.parse(path.read_text(encoding="utf-8").splitlines()[0])
    except OSError, UnicodeError, IndexError, ProfileIdError:
        return None


def write_active_profile(cache_dir: Path, profile: ProfileId | str) -> None:
    """Remember which profile is running, for the next start."""
    profile_id = profile if isinstance(profile, ProfileId) else ProfileId.parse(profile)
    write_atomically(_active_pointer_path(cache_dir), profile_id.value.encode("utf-8"))


# The current selection is runtime state that changes on every slideshow tick, so it
# is remembered beside running_profile instead of inside the profile file. A profile
# file then changes only when the user edits it. A selected= line written by an
# older version is still honoured until a selection has been stored.
def _selection_path(cache_dir: Path, profile_id: ProfileId) -> Path:
    return cache_dir / "selections" / f"{profile_id.value}.json"


def sweep_selections(cache_dir: Path, keep: Iterable[ProfileId]) -> None:
    """Forget what profiles that no longer exist showed: profiles deleted or renamed
    outside Superpaper. Other files are left alone."""
    names = {_selection_path(cache_dir, profile_id).name for profile_id in keep}
    try:
        entries = list(os.scandir(cache_dir / "selections"))
    except FileNotFoundError:
        return
    except OSError as error:
        logger.warning("Could not look for old selections in %s: %s", cache_dir, error)
        return
    for entry in entries:
        if entry.name.endswith(".json") and entry.name not in names and entry.is_file(follow_symlinks=False):
            _forget_selection(Path(entry.path))


def _read_stored_selection(path: Path) -> list[str] | None:
    """Return the remembered selection: [] once cleared, None if none was ever stored."""
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        logger.info("Ignoring the unreadable selection in %s: %s", path, error)
        return None
    if not isinstance(stored, list) or not all(isinstance(item, str) for item in stored):
        logger.info("Ignoring the malformed selection in %s.", path)
        return None
    return stored


def _store_selection(path: Path, files: list[str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(path, json.dumps(files).encode("utf-8"))
    except OSError as error:
        logger.info("Could not remember the selection in %s: %s", path, error)


def _forget_selection(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        logger.info("Could not forget the selection in %s: %s", path, error)


def _selection_to_carry_over(selection_file: Path, source_content: bytes) -> list[str] | None:
    """Return the selection a save keeps when the editor didn't choose one."""
    stored = _read_stored_selection(selection_file)
    if stored is not None:
        return stored or None
    legacy_lines = [
        line.partition("=")[2]
        for line in source_content.decode("utf-8", errors="replace").splitlines()
        if line.startswith("selected=")
    ]
    if not legacy_lines:
        return None
    return [path for path in legacy_lines[-1].strip().split(";") if path] or None


def save_managed_profile(
    paths: AppPaths,
    profile: Profile,
    *,
    selected: list[str] | None = None,
    current_profile_id: ProfileId | None = None,
    expected_source_digest: bytes | None = None,
    update_active: bool = False,
) -> Path:
    """Create, update, or rename a managed profile and return its path.

    ``selected`` are the images the editor chose to show; without them, a saved
    profile keeps what it showed. An existing profile is only overwritten while its
    file still holds what the editor loaded (``expected_source_digest``), so edits made
    elsewhere are never lost silently. A rename writes the new file, removes the old one
    and, with ``update_active``, repoints the running profile, undoing earlier steps if
    a later one fails.
    """
    root = paths.profiles
    try:
        destination_id = validate_managed_profile_id(root, profile.name, current_profile_id)
        destination = profile_path(root, destination_id)
    except (OSError, ManagedPathError, ProfileIdError, ValueError) as error:
        raise ProfileTransactionError(_DESTINATION_WRITE, error) from error
    content = profiles.serialize(profile).encode("utf-8")
    destination_selection = _selection_path(paths.cache, destination_id)

    if current_profile_id is None:
        _write_profile(destination, content)
        if selected:
            _store_selection(destination_selection, selected)
        return destination

    source_path, source_content = _read_unchanged_source(root, current_profile_id, expected_source_digest)
    source_selection = _selection_path(paths.cache, current_profile_id)
    selection = selected or _selection_to_carry_over(source_selection, source_content)
    if destination_id == current_profile_id:
        _write_profile(source_path, content)
        if selection:
            _store_selection(destination_selection, selection)
        return source_path

    _write_profile(destination, content)
    try:
        source_path.unlink()
    except OSError as error:
        raise ProfileTransactionError(_SOURCE_REMOVAL, error, _undo_create(destination)) from error
    if update_active:
        try:
            write_active_profile(paths.cache, destination_id)
        except (OSError, ValueError) as error:
            rollback_errors = _undo_remove(source_path, source_content)
            if not rollback_errors:
                rollback_errors = _undo_create(destination)
            raise ProfileTransactionError(_ACTIVE_POINTER_UPDATE, error, rollback_errors) from error
    if selection:
        _store_selection(destination_selection, selection)
    _forget_selection(source_selection)
    return destination


def _read_unchanged_source(root: Path, profile_id: ProfileId, expected_digest: bytes | None) -> tuple[Path, bytes]:
    """Return the path and bytes of the profile being saved over, if the editor's copy is current."""
    if expected_digest is None:
        error = ManagedPathError("The profile being saved was not loaded from disk.")
        raise ProfileTransactionError(_SOURCE_VERIFICATION, error)
    try:
        path = profile_path(root, profile_id, allow_missing=False)
        content = path.read_bytes()
    except (OSError, ManagedPathError) as error:
        raise ProfileTransactionError(_SOURCE_VERIFICATION, error) from error
    if _content_digest(content) != expected_digest:
        message = (
            f"'{profile_id.value}' was changed outside the editor after it was opened. "
            "Revert to load the current version, then make your changes again."
        )
        raise ProfileTransactionError(_SOURCE_VERIFICATION, ManagedPathError(message))
    return path, content


def _write_profile(path: Path, content: bytes) -> None:
    try:
        write_atomically(path, content)
    except OSError as error:
        raise ProfileTransactionError(_DESTINATION_WRITE, error) from error


def _undo_create(path: Path) -> tuple[OSError, ...]:
    try:
        path.unlink()
    except OSError as error:
        return (error,)
    return ()


def _undo_remove(path: Path, content: bytes) -> tuple[OSError, ...]:
    try:
        write_atomically(path, content)
    except OSError as error:
        return (error,)
    return ()
