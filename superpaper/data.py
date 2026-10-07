"""
Data storage classes for Superpaper.

Written by Henri Hänninen.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import random
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from enum import Enum, auto
from io import StringIO
from pathlib import Path

import superpaper.sp_logging as sp_logging
import superpaper.wallpaper_processing as wpproc
from superpaper.files import write_atomically
from superpaper.message_dialog import show_message_dialog
from superpaper.paths import AppPaths
from superpaper.profile_id import ManagedPathError, ProfileId, ProfileIdError, collision_key, profile_path


class ProfileDiagnosticKind(Enum):
    INVALID_FILENAME = auto()
    NOT_REGULAR_FILE = auto()
    MALFORMED_CONTENT = auto()
    IO_ERROR = auto()


@dataclass(frozen=True, slots=True)
class ProfileDiscoveryDiagnostic:
    path: Path
    kind: ProfileDiagnosticKind
    detail: str
    profile_id: ProfileId | None = None
    # Digest of the diagnosed bytes, so that deleting the file later can confirm it
    # removes the content the user was asked about.
    digest: bytes | None = None


@dataclass(frozen=True, slots=True)
class ProfileDiscoveryEntry:
    profile_id: ProfileId
    path: Path
    profile: ProfileData


@dataclass(frozen=True, slots=True)
class ProfileInventory:
    entries: tuple[ProfileDiscoveryEntry, ...]
    diagnostics: tuple[ProfileDiscoveryDiagnostic, ...]

    def find(self, profile_id: ProfileId) -> ProfileDiscoveryEntry | None:
        return next((entry for entry in self.entries if entry.profile_id == profile_id), None)


@dataclass(frozen=True, slots=True)
class DisplayCorrections:
    """A profile's position corrections, worked out for the displays present."""

    ppimode: bool
    """Whether a single image is spanned with the advanced, PPI-corrected renderer."""
    ppi_array: Sequence[float]
    manual_offsets: list[tuple[int, int]]
    """Each display's offset in pixels, bezels included."""


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


_DESTINATION_WRITE = "destination write"
_SOURCE_VERIFICATION = "source verification"
_SOURCE_REMOVAL = "source removal"
_ACTIVE_POINTER_UPDATE = "active pointer update"


def _content_digest(content: bytes) -> bytes:
    """Fingerprint a profile file's bytes, to notice edits made outside the editor."""
    return hashlib.sha256(content).digest()


def discover_profile_inventory(paths: AppPaths) -> ProfileInventory:
    """Load every profile in the profiles directory and explain the ones that can't load.

    A profile's identity is its filename stem. Symlinked profiles are followed, so
    profiles kept in a dotfile repository work.
    """
    root = paths.profiles
    try:
        leaves = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError as error:
        diagnostic = ProfileDiscoveryDiagnostic(root, ProfileDiagnosticKind.IO_ERROR, str(error))
        return ProfileInventory((), (diagnostic,))
    entries: list[ProfileDiscoveryEntry] = []
    diagnostics: list[ProfileDiscoveryDiagnostic] = []
    for path in leaves:
        if path.suffix != ".profile":
            continue
        try:
            profile_id = ProfileId.parse(path.stem)
        except ProfileIdError as error:
            diagnostics.append(ProfileDiscoveryDiagnostic(path, ProfileDiagnosticKind.INVALID_FILENAME, str(error)))
            continue
        loaded = _load_managed_profile(path, profile_id, paths.cache)
        if isinstance(loaded, ProfileDiscoveryEntry):
            entries.append(loaded)
        else:
            diagnostics.append(loaded)
    return ProfileInventory(tuple(entries), tuple(diagnostics))


def _load_managed_profile(
    path: Path, profile_id: ProfileId, cache_dir: Path
) -> ProfileDiscoveryEntry | ProfileDiscoveryDiagnostic:
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
        text = content.decode("utf-8")
        _validate_profile_syntax(text)
        profile = ProfileData(
            os.fspath(path),
            profile_id,
            profile_text=text,
            source_digest=digest,
            selection_file=_selection_path(cache_dir, profile_id),
        )
    except Exception as error:  # a hand-edited file can fail to parse in many ways
        return ProfileDiscoveryDiagnostic(path, ProfileDiagnosticKind.MALFORMED_CONTENT, str(error), profile_id, digest)
    return ProfileDiscoveryEntry(profile_id, path, profile)


def _validate_profile_syntax(text: str) -> None:
    """Check conversions that can make the legacy parser fail."""
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if key in {
            "name",
            "spanmode",
            "spangroups",
            "slideshow",
            "sortmode",
            "offsets",
            "hotkey",
            "perspective",
            "selected",
            "zoom",
            "align",
        } or key.startswith("display"):
            if not separator:
                message = f"Missing '=' after profile setting '{key}'."
                raise ValueError(message)
            if key == "zoom":
                float(value.strip())
            elif key == "align":
                parts = value.strip().split(",")
                if len(parts) != 2:
                    message = "Profile setting 'align' requires two values."
                    raise ValueError(message)
                float(parts[0])
                float(parts[1])
        elif key in {"delay", "bezels", "diagonal_inches"}:
            if not separator:
                message = f"Missing '=' after profile setting '{key}'."
                raise ValueError(message)
            for item in value.strip().split(";"):
                float(item)
        elif key == "ppi":
            if not separator:
                message = "Missing '=' after profile setting 'ppi'."
                raise ValueError(message)
            for item in value.strip().split(";"):
                int(item)


# Profile and data handling, back-end interface.
def list_profiles(paths: AppPaths) -> list[ProfileData]:
    """Return every usable profile, offering to delete the ones that fail to parse."""
    inventory = discover_profile_inventory(paths)
    for diagnostic in inventory.diagnostics:
        if diagnostic.kind is ProfileDiagnosticKind.MALFORMED_CONTENT:
            _prompt_to_delete_malformed_profile(diagnostic)
        else:
            sp_logging.G_LOGGER.warning("Ignoring %s: %s", diagnostic.path, diagnostic.detail)
    return [entry.profile for entry in inventory.entries]


def _prompt_to_delete_malformed_profile(diagnostic: ProfileDiscoveryDiagnostic) -> None:
    path = diagnostic.path
    msg = (
        f"There was an error when loading profile '{path.name}'.\n"
        "Would you like to delete it? Choosing 'No' will just ignore the profile."
    )
    sp_logging.G_LOGGER.info(msg)
    sp_logging.G_LOGGER.info(diagnostic.detail)
    if not show_message_dialog(msg, "Error", style="YES_NO"):
        return
    try:
        if _content_digest(path.read_bytes()) != diagnostic.digest:
            sp_logging.G_LOGGER.info("Keeping %s: it changed while the question was open.", path)
            return
        path.unlink()
    except OSError as error:
        sp_logging.G_LOGGER.info("Keeping %s: %s", path, error)
        return
    sp_logging.G_LOGGER.info("Removed profile: %s", path)


def open_profile(paths: AppPaths, profile: ProfileId | str) -> ProfileData | None:
    """Load one managed profile by name; None if it doesn't exist or can't be used."""
    try:
        profile_id = profile if isinstance(profile, ProfileId) else ProfileId.parse(profile)
    except ProfileIdError:
        return None
    loaded = _load_managed_profile(paths.profiles / profile_id.profile_filename, profile_id, paths.cache)
    return loaded.profile if isinstance(loaded, ProfileDiscoveryEntry) else None


def parse_profile_file(path: str | os.PathLike[str]):
    """Explicitly parse an arbitrary profile file, such as a GUI preview."""
    return ProfileData(path, persist_selection=False)


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


def delete_managed_profile(paths: AppPaths, profile: ProfileData) -> None:
    """Delete a loaded profile's file, refusing if the file changed after it was loaded."""
    if profile.profile_id is None or profile.source_digest is None:
        message = "Only a loaded managed profile can be deleted."
        raise ManagedPathError(message)
    path = profile_path(paths.profiles, profile.profile_id, allow_missing=False)
    if _content_digest(path.read_bytes()) != profile.source_digest:
        message = f"'{profile.profile_id.value}' changed on disk after it was loaded. Reload it before deleting."
        raise ManagedPathError(message)
    path.unlink()
    _forget_selection(_selection_path(paths.cache, profile.profile_id))


def managed_profile_for_selection(profiles: list[ProfileData], profile_id: ProfileId) -> ProfileData | None:
    """Resolve a GUI selection by managed identity, independent of editable fields."""
    return next((profile for profile in profiles if profile.profile_id == profile_id), None)


def _active_pointer_path(cache_dir: Path) -> Path:
    return cache_dir / "running_profile"


def read_active_profile(paths: AppPaths) -> ProfileData | None:
    """Return the profile that was running when Superpaper last exited, if it still exists."""
    path = _active_pointer_path(paths.cache)
    if not path.is_file():
        return None
    try:
        profname = path.read_text(encoding="utf-8").splitlines()[0]
        profile_id = ProfileId.parse(profname)
    except OSError, UnicodeError, IndexError, ProfileIdError:
        return None
    profile = open_profile(paths, profile_id)
    if profile is None:
        sp_logging.G_LOGGER.info("The previously running profile '%s' no longer exists.", profname)
    return profile


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


def _read_stored_selection(path: Path) -> list[str] | None:
    """Return the remembered selection: [] once cleared, None if none was ever stored."""
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        sp_logging.G_LOGGER.info("Ignoring the unreadable selection in %s: %s", path, error)
        return None
    if not isinstance(stored, list) or not all(isinstance(item, str) for item in stored):
        sp_logging.G_LOGGER.info("Ignoring the malformed selection in %s.", path)
        return None
    return stored


def _store_selection(path: Path, files: list[str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomically(path, json.dumps(files).encode("utf-8"))
    except OSError as error:
        sp_logging.G_LOGGER.info("Could not remember the selection in %s: %s", path, error)


def _forget_selection(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        sp_logging.G_LOGGER.info("Could not forget the selection in %s: %s", path, error)


def _parse_selected(value: str) -> list[str] | None:
    """Parse the value of a selected= line: image paths separated by ';'."""
    return [path for path in value.strip().split(";") if path] or None


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
    return _parse_selected(legacy_lines[-1]) if legacy_lines else None


def save_managed_profile(
    paths: AppPaths,
    profile: TempProfileData,
    *,
    current_profile_id: ProfileId | None = None,
    expected_source_digest: bytes | None = None,
    update_active: bool = False,
) -> Path:
    """Create, update, or rename a managed profile and return its path.

    An existing profile is only overwritten while its file still holds what the
    editor loaded (``expected_source_digest``), so edits made elsewhere are never
    lost silently. A rename writes the new file, removes the old one and, with
    ``update_active``, repoints the running profile, undoing earlier steps if a later
    one fails.
    """
    root = paths.profiles
    try:
        destination_id = validate_managed_profile_id(root, profile.name, current_profile_id)
        destination = profile_path(root, destination_id)
    except (OSError, ManagedPathError, ProfileIdError, ValueError) as error:
        raise ProfileTransactionError(_DESTINATION_WRITE, error) from error
    content = profile.serialize(include_selection=False).encode("utf-8")
    destination_selection = _selection_path(paths.cache, destination_id)

    if current_profile_id is None:
        _write_profile(destination, content)
        if profile.selected:
            _store_selection(destination_selection, profile.selected)
        return destination

    source_path, source_content = _read_unchanged_source(root, current_profile_id, expected_source_digest)
    source_selection = _selection_path(paths.cache, current_profile_id)
    selection = profile.selected or _selection_to_carry_over(source_selection, source_content)
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


class ProfileDataException(Exception):
    """ProfileData initialization error handler."""

    def __init__(self, message, profile_name, parse_file, errors):
        super().__init__(message)
        sp_logging.G_LOGGER.info("%s %s %s", message, profile_name, parse_file)
        sp_logging.G_LOGGER.info(errors)


def _parse_diagonals(value: str) -> list[float]:
    """The display diagonals of a diagonal_inches= line, in inches.

    Densities are pixels per inch of diagonal, so a diagonal of 0 makes the profile
    unusable; earlier versions failed to load such a profile as well.
    """
    inches = [float(inchstr) for inchstr in value.strip().split(";")]
    if 0 in inches:
        message = "A display diagonal of 0 inches."
        raise ValueError(message)
    return inches


def _shift_by_bezels(offsets, ppi_array, bezels, count):
    """Move each display right by the bezels (in mm) between it and the leftmost one."""
    if not ppi_array:
        sp_logging.G_LOGGER.error("Couldn't compute bezel offsets without pixel densities.")
        return offsets
    max_ppi = max(ppi_array)
    inch_per_mm = 1.0 / 25.4
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


class ProfileData:
    """
    Central data type of Superpaper, in which wallpaper settings are recorded.

    A cornerstone goal of Superpaper is to allow the user to save wallpaper
    presets that are easy to change between. These settings include the
    images to use, slideshow timer, spanning mode etc. Profiles are saved to
    .profile files and parsed when creating a profile data object.
    """

    def __init__(
        self,
        profile_file,
        profile_id: ProfileId | None = None,
        *,
        profile_text: str | None = None,
        source_digest: bytes | None = None,
        persist_selection: bool = True,
        selection_file: Path | None = None,
    ):
        self.file = profile_file
        self.name = "default_profile"
        self.spanmode = "single"  # single / advanced / multi
        self.spangroups = None
        self.slideshow = True
        self.delay_list: list[float] = [600]
        self.sortmode = "shuffle"  # shuffle / alphabetical / date_seeded_shuffle
        self.inches = []
        self.manual_offsets_useronly = []
        self.bezels = []
        # The offsets=, ppi= and diagonal_inches= lines, in file order. What they mean
        # depends on the displays present, so display_corrections works it out per layout.
        self._corrections: list[tuple[str, list]] = []
        self.hk_binding = None
        self.perspective = "default"
        self.zoom = 1.0
        self.offsets = (0.0, 0.0)
        self.paths_array = []
        self.selected = None

        self.parse_profile(StringIO(profile_text) if profile_text is not None else self.file)
        # The filename is the identity; a name= line that disagrees (a file renamed
        # by hand, or a case-only rename on Windows) is corrected on the next save.
        if profile_id is not None and self.name != profile_id.value:
            sp_logging.G_LOGGER.info("%s calls itself '%s'; using its filename.", self.file, self.name)
            self.name = profile_id.value
        # A saved profile remembers its selection in selection_file; a stored one
        # supersedes a selected= line written by an older version.
        self.selection_file = selection_file
        if selection_file is not None:
            stored_selection = _read_stored_selection(selection_file)
            if stored_selection is not None:
                self.selected = stored_selection or None
        self.profile_id: ProfileId | None = profile_id
        self.source_digest = source_digest
        self.persist_selection = persist_selection
        self.file_handler = self.Filehandler(self.paths_array, self.sortmode)

    def parse_profile(self, parse_file):
        """Read wallpaper profile settings from file."""
        try:
            with ExitStack() as stack:
                profile_file = (
                    parse_file
                    if hasattr(parse_file, "read")
                    else stack.enter_context(open(parse_file, encoding="utf-8"))
                )
                for line in profile_file:
                    # Only the first "=" separates key from value: paths may contain "=".
                    words = line.split("=", 1)
                    if words[0] == "name":
                        self.name = words[1].strip()
                    elif words[0] == "spanmode":
                        wrd1 = words[1].strip().lower()
                        if wrd1 == "single" or wrd1 == "advanced" or wrd1 == "multi":
                            self.spanmode = wrd1
                        else:
                            sp_logging.G_LOGGER.info(
                                "Exception: unknown spanmode: %s \
                                    in profile: %s",
                                words[1],
                                self.name,
                            )
                    elif words[0] == "spangroups":
                        spangroups = []
                        groups = words[1].strip().split(",")
                        for grp in groups:
                            try:
                                ids = [int(idx) for idx in grp]
                                spangroups.append(sorted(set(ids)))  # drop duplicates
                            except ValueError:
                                spangroups = None
                                break
                        self.spangroups = spangroups
                    elif words[0] == "slideshow":
                        wrd1 = words[1].strip().lower()
                        if wrd1 == "true":
                            self.slideshow = True
                        else:
                            self.slideshow = False
                    elif words[0] == "delay":
                        self.delay_list = []
                        delay_strings = words[1].strip().split(";")
                        for delstr in delay_strings:
                            self.delay_list.append(float(delstr))
                    elif words[0] == "sortmode":
                        wrd1 = words[1].strip().lower()
                        if wrd1 == "shuffle" or wrd1 == "date_seeded_shuffle" or wrd1 == "alphabetical":
                            self.sortmode = wrd1
                        else:
                            sp_logging.G_LOGGER.info(
                                "Exception: unknown sortmode: %s \
                                    in profile: %s",
                                words[1],
                                self.name,
                            )
                    elif words[0] == "offsets":
                        # w1,h1;w2,h2;... in pixels, from the leftmost display.
                        offsets = []
                        for offstr in words[1].strip().split(";"):
                            res_str = offstr.split(",")
                            try:
                                offsets.append((int(res_str[0]), int(res_str[1])))
                            except ValueError, IndexError:
                                offsets.append((0, 0))
                        self.manual_offsets_useronly = offsets
                        self._corrections.append(("offsets", offsets))
                    elif words[0] == "bezels":
                        bez_mm_strings = words[1].strip().split(";")
                        for bezstr in bez_mm_strings:
                            self.bezels.append(float(bezstr))
                    elif words[0] == "ppi":
                        ppis = [int(ppistr) for ppistr in words[1].strip().split(";")]
                        self._corrections.append(("ppi", ppis))
                    elif words[0] == "diagonal_inches":
                        self.inches = _parse_diagonals(words[1])
                        self._corrections.append(("diagonal_inches", self.inches))
                    elif words[0] == "hotkey":
                        binding_strings = words[1].strip().split("+")
                        self.hk_binding = tuple(binding_strings)
                        # if sp_logging.DEBUG:
                        #     sp_logging.G_LOGGER.info("hkBinding: %s", self.hk_binding)
                    elif words[0] == "perspective":
                        self.perspective = words[1].strip()
                        # if sp_logging.DEBUG:
                        #     sp_logging.G_LOGGER.info("perspective preset: %s", self.perspective)
                    elif words[0] == "zoom":
                        try:
                            self.zoom = max(1.0, float(words[1].strip()))
                        except ValueError:
                            self.zoom = 1.0
                    elif words[0] == "align":
                        try:
                            parts = words[1].strip().split(",")
                            off_x = min(1.0, max(-1.0, float(parts[0])))
                            off_y = min(1.0, max(-1.0, float(parts[1])))
                            self.offsets = (off_x, off_y)
                        except ValueError, IndexError:
                            self.offsets = (0.0, 0.0)
                    elif words[0] == "selected":
                        self.selected = _parse_selected(words[1])
                    elif words[0].startswith("display"):
                        paths = words[1].strip().split(";")
                        paths = list(filter(None, paths))  # drop empty strings
                        self.paths_array.append(paths)
                    else:
                        sp_logging.G_LOGGER.info("Unknown setting line in config: %s", line)
        except Exception as excep:
            msg = "There was an error parsing the profile:"
            raise ProfileDataException(msg, self.name, self.file, excep) from excep

    def display_corrections(self, resolutions) -> DisplayCorrections:
        """Work out this profile's position corrections for displays of ``resolutions``.

        Profiles from before display layouts existed correct positions with offsets=,
        ppi=, diagonal_inches= and bezels=. They apply in file order, as when earlier
        versions parsed the profile for the displays present then; the parsed profile
        no longer depends on which displays those are.
        """
        count = len(resolutions)
        ppimode = False
        ppi_array = count * [100]
        offsets = count * [(0, 0)]
        for key, values in self._corrections:
            if key == "offsets":
                ppimode = True
                offsets = values + (count - len(values)) * [(0, 0)]
            elif key == "ppi":
                ppimode = True
                ppi_array = list(values)
            elif len(values) < count:
                sp_logging.G_LOGGER.info(
                    "%s display diagonals for %s displays: falling back to no PPI correction.", len(values), count
                )
                ppimode = False
                ppi_array = count * [100]
            else:
                ppimode = True
                ppi_array = [math.sqrt(res[0] ** 2 + res[1] ** 2) / inch for inch, res in zip(values, resolutions)]
        if ppimode and self.bezels:
            offsets = _shift_by_bezels(offsets, ppi_array, self.bezels, count)
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("Corrections of '%s': PPIs %s, offsets %s", self.name, ppi_array, offsets)
        return DisplayCorrections(ppimode, ppi_array, offsets)

    def next_wallpaper_files(self, peek=False):
        """Return the current wallpaper file(s).

        A persistent selection is the source of truth for what is shown. Only
        an explicit cycle (advance_wallpaper) moves to the next image, so the
        wallpaper never changes merely because the profile is rendered again.
        A peek changes nothing: a selection whose files are missing right now (an
        unmounted drive, say) is kept for when they return.
        """
        if self.has_valid_selection():
            return list(self.selected or [])
        if self.selected and not peek:
            self.selected = None
            self._write_selected()
        return self.file_handler.next_wallpaper_files(peek=peek)

    def selection_target_count(self):
        """Return how many positional image choices this profile requires: one per
        configured display for a multi-image profile, one per span group, or one."""
        if self.spanmode == "multi":
            return len(self.paths_array)
        if self.spanmode == "advanced" and self.spangroups:
            return len(self.spangroups)
        return 1

    def has_valid_selection(self):
        """Check that the complete positional selection can still be rendered."""
        return bool(
            self.selected
            and len(self.selected) == self.selection_target_count()
            and all(os.path.isfile(path) and wpproc.is_supported_image(path) for path in self.selected)
        )

    def advance_wallpaper(self):
        """Cycle to the next image(s) and make the result the current selection."""
        files = self.file_handler.next_wallpaper_files()
        if files and len(files) == self.selection_target_count():
            self.selected = files
            self._write_selected()
            return list(files)
        return []

    def set_selected_wallpaper(self, files, persist=True):
        """Pin the given file(s) as the current selection.

        The selection is the source of truth for what is rendered; pinning it
        keeps the preview and the applied wallpaper in sync across reloads.
        When ``persist`` is True the choice is remembered across restarts.
        """
        self.selected = list(files) if files else None
        if persist:
            self._write_selected()

    def _write_selected(self):
        """Remember the current selection across restarts.

        A saved profile's selection goes to its selection_file, so the profile file
        itself is left alone; a file opened by path keeps it in its own selected= line.
        """
        if not self.persist_selection:
            return
        if self.selection_file is None:
            self._write_selected_unmanaged()
            return
        _store_selection(self.selection_file, list(self.selected or []))

    def _write_selected_unmanaged(self):
        """Retain explicit arbitrary-file parser behavior outside managed storage."""
        if not self.file:
            return
        try:
            with open(self.file, encoding="utf-8") as profile_file:
                lines = [line for line in profile_file if not line.startswith("selected=")]
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            if self.selected:
                lines.append("selected=" + ";".join(self.selected) + "\n")
            with open(self.file, "w", encoding="utf-8") as profile_file:
                profile_file.writelines(lines)
        except OSError as error:
            sp_logging.G_LOGGER.info("Failed to persist wallpaper selection: %s", error)

    class Filehandler:
        """
        Handles picking wallpapers from the assigned paths.

        Since multiple paths are supported per monitor, this class
        lists all valid images on a monitor by monitor basis and then
        orders the list according to sortmode. Allows for shuffling of the
        wallpapers, i.e. non-repeating randomized list, which is re-randomized
        once it has been exhausted.
        """

        def __init__(self, paths_array, sortmode):
            # A list of lists if there is more than one monitor with distinct
            # input paths.
            self.all_files_in_paths = []
            self.paths_array = paths_array
            self.sortmode = sortmode
            self._pending_batch = None
            for paths_list in paths_array:
                list_of_images = []
                for path in paths_list:
                    # Add list items to the end of the list instead of
                    # appending the list to the list.
                    if not os.path.exists(path):
                        message = f"A path was not found: '{path}'.\n\
Use absolute paths for best reliabilty."
                        sp_logging.G_LOGGER.info(message)
                        show_message_dialog(message, "Error")
                        continue
                    else:
                        # List only images that are of supported type.
                        if os.path.isfile(path):
                            if wpproc.is_supported_image(path):
                                list_of_images += [path]
                        else:
                            list_of_images += [
                                os.path.join(path, f) for f in os.listdir(path) if wpproc.is_supported_image(f)
                            ]
                # The same file can be included through overlapping directories,
                # explicit paths, or symlinks. Keep its first occurrence only.
                unique_images = []
                seen_images = set()
                for image in list_of_images:
                    identity = self._file_identity(image)
                    if identity not in seen_images:
                        seen_images.add(identity)
                        unique_images.append(image)
                self.all_files_in_paths.append(unique_images)
            self.iterators = []
            for diplay_image_list in self.all_files_in_paths:
                self.iterators.append(self.ImageList(diplay_image_list, self.sortmode))

        def next_wallpaper_files(self, peek=False, _attempt=0):
            """Return a complete batch, avoiding cross-monitor duplicates when possible."""
            # Guard against unbounded recursion: a persistently invalid entry
            # (e.g. a dangling symlink that keeps being re-listed on reinit)
            # would otherwise loop forever. After this many reinit attempts,
            # give up without returning a partial positional batch (issue #135).
            max_attempts = 20
            # Reject an incomplete positional batch before consuming any of
            # the other iterators.
            if any(not iterable.files for iterable in self.iterators):
                return []
            if self._pending_batch is None:
                self._pending_batch = self._plan_batch()
            files, counters = self._pending_batch
            if not all(os.path.isfile(path) for path in files):
                if sp_logging.DEBUG:
                    sp_logging.G_LOGGER.info("Ran into an invalid file, reinitializing..")
                if _attempt >= max_attempts:
                    sp_logging.G_LOGGER.info(
                        "next_wallpaper_files: giving up after %d attempts due to persistently invalid files",
                        max_attempts,
                    )
                    self._pending_batch = None
                    return []
                self.__init__(self.paths_array, self.sortmode)
                return self.next_wallpaper_files(peek=peek, _attempt=_attempt + 1)
            if peek:
                return list(files)
            for iterable, counter in zip(self.iterators, counters):
                iterable.counter = counter
            self._pending_batch = None
            return list(files)

        @staticmethod
        def _file_identity(path):
            return os.path.normcase(os.path.realpath(path))

        def _plan_batch(self):
            """Choose a maximum-distinct ordered assignment for all positions."""
            candidates = []
            for iterable in self.iterators:
                iterable.prepare_cycle()
                ordered_indices = list(range(iterable.counter, len(iterable.files))) + list(range(iterable.counter))
                candidates.append(
                    [
                        (iterable.files[index], index + 1, self._file_identity(iterable.files[index]))
                        for index in ordered_indices
                    ]
                )

            image_to_position = {}
            selected = [None] * len(candidates)

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

            # Reverse order preserves the earliest position's first choice when
            # several maximum matchings are otherwise equivalent.
            for position in reversed(range(len(candidates))):
                assign(position, set())

            # If uniqueness is impossible, duplicates are preferable to an
            # incomplete positional batch that could shift monitor assignments.
            for position, choices in enumerate(candidates):
                if selected[position] is None:
                    path, counter, _identity = choices[0]
                    selected[position] = (path, counter)

            completed = [choice for choice in selected if choice is not None]
            return ([choice[0] for choice in completed], [choice[1] for choice in completed])

        class ImageList:
            """Image list iterable that can reinitialize itself once it has been gone through."""

            def __init__(self, filelist, sortmode):
                self.counter = 0
                self.files = filelist
                self.sortmode = sortmode
                self.arrange_list()

            def __iter__(self):
                return self

            def _current_image(self):
                """Return the file at the current position, reshuffling when exhausted."""
                if not self.files:
                    return None
                if self.counter >= len(self.files):
                    self.counter = 0
                    self.arrange_list()
                return self.files[self.counter]

            def prepare_cycle(self):
                """Arrange the next cycle once before coordinated batch planning."""
                if self.counter >= len(self.files):
                    self.counter = 0
                    self.arrange_list()

            def __next__(self):
                image = self._current_image()
                if image is not None:
                    self.counter += 1
                return image

            def __peek__(self):
                return self._current_image()

            def arrange_list(self):
                """Reorders the image list as requested. Mostly for reoccuring shuffling."""
                if self.sortmode == "shuffle":
                    random.shuffle(self.files)
                elif self.sortmode == "date_seeded_shuffle":
                    today = datetime.datetime.now()  # noqa: DTZ005  # intentional local-time seed
                    random.Random(today.strftime("%Y%m%d%H")).shuffle(self.files)
                elif self.sortmode == "alphabetical":
                    self.files.sort()
                else:
                    sp_logging.G_LOGGER.info("ImageList.arrange_list: unknown sortmode: %s", self.sortmode)


class CLIProfileData(ProfileData):
    """
    Stripped down version of the ProfileData object for CLI usage.

    Notable differences are that this can be initialized with input data
    and this redefines the next_wallpaper_files function to just return
    the images given as input.
    """

    def __init__(self, files, advanced=False, perspective=None, spangroups=None, offsets=None):
        self.name = "cli"
        self.files = []
        self.spanmode = ""  # single / multi
        self.spangroups = spangroups
        self.perspective = perspective
        self.zoom = 1.0
        self.offsets = (0.0, 0.0)
        # --offsets x1 y1 x2 y2 ...: pixel offsets of the displays, from the leftmost.
        pairs = zip(*[iter(offsets or [])] * 2)
        self.offset_pairs = [(int(x), int(y)) for x, y in pairs]

        if len(files) == 1 and not advanced:
            self.spanmode = "single"
        elif advanced:
            self.spanmode = "advanced"
        else:
            self.spanmode = "multi"

        for item in files:
            self.files.append(os.path.realpath(item))
        # CLI/preview profiles use a fixed image set; treat it as the selection
        # so the renderer never tries to cycle.
        self.selected = self.files

    def display_corrections(self, resolutions) -> DisplayCorrections:
        """Offsets given on the command line apply to the displays present; nothing else is corrected."""
        count = len(resolutions)
        return DisplayCorrections(False, count * [100], (self.offset_pairs + count * [(0, 0)])[:count])

    def selection_target_count(self):
        """One image per display for multiple images; one per group, or one, otherwise."""
        if self.spanmode == "multi":
            return len(self.files)
        return super().selection_target_count()

    def next_wallpaper_files(self, peek=False):
        """Returns a list of the real paths of the images given at construction time."""
        return self.files

    def advance_wallpaper(self):
        """CLI/preview profiles have a fixed image set; cycling is a no-op."""
        return self.files


class TempProfileData:
    """Data object to test the validity of user input and for saving said input into profiles."""

    def __init__(self):
        self.name: str | None = None
        self.spanmode: str | None = None
        self.spangroups: str | None = None
        self.slideshow: bool | None = None
        self.delay: str | None = None
        self.sortmode: str | None = None
        self.inches = None
        self.manual_offsets: str | None = None
        self.bezels = None
        self.hk_binding: str | None = None
        self.perspective: str | None = None
        self.zoom: float | None = None
        self.align: tuple | None = None
        self.selected: list | None = None
        self.paths_array = []

    def save(self, filename):
        """Write this profile to ``filename``: a file outside the profiles directory, such
        as the throwaway copy that previews unsaved edits. Saved profiles go through
        save_managed_profile.
        """
        if self.name is None:
            sp_logging.G_LOGGER.info("tmp.Save(): name is not set.")
            return None
        try:
            with open(filename, "w", encoding="utf-8") as tpfile:
                tpfile.write(self.serialize())
        except OSError:
            msg = f"Cannot write to file {filename}"
            show_message_dialog(msg, "Error")
            return None
        return filename

    def serialize(self, *, include_selection=True):
        """Return the ``.profile`` file contents for this profile as a string.

        This is the single source of truth for the on-disk profile format, and the
        GUI compares this representation to decide whether there are unsaved
        changes. Saved profiles leave the selection out: it is stored separately.
        """
        lines = ["name=" + str(self.name)]
        if self.spanmode:
            lines.append("spanmode=" + str(self.spanmode))
        if self.spangroups:
            lines.append("spangroups=" + str(self.spangroups))
        if self.slideshow is not None:
            lines.append("slideshow=" + str(self.slideshow))
        if self.delay:
            lines.append("delay=" + str(self.delay))
        if self.sortmode:
            lines.append("sortmode=" + str(self.sortmode))
        if self.inches:
            lines.append("diagonal_inches=" + str(self.inches))
        if self.manual_offsets:
            lines.append("offsets=" + str(self.manual_offsets))
        if self.bezels:
            lines.append("bezels=" + str(self.bezels))
        if self.hk_binding:
            lines.append("hotkey=" + str(self.hk_binding))
        if self.perspective:
            lines.append("perspective=" + str(self.perspective))
        if self.zoom is not None and self.zoom != 1.0:
            lines.append("zoom=" + str(self.zoom))
        if self.align is not None and tuple(self.align) != (0.0, 0.0):
            lines.append(f"align={self.align[0]},{self.align[1]}")
        if self.selected and include_selection:
            lines.append("selected=" + ";".join(self.selected))
        lines.extend(f"display{index}paths={paths}" for index, paths in enumerate(self.paths_array))
        return "\n".join(lines) + "\n"

    def test_save(self, *, profiles_dir: Path | None = None, current_profile_id: ProfileId | None = None):
        """Tests whether the user input for profile settings is valid.

        With ``profiles_dir``, the name must also be usable for a profile saved there.
        """
        valid_profile = False
        if self.name is not None and self.name.strip() != "":
            if profiles_dir is not None:
                try:
                    validate_managed_profile_id(profiles_dir, self.name, current_profile_id)
                except (OSError, ProfileIdError, ValueError) as error:
                    show_message_dialog(str(error), "Error")
                    return False
            if self.spanmode == "single" and len(self.paths_array) > 1:
                msg = "When spanning a single image across all monitors, \
only one paths field is needed."
                show_message_dialog(msg, "Error")
                return False
            if self.spanmode == "multi" and len(self.paths_array) < 2:
                msg = "When setting a different image on every display, \
each display needs its own paths field."
                show_message_dialog(msg, "Error")
                return False
            if self.spangroups:
                list_grps = self.spangroups.split(",")
                for grp in list_grps:
                    for idx in grp:
                        try:
                            val = int(idx)
                        except ValueError:
                            return False
            if self.slideshow is True and not self.delay:
                msg = "When using slideshow you need to enter a delay."
                show_message_dialog(msg, "Info")
                return False
            if self.delay:
                try:
                    val = float(self.delay)
                    if val < 20:
                        msg = "It is advisable to set the slideshow delay to \
be at least 20 seconds due to the time the image processing takes."
                        show_message_dialog(msg, "Info")
                        return False
                except ValueError:
                    msg = "Slideshow delay must be an integer of seconds."
                    show_message_dialog(msg, "Error")
                    return False
            # if self.sortmode:
            # No test needed
            if self.inches:
                if self.is_list_float(self.inches):
                    pass
                else:
                    msg = "Display diagonals must be given in numeric values \
using decimal point and separated by semicolon ';'."
                    show_message_dialog(msg, "Error")
                    return False
            if self.manual_offsets:
                if self.is_list_offsets(self.manual_offsets):
                    pass
                else:
                    msg = "Display offsets must be given in (width,height) pixel \
pairs."
                    show_message_dialog(msg, "Error")
                    return False
            if self.bezels:
                if self.is_list_float(self.bezels):
                    if self.manual_offsets:
                        if len(self.manual_offsets.split(";")) < len(self.bezels.split(";")):
                            msg = "When using both offset and bezel \
corrections, take care to enter an offset for each display that you \
enter a bezel thickness."
                            show_message_dialog(msg, "Error")
                            return False
                        else:
                            pass
                    else:
                        pass
                else:
                    msg = "Display bezels must be given in millimeters using \
decimal point and separated by semicolon ';'."
                    show_message_dialog(msg, "Error")
                    return False
            if self.hk_binding:
                if self.is_valid_hotkey(self.hk_binding):
                    pass
                else:
                    msg = "Hotkey must be given as 'mod1+mod2+mod3+key'. \
Valid modifiers are 'control', 'super', 'alt', 'shift'."
                    show_message_dialog(msg, "Error")
                    return False
            if self.paths_array:
                if self.is_list_valid_paths(self.paths_array):
                    pass
                else:
                    # msg = "Paths must be separated by a semicolon ';'."
                    # show_message_dialog(msg, "Error")
                    return False
            else:
                msg = "You must enter at least one path for images."
                show_message_dialog(msg, "Error")
                return False
            # Passed all tests.
            valid_profile = True
            return valid_profile
        else:
            sp_logging.G_LOGGER.info("tmp.Save(): name is not set.")
            msg = "You must enter a name for the profile."
            show_message_dialog(msg, "Error")
            return False

    def is_list_float(self, input_string):
        """Tests if input string is a colon separated list of floats."""
        is_floats = True
        list_input = input_string.split(";")
        for item in list_input:
            try:
                float(item)
            except ValueError:
                sp_logging.G_LOGGER.info("float type check failed for: '%s'", item)
                return False
        return is_floats

    def is_list_offsets(self, input_string):
        """Checks that input string is a valid list of offsets."""
        list_input = input_string.split(";")
        try:
            for off_pair in list_input:
                offset = off_pair.split(",")
                if len(offset) != 2:
                    return False
                try:
                    int(offset[0])
                    int(offset[1])
                except ValueError:
                    sp_logging.G_LOGGER.info("int type check failed for: '%s' or '%s'", offset[0], offset[1])
                    return False
        except TypeError:
            return False
        # Passed tests.
        return True

    def is_valid_hotkey(self, input_string):
        """A dummy / placeholder method for checking input hotkey."""
        # Validity is hard to properly verify here.
        # Instead do it when registering hotkeys at startup.
        input_string = "" + input_string
        return True

    def is_list_valid_paths(self, input_list):
        """Verifies that input list contains paths and that they're valid."""
        if input_list == [""]:
            msg = "At least one path for wallpapers must be given."
            show_message_dialog(msg, "Error")
            return False
        if "" in input_list:
            msg = "Add an image source for every display present."
            show_message_dialog(msg, "Error")
            return False
        if self.spangroups:
            num_groups = len(self.spangroups.split(","))
            if len(input_list) < num_groups:
                msg = "Add an image source for every span group."
                show_message_dialog(msg, "Error")
                return False
        for path_list_str in input_list:
            path_list = path_list_str.split(";")
            for path in path_list:
                if os.path.isdir(path) is True:
                    if any(wpproc.is_supported_image(f) for f in os.listdir(path)):
                        continue
                    else:
                        msg = f"Path '{path}' does not contain supported image files."
                        show_message_dialog(msg, "Error")
                        return False
                elif os.path.isfile(path) is True:
                    if wpproc.is_supported_image(path):
                        continue
                    else:
                        msg = f"Image '{path}' is not a supported image file."
                        show_message_dialog(msg, "Error")
                        return False
                else:
                    msg = f"Path '{path}' was not recognized as a directory."
                    show_message_dialog(msg, "Error")
                    return False
        valid_pathsarray = True
        return valid_pathsarray
