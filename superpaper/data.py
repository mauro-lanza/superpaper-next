"""
Data storage classes for Superpaper.

Written by Henri Hänninen.
"""

from __future__ import annotations

import datetime
import errno
import logging
import math
import os
import random
import stat
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from enum import Enum, auto
from io import StringIO
from pathlib import Path

import superpaper.sp_logging as sp_logging
import superpaper.sp_paths as sp_paths
import superpaper.wallpaper_processing as wpproc
from superpaper.message_dialog import show_message_dialog
from superpaper.profile_id import ManagedPathError, ProfileId, ProfileIdError, profile_path
from superpaper.sp_paths import CONFIG_PATH, TEMP_PATH
from superpaper.sp_platform import IS_MACOS


class ProfileDiagnosticKind(Enum):
    INVALID_FILENAME = auto()
    NOT_REGULAR_FILE = auto()
    SYMLINK = auto()
    PORTABLE_COLLISION = auto()
    NAME_MISMATCH = auto()
    MALFORMED_CONTENT = auto()
    IO_ERROR = auto()


@dataclass(frozen=True, slots=True)
class ProfileDiscoveryDiagnostic:
    path: Path
    kind: ProfileDiagnosticKind
    detail: str
    profile_id: ProfileId | None = None
    identity: FileIdentity | None = None


@dataclass(frozen=True, slots=True)
class ProfileDiscoveryEntry:
    profile_id: ProfileId
    path: Path
    text: str
    identity: FileIdentity
    profile: ProfileData


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int

    @classmethod
    def from_stat(cls, result: os.stat_result) -> FileIdentity:
        return cls(result.st_dev, result.st_ino)


@dataclass(frozen=True, slots=True)
class ProfileInventory:
    entries: tuple[ProfileDiscoveryEntry, ...]
    diagnostics: tuple[ProfileDiscoveryDiagnostic, ...]

    def find(self, profile_id: ProfileId) -> ProfileDiscoveryEntry | None:
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


_DESTINATION_WRITE = "destination write"
_SOURCE_VERIFICATION = "source verification"
_SOURCE_REMOVAL = "source removal"
_ACTIVE_POINTER_UPDATE = "active pointer update"


def discover_profile_inventory() -> ProfileInventory:
    """Inspect managed profile leaves and capture each file from one descriptor.

    ``O_NOFOLLOW`` closes the leaf-symlink race on platforms that provide it.
    The portable fallback compares ``lstat`` and ``fstat`` identities, which
    still has a residual race if an attacker replaces a leaf and reuses its
    inode between those calls.
    """
    root = Path(sp_paths.PROFILES_PATH).resolve()
    candidates: list[ProfileDiscoveryEntry] = []
    diagnostics: list[ProfileDiscoveryDiagnostic] = []
    try:
        leaves = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError as error:
        diagnostics.append(ProfileDiscoveryDiagnostic(root, ProfileDiagnosticKind.NOT_REGULAR_FILE, str(error)))
        return ProfileInventory((), tuple(diagnostics))

    identified: list[tuple[Path, ProfileId]] = []
    by_collision: dict[str, list[tuple[Path, ProfileId]]] = {}
    for path in leaves:
        if path.suffix != ".profile":
            continue
        try:
            profile_id = ProfileId.parse(path.stem)
        except ProfileIdError as error:
            diagnostics.append(ProfileDiscoveryDiagnostic(path, ProfileDiagnosticKind.INVALID_FILENAME, str(error)))
            continue
        identified.append((path, profile_id))
        by_collision.setdefault(profile_id.collision_key, []).append((path, profile_id))

    colliding = {key for key, collision_entries in by_collision.items() if len(collision_entries) > 1}
    for path, profile_id in identified:
        if profile_id.collision_key in colliding:
            diagnostics.append(
                ProfileDiscoveryDiagnostic(
                    path,
                    ProfileDiagnosticKind.PORTABLE_COLLISION,
                    "Profile filename has a portable collision.",
                    profile_id,
                )
            )

    for path, profile_id in identified:
        try:
            content, identity = _read_managed_profile(path)
        except ManagedPathError as error:
            kind = ProfileDiagnosticKind.SYMLINK if path.is_symlink() else ProfileDiagnosticKind.NOT_REGULAR_FILE
            diagnostics.append(ProfileDiscoveryDiagnostic(path, kind, str(error), profile_id))
            continue
        except OSError as error:
            kind = ProfileDiagnosticKind.SYMLINK if error.errno == errno.ELOOP else ProfileDiagnosticKind.IO_ERROR
            diagnostics.append(ProfileDiscoveryDiagnostic(path, kind, str(error), profile_id))
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeError as error:
            diagnostics.append(
                ProfileDiscoveryDiagnostic(
                    path, ProfileDiagnosticKind.MALFORMED_CONTENT, str(error), profile_id, identity
                )
            )
            continue
        try:
            _validate_profile_syntax(text)
        except (IndexError, ValueError) as error:
            diagnostics.append(
                ProfileDiscoveryDiagnostic(
                    path, ProfileDiagnosticKind.MALFORMED_CONTENT, str(error), profile_id, identity
                )
            )
            continue
        if profile_id.collision_key in colliding:
            continue
        lines = text.splitlines()
        names = [line[5:] for line in lines if line.startswith("name=")]
        if names != [profile_id.value]:
            diagnostics.append(
                ProfileDiscoveryDiagnostic(
                    path,
                    ProfileDiagnosticKind.NAME_MISMATCH,
                    "Profile must contain exactly one name matching its filename stem.",
                    profile_id,
                    identity,
                )
            )
            continue
        try:
            profile = ProfileData(
                os.fspath(path),
                profile_id,
                profile_text=text,
                source_identity=identity,
            )
        except Exception as error:
            diagnostics.append(
                ProfileDiscoveryDiagnostic(
                    path, ProfileDiagnosticKind.MALFORMED_CONTENT, str(error), profile_id, identity
                )
            )
            continue
        candidates.append(ProfileDiscoveryEntry(profile_id, path, text, identity, profile))

    return ProfileInventory(tuple(candidates), tuple(diagnostics))


def _read_managed_profile(path: Path, expected_identity: FileIdentity | None = None) -> tuple[bytes, FileIdentity]:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    before = None
    if nofollow:
        flags |= nofollow
    else:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode):
            message = f"Managed profile paths cannot be symbolic links: {path}"
            raise ManagedPathError(message)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            message = f"Managed profile paths must be regular files: {path}"
            raise ManagedPathError(message)
        identity = FileIdentity.from_stat(opened)
        if before is not None and FileIdentity.from_stat(before) != identity:
            message = f"Managed profile changed while being opened: {path}"
            raise ManagedPathError(message)
        if expected_identity is not None and identity != expected_identity:
            message = f"Managed profile changed since it was loaded: {path}"
            raise ManagedPathError(message)
        chunks = []
        while chunk := os.read(fd, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks), identity
    finally:
        os.close(fd)


def _regular_destination_identity(path: Path, *, allow_missing: bool) -> FileIdentity | None:
    """Return a regular destination's identity, rejecting symlinks and special files."""
    try:
        destination = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        message = f"Managed file does not exist: {path}"
        raise ManagedPathError(message) from None
    if stat.S_ISLNK(destination.st_mode):
        message = f"Managed file paths cannot be symbolic links: {path}"
        raise ManagedPathError(message)
    if not stat.S_ISREG(destination.st_mode):
        message = f"Managed file paths must be regular files: {path}"
        raise ManagedPathError(message)
    return FileIdentity.from_stat(destination)


def _regular_destination_identity_at(directory_fd: int, path: Path, *, allow_missing: bool) -> FileIdentity | None:
    """Inspect a direct leaf relative to an already trusted directory."""
    try:
        destination = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            return None
        message = f"Managed file does not exist: {path}"
        raise ManagedPathError(message) from None
    if stat.S_ISLNK(destination.st_mode):
        message = f"Managed file paths cannot be symbolic links: {path}"
        raise ManagedPathError(message)
    if not stat.S_ISREG(destination.st_mode):
        message = f"Managed file paths must be regular files: {path}"
        raise ManagedPathError(message)
    return FileIdentity.from_stat(destination)


_HAS_DIR_FD_MUTATIONS = all(
    operation in os.supports_dir_fd for operation in (os.open, os.stat, os.unlink, os.link, os.rename)
)


def _open_managed_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags)


def _open_verified_managed_at(directory_fd: int, path: Path, expected_identity: FileIdentity) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path.name, flags, dir_fd=directory_fd)
    try:
        opened = os.fstat(fd)
        if stat.S_ISREG(opened.st_mode) and FileIdentity.from_stat(opened) == expected_identity:
            return fd
    except Exception:
        os.close(fd)
        raise
    os.close(fd)
    message = f"Managed profile changed since it was loaded: {path}"
    raise ManagedPathError(message)


def _atomic_write_regular(
    path: Path,
    content: bytes,
    *,
    may_replace: bool,
    expected_identity: FileIdentity | None = None,
) -> FileIdentity:
    """Atomically write a direct leaf without following the destination.

    Exclusive hard-link publication makes creates fail if the destination
    appears concurrently. Replacing an existing file remains subject to the
    unavoidable portable race between the final identity check and rename;
    directory-relative operations constrain that race to a trusted root and
    all observed destinations are rejected unless regular and non-symlinks.
    """
    directory_fd = _open_managed_directory(path.parent) if _HAS_DIR_FD_MUTATIONS else None

    def identity_reader(*, allow_missing: bool) -> FileIdentity | None:
        if directory_fd is not None:
            return _regular_destination_identity_at(directory_fd, path, allow_missing=allow_missing)
        return _regular_destination_identity(path, allow_missing=allow_missing)

    try:
        original_identity = identity_reader(allow_missing=True)
    except Exception:
        if directory_fd is not None:
            os.close(directory_fd)
        raise
    if original_identity is not None and not may_replace:
        if directory_fd is not None:
            os.close(directory_fd)
        message = f"Managed file already exists: {path}"
        raise FileExistsError(message)
    if expected_identity is not None and original_identity != expected_identity:
        if directory_fd is not None:
            os.close(directory_fd)
        message = f"Managed file changed since it was loaded: {path}"
        raise ManagedPathError(message)

    try:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    except Exception:
        if directory_fd is not None:
            os.close(directory_fd)
        raise
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
            published_identity = FileIdentity.from_stat(os.fstat(output.fileno()))

        if may_replace and original_identity is not None:
            verified_fd = (
                _open_verified_managed_at(directory_fd, path, original_identity)
                if directory_fd is not None
                else _open_verified_managed(path, original_identity)
            )
            try:
                if identity_reader(allow_missing=True) != FileIdentity.from_stat(os.fstat(verified_fd)):
                    message = f"Managed file changed while being saved: {path}"
                    raise FileExistsError(message)
                if directory_fd is not None:
                    os.replace(
                        temporary.name,
                        path.name,
                        src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd,
                    )
                else:
                    os.replace(temporary, path)
            finally:
                os.close(verified_fd)
        else:
            # Publishing with a hard link is an atomic create-if-absent. Unlike
            # os.replace, it cannot overwrite a destination created by a race.
            if directory_fd is not None:
                if identity_reader(allow_missing=True) is not None:
                    message = f"Managed file already exists: {path}"
                    raise FileExistsError(message)
                os.link(
                    temporary.name,
                    path.name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                os.unlink(temporary.name, dir_fd=directory_fd)
            else:
                os.link(temporary, path)
                temporary.unlink()
        if identity_reader(allow_missing=False) != published_identity:
            message = f"Managed file changed immediately after publication: {path}"
            raise FileExistsError(message)
        return published_identity
    finally:
        try:
            if directory_fd is not None:
                os.unlink(temporary.name, dir_fd=directory_fd)
            else:
                temporary.unlink()
        except FileNotFoundError:
            pass
        if directory_fd is not None:
            os.close(directory_fd)


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
def list_profiles() -> list[ProfileData]:
    """List discoverable profiles, retaining the legacy malformed-content prompt."""
    profile_list = []
    inventory = discover_profile_inventory()
    for entry in inventory.entries:
        profile_list.append(entry.profile)
    identity_diagnostic_paths = {
        diagnostic.path
        for diagnostic in inventory.diagnostics
        if diagnostic.kind
        in {
            ProfileDiagnosticKind.INVALID_FILENAME,
            ProfileDiagnosticKind.NOT_REGULAR_FILE,
            ProfileDiagnosticKind.SYMLINK,
            ProfileDiagnosticKind.PORTABLE_COLLISION,
            ProfileDiagnosticKind.NAME_MISMATCH,
            ProfileDiagnosticKind.IO_ERROR,
        }
    }
    for diagnostic in inventory.diagnostics:
        if (
            diagnostic.kind is ProfileDiagnosticKind.MALFORMED_CONTENT
            and diagnostic.path not in identity_diagnostic_paths
        ):
            _prompt_to_delete_malformed_profile(diagnostic.path, diagnostic.identity, diagnostic.detail)
    return profile_list


def _prompt_to_delete_malformed_profile(path: Path, identity: FileIdentity | None, error: object) -> None:
    msg = (
        f"There was an error when loading profile '{path.name}'.\n"
        "Would you like to delete it? Choosing 'No' will just ignore the profile."
    )
    sp_logging.G_LOGGER.info(msg)
    sp_logging.G_LOGGER.info(error)
    if show_message_dialog(msg, "Error", style="YES_NO"):
        if identity is None:
            sp_logging.G_LOGGER.info("Retaining malformed profile without a captured file identity: %s", path)
            return
        sp_logging.G_LOGGER.info("Removing profile: %s", path)
        try:
            _remove_managed_path(path, identity)
        except OSError as unlink_error:
            sp_logging.G_LOGGER.info("Retaining malformed profile because verified removal failed: %s", unlink_error)
        except ManagedPathError as identity_error:
            sp_logging.G_LOGGER.info("Retaining malformed profile because its identity changed: %s", identity_error)


def open_profile(profile: ProfileId | str):
    """Return a discoverable managed profile by validated identity."""
    try:
        profile_id = profile if isinstance(profile, ProfileId) else ProfileId.parse(profile)
    except ProfileIdError:
        return None
    entry = discover_profile_inventory().find(profile_id)
    if entry is None:
        return None
    try:
        profile_path(Path(sp_paths.PROFILES_PATH), profile_id, allow_missing=False)
        _read_managed_profile(entry.path, entry.identity)
        return _profile_from_entry(entry)
    except ManagedPathError, OSError, ProfileDataException, ValueError, ZeroDivisionError:
        return None


def parse_profile_file(path: str | os.PathLike[str]):
    """Explicitly parse an arbitrary profile file, such as a GUI preview."""
    return ProfileData(path, persist_selection=False)


def _profile_from_entry(entry: ProfileDiscoveryEntry):
    return entry.profile


def validate_managed_profile_id(name: object, current_profile_id: ProfileId | None = None) -> ProfileId:
    """Validate a save identity and reject portable collisions with managed leaves."""
    profile_id = ProfileId.parse(name)
    root = Path(sp_paths.PROFILES_PATH)
    try:
        leaves = root.iterdir()
        for path in leaves:
            if path.suffix != ".profile":
                continue
            try:
                existing_id = ProfileId.parse(path.stem)
            except ProfileIdError:
                continue
            if current_profile_id is not None and existing_id == current_profile_id == profile_id:
                continue
            if existing_id.collision_key == profile_id.collision_key:
                message = f"Profile name collides with existing profile '{existing_id.value}'."
                raise ValueError(message)
    except FileNotFoundError:
        pass
    return profile_id


def delete_managed_profile(profile: ProfileData) -> None:
    """Delete the managed regular file represented by a loaded profile."""
    if profile.profile_id is None or profile.source_identity is None:
        message = "Only a loaded managed profile can be deleted."
        raise ManagedPathError(message)
    path = profile_path(Path(sp_paths.PROFILES_PATH), profile.profile_id, allow_missing=False)
    _remove_managed_path(path, profile.source_identity)


def managed_profile_for_selection(profiles: list[ProfileData], profile_id: ProfileId) -> ProfileData | None:
    """Resolve a GUI selection by managed identity, independent of editable fields."""
    return next((profile for profile in profiles if profile.profile_id == profile_id), None)


def _remove_managed_path(path: Path, expected_identity: FileIdentity) -> None:
    """Unlink a regular leaf only while its captured identity still matches.

    The opened descriptor and directory-relative stat verify identity directly
    before unlink. Kernels without compare-and-unlink still leave a residual
    replacement race between that check and unlink; the path-based fallback
    additionally has an inode-reuse race.
    """
    directory_fd = _open_managed_directory(path.parent) if _HAS_DIR_FD_MUTATIONS else None
    fd = (
        _open_verified_managed_at(directory_fd, path, expected_identity)
        if directory_fd is not None
        else _open_verified_managed(path, expected_identity)
    )
    try:
        current_identity = (
            _regular_destination_identity_at(directory_fd, path, allow_missing=False)
            if directory_fd is not None
            else _regular_destination_identity(path, allow_missing=False)
        )
        if current_identity != FileIdentity.from_stat(os.fstat(fd)):
            message = f"Managed profile changed while being deleted: {path}"
            raise ManagedPathError(message)
        if directory_fd is not None:
            os.unlink(path.name, dir_fd=directory_fd)
        else:
            path.unlink()
    finally:
        os.close(fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _open_verified_managed(path: Path, expected_identity: FileIdentity) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if stat.S_ISREG(opened.st_mode) and FileIdentity.from_stat(opened) == expected_identity:
            return fd
    except Exception:
        os.close(fd)
        raise
    os.close(fd)
    message = f"Managed profile changed since it was loaded: {path}"
    raise ManagedPathError(message)


def read_active_profile() -> ProfileData | None:
    """Reads last active profile from file at startup."""
    path = Path(sp_paths.TEMP_PATH) / "running_profile"
    try:
        content, _identity = _read_managed_profile(path)
    except FileNotFoundError:
        try:
            _atomic_write_regular(path, b"", may_replace=False)
        except OSError, ManagedPathError:
            pass
        return None
    except OSError, ManagedPathError:
        return None
    try:
        profname = content.decode("utf-8").splitlines()[0].rstrip("\r\n")
    except IndexError, UnicodeError:
        return None
    if profname:
        try:
            profile_id = ProfileId.parse(profname)
        except ProfileIdError:
            return None
        profile = open_profile(profile_id)
        if profile is not None:
            return profile
        sp_logging.G_LOGGER.info(
            "Exception: Previously run profile configuration \
                        file not found. Is the filename same as the \
                        profile name: %s?",
            profname,
        )
    return None


def write_active_profile(profile: ProfileId | str) -> None:
    """Writes active profile name to file after profile has changed."""
    profile_id = profile if isinstance(profile, ProfileId) else ProfileId.parse(profile)
    path = Path(sp_paths.TEMP_PATH) / "running_profile"
    _atomic_write_regular(path, profile_id.value.encode("utf-8"), may_replace=True)


def save_managed_profile(
    profile: TempProfileData,
    *,
    current_profile_id: ProfileId | None = None,
    expected_source_identity: FileIdentity | None = None,
    update_active: bool = False,
) -> Path:
    """Create, update, or rename a managed profile with bounded rollback."""
    try:
        destination_id = validate_managed_profile_id(profile.name, current_profile_id)
        destination = profile_path(Path(sp_paths.PROFILES_PATH), destination_id)
    except (OSError, ManagedPathError, ProfileIdError, ValueError) as error:
        raise ProfileTransactionError(_DESTINATION_WRITE, error) from error
    content = profile._serialize().encode("utf-8")

    if current_profile_id is None:
        try:
            _atomic_write_regular(destination, content, may_replace=False)
        except (OSError, ManagedPathError, ValueError) as error:
            raise ProfileTransactionError(_DESTINATION_WRITE, error) from error
        return destination

    if expected_source_identity is None:
        error = ManagedPathError("The save source has no captured managed-file identity.")
        raise ProfileTransactionError(_SOURCE_VERIFICATION, error) from error
    try:
        source_path = profile_path(Path(sp_paths.PROFILES_PATH), current_profile_id, allow_missing=False)
        source_content, source_identity = _read_managed_profile(source_path, expected_source_identity)
    except (OSError, ManagedPathError) as error:
        raise ProfileTransactionError(_SOURCE_VERIFICATION, error) from error

    if destination_id == current_profile_id:
        try:
            _atomic_write_regular(
                source_path,
                content,
                may_replace=True,
                expected_identity=source_identity,
            )
        except (OSError, ManagedPathError) as error:
            raise ProfileTransactionError(_DESTINATION_WRITE, error) from error
        return source_path

    try:
        destination_identity = _atomic_write_regular(destination, content, may_replace=False)
    except (OSError, ManagedPathError) as error:
        raise ProfileTransactionError(_DESTINATION_WRITE, error) from error

    try:
        _remove_managed_path(source_path, source_identity)
    except (OSError, ManagedPathError) as error:
        rollback_errors = _rollback_destination(destination, destination_identity)
        raise ProfileTransactionError(_SOURCE_REMOVAL, error, rollback_errors) from error

    if update_active:
        try:
            write_active_profile(destination_id)
        except (OSError, ManagedPathError) as error:
            rollback_errors = []
            source_restored = False
            try:
                _atomic_write_regular(source_path, source_content, may_replace=False)
                source_restored = True
            except (OSError, ManagedPathError) as rollback_error:
                rollback_errors.append(
                    rollback_error if isinstance(rollback_error, OSError) else OSError(str(rollback_error))
                )
            if source_restored:
                rollback_errors.extend(_rollback_destination(destination, destination_identity))
            raise ProfileTransactionError(_ACTIVE_POINTER_UPDATE, error, tuple(rollback_errors)) from error
    return destination


def _rollback_destination(path: Path, identity: FileIdentity) -> tuple[OSError, ...]:
    try:
        _remove_managed_path(path, identity)
    except (OSError, ManagedPathError) as error:
        return (error if isinstance(error, OSError) else OSError(str(error)),)
    return ()


class GeneralSettingsData:
    """Object to store and save application wide settings."""

    def __init__(self):
        self.logging = False
        self.use_hotkeys = True
        self.hk_binding_next = None
        self.hk_binding_pause = None
        self.set_command = ""
        self.browse_default_dir = ""
        self.show_help = True
        self.warn_large_img = True
        self.parse_settings()

    def parse_settings(self):
        """Parse general_settings file. Create it if it doesn't exists."""
        # Re-reading settings must clear a command that was removed from disk.
        self.set_command = ""
        fname = os.path.join(CONFIG_PATH, "general_settings")
        if os.path.isfile(fname):
            with open(fname) as general_settings_file:
                for line in general_settings_file:
                    words = line.strip().split("=", 1)
                    if words[0] == "logging":
                        wrds1 = words[1].strip().lower()
                        if wrds1 == "true":
                            self.logging = True
                            sp_logging.LOGGING = True
                            sp_logging.DEBUG = True
                            sp_logging.G_LOGGER = logging.getLogger("default")
                            sp_logging.G_LOGGER.setLevel(logging.INFO)
                            # Install exception handler
                            sys.excepthook = sp_logging.custom_exception_handler
                            file_handler = logging.FileHandler(os.path.join(TEMP_PATH, "log"), mode="w")
                            sp_logging.FILE_HANDLER = file_handler
                            sp_logging.G_LOGGER.addHandler(file_handler)
                            console_handler = logging.StreamHandler()
                            sp_logging.CONSOLE_HANDLER = console_handler
                            sp_logging.G_LOGGER.addHandler(console_handler)
                            sp_logging.G_LOGGER.info("Enabled logging to file.")
                    elif words[0] == "use hotkeys":
                        wrds1 = words[1].strip().lower()
                        if wrds1 == "true":
                            self.use_hotkeys = True
                        else:
                            self.use_hotkeys = False
                        if sp_logging.DEBUG:
                            sp_logging.G_LOGGER.info("use_hotkeys: %s", self.use_hotkeys)
                    elif words[0] == "next wallpaper hotkey":
                        binding_strings = words[1].strip().split("+")
                        if binding_strings:
                            self.hk_binding_next = tuple(binding_strings)
                        if sp_logging.DEBUG:
                            sp_logging.G_LOGGER.info("hk_binding_next: %s", self.hk_binding_next)
                    elif words[0] == "pause wallpaper hotkey":
                        binding_strings = words[1].strip().split("+")
                        if binding_strings:
                            self.hk_binding_pause = tuple(binding_strings)
                        if sp_logging.DEBUG:
                            sp_logging.G_LOGGER.info("hk_binding_pause: %s", self.hk_binding_pause)
                    elif words[0] == "set_command":
                        self.set_command = words[1].strip()
                    elif words[0].strip() == "show_help_at_start":
                        show_state = words[1].strip().lower()
                        if show_state == "false":
                            self.show_help = False
                        else:
                            pass
                    elif words[0].strip() == "warn_large_img":
                        show_state = words[1].strip().lower()
                        if show_state == "false":
                            self.warn_large_img = False
                        else:
                            pass
                    elif words[0].strip() == "browse_default_dir":
                        self.browse_default_dir = words[1].strip()
                    else:
                        sp_logging.G_LOGGER.info(
                            "GeneralSettings parse Exception: Unkown general setting: %s", words[0]
                        )
        else:
            # if file does not exist, create it and write default values.
            with open(fname, "x") as general_settings_file:
                general_settings_file.write("logging=false\n")
                if IS_MACOS:
                    general_settings_file.write("use hotkeys=false\n")
                else:
                    general_settings_file.write("use hotkeys=true\n")
                general_settings_file.write("next wallpaper hotkey=control+super+w\n")
                self.hk_binding_next = ("control", "super", "w")
                general_settings_file.write("pause wallpaper hotkey=control+super+shift+p\n")
                self.hk_binding_pause = ("control", "super", "shift", "p")
                general_settings_file.write("set_command=\n")
                general_settings_file.write("browse_default_dir=\n")
                general_settings_file.write("warn_large_img=true")
        wpproc.G_SET_COMMAND_STRING = self.set_command

    def save_settings(self):
        """Save the current state of the general settings object."""

        fname = os.path.join(CONFIG_PATH, "general_settings")
        with open(fname, "w") as general_settings_file:
            if self.logging:
                general_settings_file.write("logging=true\n")
            else:
                general_settings_file.write("logging=false\n")

            if self.use_hotkeys:
                general_settings_file.write("use hotkeys=true\n")
            else:
                general_settings_file.write("use hotkeys=false\n")

            if self.hk_binding_next:
                hk_string = "+".join(self.hk_binding_next)
                general_settings_file.write(f"next wallpaper hotkey={hk_string}\n")

            if self.hk_binding_pause:
                hk_string_p = "+".join(self.hk_binding_pause)
                general_settings_file.write(f"pause wallpaper hotkey={hk_string_p}\n")

            if self.show_help:
                general_settings_file.write("show_help_at_start=true\n")
            else:
                general_settings_file.write("show_help_at_start=false\n")

            general_settings_file.write(f"set_command={self.set_command}\n")
            general_settings_file.write(f"browse_default_dir={self.browse_default_dir}\n")

            if self.warn_large_img:
                general_settings_file.write("warn_large_img=true")
            else:
                general_settings_file.write("warn_large_img=false")


class ProfileDataException(Exception):
    """ProfileData initialization error handler."""

    def __init__(self, message, profile_name, parse_file, errors):
        super().__init__(message)
        sp_logging.G_LOGGER.info("%s %s %s", message, profile_name, parse_file)
        sp_logging.G_LOGGER.info(errors)


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
        source_identity: FileIdentity | None = None,
        persist_selection: bool = True,
    ):
        if not wpproc.RESOLUTION_ARRAY:
            msg = "Cannot parse profile, monitor resolution data is missing."
            show_message_dialog(msg)
            sp_logging.G_LOGGER.error(msg)
            sys.exit()

        self.file = profile_file
        self.name = "default_profile"
        self.spanmode = "single"  # single / advanced / multi
        self.spangroups = None
        self.slideshow = True
        self.delay_list: list[float] = [600]
        self.sortmode = "shuffle"  # shuffle / alphabetical / date_seeded_shuffle
        self.ppimode = False
        self.ppi_array = wpproc.NUM_DISPLAYS * [100]
        self.ppi_array_relative_density = []
        self.inches = []
        self.manual_offsets = wpproc.NUM_DISPLAYS * [(0, 0)]
        self.manual_offsets_useronly = []
        self.bezels = []
        self.bezel_px_offsets = []
        self.hk_binding = None
        self.perspective = "default"
        self.zoom = 1.0
        self.offsets = (0.0, 0.0)
        self.paths_array = []
        self.selected = None

        self.parse_profile(StringIO(profile_text) if profile_text is not None else self.file)
        if profile_id is not None and self.name != profile_id.value:
            message = "Profile name does not match its managed filename."
            raise ProfileDataException(message, self.name, self.file, profile_id.value)
        self.profile_id: ProfileId | None = profile_id
        self.source_identity = source_identity
        self.persist_selection = persist_selection
        if self.ppimode is True:
            self.compute_relative_densities()
            if self.bezels:
                self.compute_bezel_px_offsets()
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
                    line.strip()
                    words = line.split("=")
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
                        # Use PPI mode algorithm to do cuts.
                        # Defaults assume uniform pixel density
                        # if no custom values are given.
                        offs = []
                        offs_user_only = []
                        # w1,h1;w2,h2;...
                        offset_strings = words[1].strip().split(";")
                        for offstr in offset_strings:
                            res_str = offstr.split(",")
                            try:
                                offs.append((int(res_str[0]), int(res_str[1])))
                                offs_user_only.append((int(res_str[0]), int(res_str[1])))
                            except ValueError, IndexError:
                                offs.append((0, 0))
                                offs_user_only.append((0, 0))
                        while len(offs) < wpproc.NUM_DISPLAYS:
                            offs.append((0, 0))
                            offs_user_only.append((0, 0))
                        self.ppimode = True
                        self.manual_offsets = offs
                        self.manual_offsets_useronly = offs_user_only
                    elif words[0] == "bezels":
                        bez_mm_strings = words[1].strip().split(";")
                        for bezstr in bez_mm_strings:
                            self.bezels.append(float(bezstr))
                    elif words[0] == "ppi":
                        self.ppimode = True
                        # overwrite initialized arrays.
                        self.ppi_array = []
                        self.ppi_array_relative_density = []
                        ppi_strings = words[1].strip().split(";")
                        for ppistr in ppi_strings:
                            self.ppi_array.append(int(ppistr))
                    elif words[0] == "diagonal_inches":
                        self.ppimode = True
                        # overwrite initialized arrays.
                        self.ppi_array = []
                        self.ppi_array_relative_density = []
                        inch_strings = words[1].strip().split(";")
                        self.inches = []
                        for inchstr in inch_strings:
                            self.inches.append(float(inchstr))
                        self.ppi_array = self.compute_ppis(self.inches)
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
                        sel = line.split("=", 1)[1].strip()
                        sel_files = [p for p in sel.split(";") if p]
                        self.selected = sel_files or None
                    elif words[0].startswith("display"):
                        paths = words[1].strip().split(";")
                        paths = list(filter(None, paths))  # drop empty strings
                        self.paths_array.append(paths)
                    else:
                        sp_logging.G_LOGGER.info("Unknown setting line in config: %s", line)
        except Exception as excep:
            msg = "There was an error parsing the profile:"
            raise ProfileDataException(msg, self.name, self.file, excep) from excep

    def compute_ppis(self, inches):
        """Compute monitor PPIs from user input diagonal inches."""
        if len(inches) < wpproc.NUM_DISPLAYS:
            sp_logging.G_LOGGER.info(
                "Exception: Number of read display diagonals was: \
                                     %s , but the number of displays was found to be: %s",
                str(len(inches)),
                str(wpproc.NUM_DISPLAYS),
            )
            sp_logging.G_LOGGER.info("Falling back to no PPI correction.")
            self.ppimode = False
            return wpproc.NUM_DISPLAYS * [100]
        else:
            ppi_array = []
            for inch, res in zip(inches, wpproc.RESOLUTION_ARRAY):
                diagonal_px = math.sqrt(res[0] ** 2 + res[1] ** 2)
                px_per_inch = diagonal_px / inch
                ppi_array.append(px_per_inch)
            if sp_logging.DEBUG:
                sp_logging.G_LOGGER.info("Computed PPIs: %s", ppi_array)
            return ppi_array

    def compute_relative_densities(self):
        """
        Normalizes the ppi_array list such that the max ppi has the relative value 1.0.

        This means that every other display has an equal relative density or a lesser
        value. The benefit of this normalization is that the resulting corrected
        image sections never have to be scaled up in the end, which would happen with
        relative densities of over 1.0. This presumably yields a slight improvement
        in the resulting image quality in some worst case scenarios.
        """
        if self.ppi_array:
            max_density = max(self.ppi_array)
        else:
            sp_logging.G_LOGGER.error("Couldn't compute relative densities: %s, %s", self.name, self.file)
            return 1
        for ppi in self.ppi_array:
            self.ppi_array_relative_density.append((1 / max_density) * float(ppi))
        # if sp_logging.DEBUG:
        #     sp_logging.G_LOGGER.info("relative pixel densities: %s",
        #                              self.ppi_array_relative_density)

    def compute_bezel_px_offsets(self):
        """Computes bezel sizes in pixels based on display PPIs."""
        if self.ppi_array:
            max_ppi = max(self.ppi_array)
        else:
            sp_logging.G_LOGGER.error("Couldn't compute relative densities: %s, %s", self.name, self.file)
            return 1

        bez_px_offs = [0]  # never offset 1st disp, anchor to it.
        inch_per_mm = 1.0 / 25.4
        for bez_mm in self.bezels:
            bez_px_offs.append(round(float(max_ppi) * inch_per_mm * bez_mm))
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info(
                "Bezel px calculation: initial manual offset: %s, \
                and bezel pixels: %s",
                self.manual_offsets,
                bez_px_offs,
            )
        if len(bez_px_offs) < wpproc.NUM_DISPLAYS:
            if sp_logging.DEBUG:
                sp_logging.G_LOGGER.info("Bezel px calculation: Too few bezel mm values given! Appending zeros.")
            while len(bez_px_offs) < wpproc.NUM_DISPLAYS:
                bez_px_offs.append(0)
        elif len(bez_px_offs) > wpproc.NUM_DISPLAYS:
            if sp_logging.DEBUG:
                sp_logging.G_LOGGER.info("Bezel px calculation: Got more bezel mm values than expected!")
            # Currently ignore list tail if there are too many bezel values
        # Add these horizontal offsets to manual_offsets:
        # Avoid offsetting the leftmost anchored display i==0
        for i in range(1, min(len(bez_px_offs), wpproc.NUM_DISPLAYS)):
            # Add previous offsets to ones further away to the right.
            # Each display needs to be offset by the given bezel relative to
            # the display to its left, which can be shifted relative to
            # the anchor.
            bez_px_offs[i] += bez_px_offs[i - 1]
            self.manual_offsets[i] = (
                self.manual_offsets[i][0] + bez_px_offs[i],
                self.manual_offsets[i][1],
            )
        self.bezel_px_offsets = bez_px_offs
        if sp_logging.DEBUG:
            sp_logging.G_LOGGER.info("Bezel px calculation: resulting combined manual offset: %s", self.manual_offsets)

    def next_wallpaper_files(self, peek=False):
        """Return the current wallpaper file(s).

        A persistent selection is the source of truth for what is shown. Only
        an explicit cycle (advance_wallpaper) moves to the next image, so the
        wallpaper never changes merely because the profile is rendered again.
        """
        if self.has_valid_selection():
            return list(self.selected or [])
        if self.selected:
            self.selected = None
            self._write_selected()
        return self.file_handler.next_wallpaper_files(peek=peek)

    def selection_target_count(self):
        """Return how many positional image choices this profile requires."""
        if self.spanmode == "multi":
            return wpproc.NUM_DISPLAYS
        if self.spanmode == "advanced" and self.spangroups:
            return len(self.spangroups)
        return 1

    def has_valid_selection(self):
        """Check that the complete positional selection can still be rendered."""
        return bool(
            self.selected
            and len(self.selected) == self.selection_target_count()
            and all(
                os.path.isfile(path) and path.lower().endswith(wpproc.G_SUPPORTED_IMAGE_EXTENSIONS)
                for path in self.selected
            )
        )

    def advance_wallpaper(self):
        """Cycle to the next image(s) and make the result the current selection."""
        files = self.file_handler.next_wallpaper_files()
        if len(files) == self.selection_target_count():
            self.selected = files
            self._write_selected()
            return list(files)
        return []

    def set_selected_wallpaper(self, files, persist=True):
        """Pin the given file(s) as the current selection.

        The selection is the source of truth for what is rendered; pinning it
        keeps the preview and the applied wallpaper in sync across reloads.
        When ``persist`` is True the choice is written into the profile file so
        it survives a restart.
        """
        self.selected = list(files) if files else None
        if persist:
            self._write_selected()

    def _write_selected(self):
        """Persist the current selection into the profile file."""
        if not self.persist_selection:
            return
        if self.profile_id is None or self.source_identity is None:
            self._write_selected_unmanaged()
            return
        try:
            path = profile_path(Path(sp_paths.PROFILES_PATH), self.profile_id, allow_missing=False)
            content, identity = _read_managed_profile(path, self.source_identity)
            lines = [ln for ln in content.decode("utf-8").splitlines(keepends=True) if not ln.startswith("selected=")]
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            if self.selected:
                lines.append("selected=" + ";".join(self.selected) + "\n")
            self.source_identity = _atomic_write_regular(
                path,
                "".join(lines).encode("utf-8"),
                may_replace=True,
                expected_identity=identity,
            )
        except (OSError, UnicodeError, ManagedPathError) as err:
            sp_logging.G_LOGGER.info("Failed to persist wallpaper selection: %s", err)

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
                            if path.lower().endswith(wpproc.G_SUPPORTED_IMAGE_EXTENSIONS):
                                list_of_images += [path]
                            else:
                                pass
                        else:
                            list_of_images += [
                                os.path.join(path, f)
                                for f in os.listdir(path)
                                if f.lower().endswith(wpproc.G_SUPPORTED_IMAGE_EXTENSIONS)
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
        self.ppimode = False  # keep this for legacy profile support
        self.perspective = perspective
        self.zoom = 1.0
        self.offsets = (0.0, 0.0)
        self.manual_offsets = wpproc.NUM_DISPLAYS * [(0, 0)]

        if len(files) == 1 and not advanced:
            self.spanmode = "single"
        elif advanced:
            self.spanmode = "advanced"
        else:
            self.spanmode = "multi"

        if offsets:
            off_pairs_zip = zip(*[iter(offsets)] * 2)
            off_pairs = [tuple(p) for p in off_pairs_zip]
            for off, i in zip(off_pairs, range(len(self.manual_offsets))):
                self.manual_offsets[i] = off
            for pair in self.manual_offsets:
                self.manual_offsets[self.manual_offsets.index(pair)] = (int(pair[0]), int(pair[1]))

        for item in files:
            self.files.append(os.path.realpath(item))
        # CLI/preview profiles use a fixed image set; treat it as the selection
        # so the renderer never tries to cycle.
        self.selected = self.files

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

    def save(self, filename=None, *, current_profile_id: ProfileId | None = None):
        """Saves the TempProfile into a file.

        By default the profile is written to ``<name>.profile`` in
        PROFILES_PATH. Pass ``filename`` to write to a specific path instead;
        this is used to render unsaved edits (preview) without overwriting the
        stored profile on disk.
        """
        if self.name is None:
            sp_logging.G_LOGGER.info("tmp.Save(): name is not set.")
            return None
        if filename is None:
            try:
                profile_id = validate_managed_profile_id(self.name, current_profile_id)
                fname = profile_path(Path(sp_paths.PROFILES_PATH), profile_id)
                may_replace = current_profile_id == profile_id
                _atomic_write_regular(fname, self._serialize().encode("utf-8"), may_replace=may_replace)
            except (ManagedPathError, OSError, ProfileIdError, ValueError) as error:
                show_message_dialog(str(error), "Error")
                return None
            return fname
        else:
            fname = filename
        try:
            with open(fname, "w", encoding="utf-8") as tpfile:
                tpfile.write(self._serialize())
        except OSError:
            msg = f"Cannot write to file {fname}"
            show_message_dialog(msg, "Error")
            return None
        return fname

    def _serialize(self):
        """Return the ``.profile`` file contents for this profile as a string.

        This is the single source of truth for the on-disk profile format:
        ``save()`` writes exactly this, and the GUI compares this representation
        to decide whether there are unsaved changes.
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
        if self.selected:
            lines.append("selected=" + ";".join(self.selected))
        if self.paths_array:
            lines.extend(
                "display" + str(self.paths_array.index(paths)) + "paths=" + paths for paths in self.paths_array
            )
        return "\n".join(lines) + "\n"

    def test_save(self, *, current_profile_id: ProfileId | None = None, managed: bool = True):
        """Tests whether the user input for profile settings is valid."""
        valid_profile = False
        if self.name is not None and self.name.strip() != "":
            if managed:
                try:
                    validate_managed_profile_id(self.name, current_profile_id)
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
        # if len(list_input) < wpproc.NUM_DISPLAYS:
        #     msg = "Enter an offset for every display, even if it is (0,0)."
        #     show_message_dialog(msg, "Error")
        #     return False
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
                    supported_files = [f for f in os.listdir(path) if f.endswith(wpproc.G_SUPPORTED_IMAGE_EXTENSIONS)]
                    if supported_files:
                        continue
                    else:
                        msg = f"Path '{path}' does not contain supported image files."
                        show_message_dialog(msg, "Error")
                        return False
                elif os.path.isfile(path) is True:
                    if path.endswith(wpproc.G_SUPPORTED_IMAGE_EXTENSIONS):
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
