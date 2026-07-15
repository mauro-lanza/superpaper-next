"""Portable profile identity and managed profile-path validation."""

import unicodedata
from dataclasses import InitVar, dataclass, field
from enum import Enum, auto
from pathlib import Path, PureWindowsPath


class ProfileIdErrorCode(Enum):
    NOT_STRING = auto()
    EMPTY = auto()
    NOT_NFC = auto()
    ABSOLUTE = auto()
    SEPARATOR = auto()
    DOT_COMPONENT = auto()
    NUL = auto()
    CONTROL = auto()
    TOO_LONG = auto()
    SURROUNDING_WHITESPACE = auto()
    TRAILING_DOT = auto()
    INVALID_CHARACTER = auto()
    RESERVED_NAME = auto()
    RESERVED_APPLICATION_NAME = auto()


class ProfileIdError(ValueError):
    """A profile identifier failed portable validation."""

    def __init__(self, code: ProfileIdErrorCode, raw: object, message: str, suggested: str | None = None):
        super().__init__(message)
        self.code = code
        self.raw = raw
        self.suggested = suggested


_INVALID_CHARACTERS = frozenset('<>:"/\\|?*=')
_MAX_PROFILE_ID_BYTES = 200
_MAX_PROFILE_ID_UTF16_UNITS = 200
_RESERVED_APPLICATION_NAMES = frozenset({"create a new profile", "cli"})
_WINDOWS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
    | {"com¹", "com²", "com³", "lpt¹", "lpt²", "lpt³"}
)


@dataclass(frozen=True, slots=True)
class ProfileId:
    """Validated filename-stem identity for one wallpaper profile."""

    raw: InitVar[object]
    _value: str = field(init=False, repr=False)

    def __post_init__(self, raw: object) -> None:
        object.__setattr__(self, "_value", _validate_profile_id(raw))

    @classmethod
    def parse(cls, raw: object) -> ProfileId:
        return cls(raw)

    @property
    def value(self) -> str:
        return self._value

    @property
    def profile_filename(self) -> str:
        return f"{self.value}.profile"

    @property
    def collision_key(self) -> str:
        """Portable collision key for case-insensitive filesystems."""
        return self.value.casefold()


def _validate_profile_id(raw: object) -> str:
    if not isinstance(raw, str):
        raise ProfileIdError(ProfileIdErrorCode.NOT_STRING, raw, "Profile names must be strings.")
    if not raw:
        raise ProfileIdError(ProfileIdErrorCode.EMPTY, raw, "Profile names cannot be empty.")
    normalized = unicodedata.normalize("NFC", raw)
    if normalized != raw:
        raise ProfileIdError(
            ProfileIdErrorCode.NOT_NFC,
            raw,
            "Profile names must use Unicode NFC normalization.",
            suggested=normalized,
        )
    if "\0" in raw:
        raise ProfileIdError(ProfileIdErrorCode.NUL, raw, "Profile names cannot contain NUL characters.")
    if any(unicodedata.category(char) in {"Cc", "Cs"} for char in raw):
        raise ProfileIdError(ProfileIdErrorCode.CONTROL, raw, "Profile names cannot contain control characters.")
    utf8_length = len(raw.encode("utf-8"))
    utf16_length = len(raw.encode("utf-16-le")) // 2
    if utf8_length > _MAX_PROFILE_ID_BYTES or utf16_length > _MAX_PROFILE_ID_UTF16_UNITS:
        raise ProfileIdError(
            ProfileIdErrorCode.TOO_LONG,
            raw,
            "Profile names cannot exceed 200 UTF-8 bytes or 200 UTF-16 code units.",
        )
    if raw != raw.strip():
        raise ProfileIdError(
            ProfileIdErrorCode.SURROUNDING_WHITESPACE,
            raw,
            "Profile names cannot start or end with whitespace.",
        )
    if raw in {".", ".."}:
        raise ProfileIdError(ProfileIdErrorCode.DOT_COMPONENT, raw, "Profile names cannot be '.' or '..'.")
    if Path(raw).is_absolute() or PureWindowsPath(raw).is_absolute():
        raise ProfileIdError(ProfileIdErrorCode.ABSOLUTE, raw, "Profile names cannot be absolute paths.")
    if "/" in raw or "\\" in raw:
        raise ProfileIdError(ProfileIdErrorCode.SEPARATOR, raw, "Profile names cannot contain path separators.")
    invalid = sorted(set(raw) & _INVALID_CHARACTERS)
    if invalid:
        raise ProfileIdError(
            ProfileIdErrorCode.INVALID_CHARACTER,
            raw,
            f"Profile names cannot contain: {''.join(invalid)}",
        )
    if raw.endswith("."):
        raise ProfileIdError(ProfileIdErrorCode.TRAILING_DOT, raw, "Profile names cannot end with a period.")
    device_stem = raw.split(".", 1)[0].rstrip(" .").casefold()
    if device_stem in _WINDOWS_DEVICES:
        raise ProfileIdError(ProfileIdErrorCode.RESERVED_NAME, raw, f"'{raw}' is reserved by Windows.")
    if raw.casefold() in _RESERVED_APPLICATION_NAMES:
        raise ProfileIdError(
            ProfileIdErrorCode.RESERVED_APPLICATION_NAME,
            raw,
            f"'{raw}' is reserved by Superpaper.",
        )
    return raw


class ManagedPathError(ValueError):
    """A managed profile path escaped its root or addressed a symlink."""


def assert_managed_leaf(root: Path, path: Path, *, allow_missing: bool) -> Path:
    """Validate one non-symlink leaf directly below root.

    This validation cannot prevent the leaf from being replaced between this
    check and a later filesystem operation (TOCTOU); callers must handle that
    race when opening or modifying the returned path.
    """
    if path.parent != root or path.name in {"", ".", ".."} or ".." in path.parts:
        message = f"Managed path is not a direct leaf below profile root: {path}"
        raise ManagedPathError(message)
    resolved_root = root.resolve()
    if path.parent.resolve() != resolved_root:
        message = f"Managed path escapes profile root: {path}"
        raise ManagedPathError(message)
    if path.is_symlink():
        message = f"Managed profile paths cannot be symbolic links: {path}"
        raise ManagedPathError(message)
    if allow_missing and path.exists() and not path.is_file():
        message = f"Managed profile paths must be regular files: {path}"
        raise ManagedPathError(message)
    if not allow_missing and not path.is_file():
        message = f"Managed profile file does not exist: {path}"
        raise ManagedPathError(message)
    return path


def profile_path(root: Path, profile_id: ProfileId, *, allow_missing: bool = True) -> Path:
    """Build a contained profile path for a validated identifier."""
    resolved_root = root.resolve()
    candidate = resolved_root / profile_id.profile_filename
    return assert_managed_leaf(resolved_root, candidate, allow_missing=allow_missing)
