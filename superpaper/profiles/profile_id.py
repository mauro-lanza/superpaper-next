"""Profile identity: which filenames are profiles, and where their files may live."""

import unicodedata
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


class ProfileIdError(ValueError):
    """A profile identifier failed portable validation."""


NEW_PROFILE_LABEL = "Create a new profile"
"""The profile dropdown's entry for starting a new profile; no profile may be named so."""
_WINDOWS_INVALID_CHARACTERS = frozenset('<>:"|?*')
_MAX_PROFILE_NAME_CHARS = 50
_RESERVED_APPLICATION_NAMES = frozenset({NEW_PROFILE_LABEL.casefold(), "cli"})
_WINDOWS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
    | {"com¹", "com²", "com³", "lpt¹", "lpt²", "lpt³"}
)


@dataclass(frozen=True, slots=True)
class ProfileId:
    """The filename stem that identifies one wallpaper profile.

    ``parse`` accepts every name that can safely be a profile file on this system, so
    profiles saved by older versions keep loading; ``windows_names`` says whether that
    includes Windows' filename rules. ``parse_new`` also requires the name to be
    portable; use it for names Superpaper is about to create.
    """

    value: str

    def __post_init__(self) -> None:
        _raise_if_problem(_path_safety_problem(self.value))

    @classmethod
    def parse(cls, raw: str, *, windows_names: bool) -> ProfileId:
        profile_id = cls(raw)
        if windows_names:
            _raise_if_problem(_windows_problem(raw))
        return profile_id

    @classmethod
    def parse_new(cls, raw: str) -> ProfileId:
        # Windows rejects or silently aliases some names. New names avoid them on
        # every platform so that profiles can move between systems.
        profile_id = cls(raw)
        _raise_if_problem(_windows_problem(raw) or _superpaper_conventions_problem(raw))
        return profile_id

    @property
    def collision_key(self) -> str:
        return collision_key(self.value)


def collision_key(name: str) -> str:
    """Return the key under which two names denote one file on a case-insensitive filesystem."""
    return unicodedata.normalize("NFC", name).casefold()


def _raise_if_problem(problem: str | None) -> None:
    if problem is not None:
        raise ProfileIdError(problem)


def _path_safety_problem(raw: str) -> str | None:
    """Why ``raw`` isn't a single safe path component that survives the profile's
    "name=" line and doesn't shadow an entry of the UI, or None."""
    if not raw:
        return "Profile names cannot be empty."
    if "\0" in raw:
        return "Profile names cannot contain NUL characters."
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in raw):
        return "Profile names cannot contain control characters."
    if raw in {".", ".."}:
        return "Profile names cannot be '.' or '..'."
    if Path(raw).is_absolute() or PureWindowsPath(raw).is_absolute():
        return "Profile names cannot be absolute paths."
    if "/" in raw or "\\" in raw:
        return "Profile names cannot contain path separators."
    if raw.casefold() in _RESERVED_APPLICATION_NAMES:
        return f"'{raw}' is reserved by Superpaper."
    return None


def _windows_problem(raw: str) -> str | None:
    if raw != raw.strip():
        return "Profile names cannot start or end with whitespace."
    invalid = sorted(set(raw) & _WINDOWS_INVALID_CHARACTERS)
    if invalid:
        return f"Profile names cannot contain: {''.join(invalid)}"
    if raw.endswith("."):
        return "Profile names cannot end with a period."
    device_stem = raw.split(".", 1)[0].rstrip(" .").casefold()
    if device_stem in _WINDOWS_DEVICES:
        return f"'{raw}' is reserved by Windows."
    return None


def _superpaper_conventions_problem(raw: str) -> str | None:
    if unicodedata.normalize("NFC", raw) != raw:
        return "Profile names must use Unicode NFC normalization."
    if len(raw) > _MAX_PROFILE_NAME_CHARS:
        return f"Profile names cannot exceed {_MAX_PROFILE_NAME_CHARS} characters."
    if "=" in raw:
        # Older versions split the "name=" line at every "=" and would truncate it.
        return "Profile names cannot contain: ="
    return None


class ManagedPathError(ValueError):
    """A managed profile path escaped its root or is not a regular file."""


def profile_path(root: Path, profile_id: ProfileId) -> Path:
    """The path of a profile's file in ``root``, which must be a regular file if it exists.
    A symlinked file is accepted: dotfile managers link profiles into place."""
    path = root.resolve() / f"{profile_id.value}.profile"
    if path.exists() and not path.is_file():
        message = f"Managed profile paths must be regular files: {path}"
        raise ManagedPathError(message)
    return path


def existing_profile_path(root: Path, profile_id: ProfileId) -> Path:
    """The path of a profile's file in ``root``, which must exist as a regular file."""
    path = root.resolve() / f"{profile_id.value}.profile"
    if not path.is_file():
        message = f"Managed profile file does not exist: {path}"
        raise ManagedPathError(message)
    return path
