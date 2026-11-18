import sys
import unicodedata
from pathlib import Path

import pytest

from superpaper.profiles.profile_id import (
    NEW_PROFILE_LABEL,
    ManagedPathError,
    ProfileId,
    ProfileIdError,
    _assert_managed_leaf,
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
        ProfileId.parse(name)


def test_the_new_profile_entry_is_not_a_profile_name():
    with pytest.raises(ProfileIdError, match="reserved by Superpaper"):
        ProfileId.parse(NEW_PROFILE_LABEL.upper())


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


@pytest.mark.skipif(sys.platform == "win32", reason="Windows enforces its filename rules for every name")
@pytest.mark.parametrize(("name", "_message"), NON_PORTABLE_NAMES)
def test_existing_non_portable_names_still_identify_profiles(name, _message):
    assert ProfileId.parse(name).value == name


@pytest.mark.parametrize(
    "name",
    [
        "a" * 50,
        "é" * 50,
        "😀" * 50,
    ],
)
def test_profile_id_accepts_exact_length_boundaries(name):
    assert ProfileId.parse_new(name).value == name


def test_new_profile_name_must_be_nfc():
    decomposed = unicodedata.normalize("NFD", "Café")

    with pytest.raises(ProfileIdError, match="NFC"):
        ProfileId.parse_new(decomposed)
    # macOS HFS+ hands out decomposed filenames, so an existing file must still load.
    assert ProfileId.parse(decomposed).value == decomposed


@pytest.mark.parametrize("factory", [ProfileId, ProfileId.parse])
def test_profile_id_public_construction_validates(factory):
    with pytest.raises(ProfileIdError, match="path separators"):
        factory("../outside")


@pytest.mark.parametrize("raw", [None, 42, b"Work"])
def test_profile_id_rejects_non_strings(raw):
    with pytest.raises(ProfileIdError, match="must be strings"):
        ProfileId.parse(raw)


def test_collision_key_is_case_insensitive():
    assert ProfileId.parse("Work").collision_key == ProfileId.parse("work").collision_key


def test_collision_key_uses_unicode_casefold():
    assert ProfileId.parse("Straße").collision_key == ProfileId.parse("STRASSE").collision_key


def test_collision_key_ignores_unicode_normalization():
    decomposed = unicodedata.normalize("NFD", "Café")

    assert ProfileId.parse(decomposed).collision_key == ProfileId.parse("café").collision_key


def test_profile_path_is_directly_contained(tmp_path):
    profile_id = ProfileId.parse("Work")

    assert profile_path(tmp_path, profile_id) == tmp_path.resolve() / "Work.profile"


def test_profile_path_accepts_relative_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = Path("profiles")
    root.mkdir()

    assert profile_path(root, ProfileId("Work")) == root.resolve() / "Work.profile"


def test_managed_leaf_rejects_outside_path(tmp_path):
    root = tmp_path / "profiles"
    root.mkdir()
    outside = tmp_path / "outside.profile"

    with pytest.raises(ManagedPathError, match="not a direct leaf"):
        _assert_managed_leaf(root, outside, allow_missing=True)


@pytest.mark.parametrize("relative", [Path("nested/file.profile"), Path("nested/../file.profile"), Path("..")])
def test_managed_leaf_rejects_non_direct_or_dot_paths(tmp_path, relative):
    root = tmp_path / "profiles"
    root.mkdir()

    with pytest.raises(ManagedPathError, match="not a direct leaf"):
        _assert_managed_leaf(root, root / relative, allow_missing=True)


def test_managed_leaf_accepts_symlinked_profile(tmp_path):
    root = tmp_path / "profiles"
    root.mkdir()
    dotfile = tmp_path / "dotfiles" / "linked.profile"
    dotfile.parent.mkdir()
    dotfile.write_text("name=linked\n", encoding="utf-8")
    link = root / "linked.profile"
    link.symlink_to(dotfile)

    assert _assert_managed_leaf(root, link, allow_missing=False) == link


def test_managed_leaf_allow_missing_accepts_missing_or_regular_file(tmp_path):
    path = tmp_path / "managed.profile"

    assert _assert_managed_leaf(tmp_path, path, allow_missing=True) == path
    path.write_text("profile", encoding="utf-8")
    assert _assert_managed_leaf(tmp_path, path, allow_missing=True) == path


def test_managed_leaf_allow_missing_rejects_directory(tmp_path):
    path = tmp_path / "managed.profile"
    path.mkdir()

    with pytest.raises(ManagedPathError, match="must be regular files"):
        _assert_managed_leaf(tmp_path, path, allow_missing=True)


def test_profile_path_requires_existing_regular_file(tmp_path):
    profile_id = ProfileId.parse("missing")

    with pytest.raises(ManagedPathError, match="does not exist"):
        profile_path(Path(tmp_path), profile_id, allow_missing=False)
