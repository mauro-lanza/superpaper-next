"""Profile identity: which filenames are profiles, and where their files may live."""

import unicodedata
from dataclasses import InitVar, dataclass, field
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

    raw: InitVar[object]
    windows_names: InitVar[bool]
    _value: str = field(init=False, repr=False)

    def __post_init__(self, raw: object, windows_names: bool) -> None:
        object.__setattr__(self, "_value", _validate_profile_id(raw, new=False, windows_names=windows_names))

    @classmethod
    def parse(cls, raw: object, *, windows_names: bool) -> ProfileId:
        return cls(raw, windows_names)

    @classmethod
    def parse_new(cls, raw: object) -> ProfileId:
        _validate_profile_id(raw, new=True, windows_names=False)
        return cls(raw, windows_names=False)

    @property
    def value(self) -> str:
        return self._value

    @property
    def collision_key(self) -> str:
        return collision_key(self.value)


def collision_key(name: str) -> str:
    """Return the key under which two names denote one file on a case-insensitive filesystem."""
    return unicodedata.normalize("NFC", name).casefold()


def _validate_profile_id(raw: object, *, new: bool, windows_names: bool) -> str:
    if not isinstance(raw, str):
        message = "Profile names must be strings."
        raise ProfileIdError(message)
    problem = _problem(raw, new=new, windows_names=windows_names)
    if problem is not None:
        raise ProfileIdError(problem)
    return raw


def _problem(raw: str, *, new: bool, windows_names: bool) -> str | None:
    """Why ``raw`` can't identify a profile, or None if it can."""
    # Rules for every name, whatever its origin: a single safe path component that
    # survives the profile's "name=" line and doesn't shadow an entry of the UI.
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
    if new or windows_names:
        # Windows rejects or silently aliases these names. New names avoid them on
        # every platform so that profiles can move between systems.
        problem = _windows_problem(raw)
        if problem is not None:
            return problem
    if new:
        return _superpaper_conventions_problem(raw)
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


def profile_path(root: Path, profile_id: ProfileId, *, allow_missing: bool = True) -> Path:
    """The path of a profile's file in ``root``, which must be a regular file if it exists
    (or must exist, unless ``allow_missing``). A symlinked file is accepted: dotfile managers
    link profiles into place."""
    path = root.resolve() / f"{profile_id.value}.profile"
    if allow_missing and path.exists() and not path.is_file():
        message = f"Managed profile paths must be regular files: {path}"
        raise ManagedPathError(message)
    if not allow_missing and not path.is_file():
        message = f"Managed profile file does not exist: {path}"
        raise ManagedPathError(message)
    return path
