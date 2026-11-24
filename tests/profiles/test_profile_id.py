import unicodedata
from pathlib import Path

import pytest

from superpaper.profiles.profile_id import (
    NEW_PROFILE_LABEL,
    ManagedPathError,
    ProfileId,
    ProfileIdError,
    existing_profile_path,
    profile_path,
)


@pytest.mark.parametrize(
    "name",
    [
        "Work",
        "Project Alpha",
        ".private",
        "work.v2",
        "saved.profile",
        "日本語",
        "Café",
        "alpha-beta_2",
        "format\u200dcontrol",
        "a" * 50,
        "é" * 50,
        "😀" * 50,
    ],
)
def test_profile_id_accepts_portable_names(name):
    profile_id = ProfileId.parse_new(name)

    assert profile_id.value == name


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "cannot be empty"),
        (".", "cannot be '.' or '..'"),
        ("..", "cannot be '.' or '..'"),
        ("../outside", "path separators"),
        ("folder/name", "path separators"),
        (r"folder\name", "path separators"),
        ("/absolute", "absolute paths"),
        (r"C:\absolute", "absolute paths"),
        ("name\0suffix", "NUL"),
        ("name\n", "control characters"),
        ("name\0 ", "NUL"),
        ("name\tvalue", "control characters"),
        ("name\ud800value", "control characters"),
        ("cli", "reserved by Superpaper"),
        ("Create a new profile", "reserved by Superpaper"),
    ],
)
def test_profile_id_rejects_unsafe_names(name, message):
    with pytest.raises(ProfileIdError, match=message):
        ProfileId.parse(name, windows_names=False)


def test_direct_construction_validates_path_safety():
    with pytest.raises(ProfileIdError, match="path separators"):
        ProfileId("../outside")


def test_the_new_profile_entry_is_not_a_profile_name():
    with pytest.raises(ProfileIdError, match="reserved by Superpaper"):
        ProfileId.parse(NEW_PROFILE_LABEL.upper(), windows_names=False)


NON_PORTABLE_NAMES = [
    (" ", "whitespace"),
    (" Work", "whitespace"),
    ("Work ", "whitespace"),
    ("bad=name", "cannot contain: ="),
    ("bad:name", "cannot contain: :"),
    ("trailing.", "period"),
    ("CON", "reserved by Windows"),
    ("con.notes", "reserved by Windows"),
    ("CON .txt", "reserved by Windows"),
    ("CoNin$", "reserved by Windows"),
    ("CONOUT$.txt", "reserved by Windows"),
    ("LPT9", "reserved by Windows"),
    ("LPT1 .foo", "reserved by Windows"),
    ("COM¹.log", "reserved by Windows"),
    ("a" * 51, "cannot exceed 50 characters"),
    ("é" * 51, "cannot exceed 50 characters"),
    ("😀" * 51, "cannot exceed 50 characters"),
]


@pytest.mark.parametrize(("name", "message"), NON_PORTABLE_NAMES)
def test_new_profile_names_must_be_portable(name, message):
    with pytest.raises(ProfileIdError, match=message):
        ProfileId.parse_new(name)


@pytest.mark.parametrize("name", ["bad:name", "CON", "trailing."])
def test_windows_names_apply_to_existing_profiles_when_asked(name):
    with pytest.raises(ProfileIdError):
        ProfileId.parse(name, windows_names=True)


@pytest.mark.parametrize(("name", "_message"), NON_PORTABLE_NAMES)
def test_existing_non_portable_names_still_identify_profiles(name, _message):
    assert ProfileId.parse(name, windows_names=False).value == name


def test_new_profile_name_must_be_nfc():
    decomposed = unicodedata.normalize("NFD", "Café")

    with pytest.raises(ProfileIdError, match="NFC"):
        ProfileId.parse_new(decomposed)
    # macOS HFS+ hands out decomposed filenames, so an existing file must still load.
    assert ProfileId.parse(decomposed, windows_names=False).value == decomposed


@pytest.mark.parametrize(
    ("name", "same_as"),
    [
        ("Work", "work"),
        ("Straße", "STRASSE"),
        (unicodedata.normalize("NFD", "Café"), "café"),
    ],
    ids=["case", "casefold", "normalization"],
)
def test_names_of_one_file_on_a_case_insensitive_filesystem_share_a_collision_key(name, same_as):
    assert (
        ProfileId.parse(name, windows_names=False).collision_key
        == ProfileId.parse(same_as, windows_names=False).collision_key
    )


def test_profile_path_is_directly_contained(tmp_path):
    profile_id = ProfileId.parse("Work", windows_names=False)

    assert profile_path(tmp_path, profile_id) == tmp_path.resolve() / "Work.profile"


def test_profile_path_accepts_relative_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = Path("profiles")
    root.mkdir()

    assert profile_path(root, ProfileId.parse("Work", windows_names=False)) == root.resolve() / "Work.profile"


def test_profile_path_accepts_symlinked_profile(tmp_path):
    root = tmp_path / "profiles"
    root.mkdir()
    dotfile = tmp_path / "dotfiles" / "linked.profile"
    dotfile.parent.mkdir()
    dotfile.write_text("name=linked\n", encoding="utf-8")
    (root / "linked.profile").symlink_to(dotfile)

    assert (
        existing_profile_path(root, ProfileId.parse("linked", windows_names=False)) == root.resolve() / "linked.profile"
    )


def test_profile_path_allow_missing_accepts_missing_or_regular_file(tmp_path):
    path = tmp_path.resolve() / "managed.profile"

    assert profile_path(tmp_path, ProfileId.parse("managed", windows_names=False)) == path
    path.write_text("profile", encoding="utf-8")
    assert profile_path(tmp_path, ProfileId.parse("managed", windows_names=False)) == path


def test_profile_path_allow_missing_rejects_directory(tmp_path):
    (tmp_path / "managed.profile").mkdir()

    with pytest.raises(ManagedPathError, match="must be regular files"):
        profile_path(tmp_path, ProfileId.parse("managed", windows_names=False))


def test_profile_path_requires_existing_regular_file(tmp_path):
    profile_id = ProfileId.parse("missing", windows_names=False)

    with pytest.raises(ManagedPathError, match="does not exist"):
        existing_profile_path(Path(tmp_path), profile_id)
