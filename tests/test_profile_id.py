import unicodedata
from pathlib import Path

import pytest

from superpaper.profile_id import (
    ManagedPathError,
    ProfileId,
    ProfileIdError,
    ProfileIdErrorCode,
    assert_managed_leaf,
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
    profile_id = ProfileId.parse(name)

    assert profile_id.value == name
    assert profile_id.profile_filename == f"{name}.profile"


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("", ProfileIdErrorCode.EMPTY),
        (" ", ProfileIdErrorCode.SURROUNDING_WHITESPACE),
        (" Work", ProfileIdErrorCode.SURROUNDING_WHITESPACE),
        ("Work ", ProfileIdErrorCode.SURROUNDING_WHITESPACE),
        (".", ProfileIdErrorCode.DOT_COMPONENT),
        ("..", ProfileIdErrorCode.DOT_COMPONENT),
        ("../outside", ProfileIdErrorCode.SEPARATOR),
        ("folder/name", ProfileIdErrorCode.SEPARATOR),
        (r"folder\name", ProfileIdErrorCode.SEPARATOR),
        ("/absolute", ProfileIdErrorCode.ABSOLUTE),
        (r"C:\absolute", ProfileIdErrorCode.ABSOLUTE),
        ("name\0suffix", ProfileIdErrorCode.NUL),
        ("name\n", ProfileIdErrorCode.CONTROL),
        ("name\0 ", ProfileIdErrorCode.NUL),
        ("name\tvalue", ProfileIdErrorCode.CONTROL),
        ("name\ud800value", ProfileIdErrorCode.CONTROL),
        ("bad=name", ProfileIdErrorCode.INVALID_CHARACTER),
        ("bad:name", ProfileIdErrorCode.INVALID_CHARACTER),
        ("trailing.", ProfileIdErrorCode.TRAILING_DOT),
        ("CON", ProfileIdErrorCode.RESERVED_NAME),
        ("con.notes", ProfileIdErrorCode.RESERVED_NAME),
        ("CON .txt", ProfileIdErrorCode.RESERVED_NAME),
        ("CoNin$", ProfileIdErrorCode.RESERVED_NAME),
        ("CONOUT$.txt", ProfileIdErrorCode.RESERVED_NAME),
        ("LPT9", ProfileIdErrorCode.RESERVED_NAME),
        ("LPT1 .foo", ProfileIdErrorCode.RESERVED_NAME),
        ("COM¹.log", ProfileIdErrorCode.RESERVED_NAME),
        ("cli", ProfileIdErrorCode.RESERVED_APPLICATION_NAME),
        ("Create a new profile", ProfileIdErrorCode.RESERVED_APPLICATION_NAME),
    ],
)
def test_profile_id_rejects_unsafe_names(name, code):
    with pytest.raises(ProfileIdError) as error:
        ProfileId.parse(name)

    assert error.value.code is code
    assert error.value.raw == name


@pytest.mark.parametrize(
    "name",
    [
        "a" * 200,
        "é" * 100,
        "😀" * 50,
    ],
)
def test_profile_id_accepts_exact_length_boundaries(name):
    assert ProfileId.parse(name).value == name


@pytest.mark.parametrize(
    "name",
    [
        "a" * 201,
        "é" * 101,
        "😀" * 51,
    ],
)
def test_profile_id_rejects_names_over_length_boundaries(name):
    with pytest.raises(ProfileIdError) as error:
        ProfileId.parse(name)

    assert error.value.code is ProfileIdErrorCode.TOO_LONG


def test_profile_id_reports_normalized_suggestion():
    decomposed = unicodedata.normalize("NFD", "Café")

    with pytest.raises(ProfileIdError) as error:
        ProfileId.parse(decomposed)

    assert error.value.code is ProfileIdErrorCode.NOT_NFC
    assert error.value.suggested == "Café"


@pytest.mark.parametrize("factory", [ProfileId, ProfileId.parse])
def test_profile_id_public_construction_validates(factory):
    with pytest.raises(ProfileIdError) as error:
        factory("../outside")

    assert error.value.code is ProfileIdErrorCode.SEPARATOR


@pytest.mark.parametrize("raw", [None, 42, b"Work"])
def test_profile_id_rejects_non_strings(raw):
    with pytest.raises(ProfileIdError) as error:
        ProfileId.parse(raw)

    assert error.value.code is ProfileIdErrorCode.NOT_STRING
    assert error.value.raw is raw


def test_collision_key_is_case_insensitive():
    assert ProfileId.parse("Work").collision_key == ProfileId.parse("work").collision_key


def test_collision_key_uses_unicode_casefold():
    assert ProfileId.parse("Straße").collision_key == ProfileId.parse("STRASSE").collision_key


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
        assert_managed_leaf(root, outside, allow_missing=True)


@pytest.mark.parametrize("relative", [Path("nested/file.profile"), Path("nested/../file.profile"), Path("..")])
def test_managed_leaf_rejects_non_direct_or_dot_paths(tmp_path, relative):
    root = tmp_path / "profiles"
    root.mkdir()

    with pytest.raises(ManagedPathError, match="not a direct leaf"):
        assert_managed_leaf(root, root / relative, allow_missing=True)


def test_managed_leaf_rejects_symlink(tmp_path):
    root = tmp_path / "profiles"
    root.mkdir()
    outside = tmp_path / "outside.profile"
    outside.write_text("sentinel", encoding="utf-8")
    link = root / "linked.profile"
    link.symlink_to(outside)

    with pytest.raises(ManagedPathError, match="symbolic links"):
        assert_managed_leaf(root, link, allow_missing=False)

    assert outside.read_text(encoding="utf-8") == "sentinel"


def test_managed_leaf_allow_missing_accepts_missing_or_regular_file(tmp_path):
    path = tmp_path / "managed.profile"

    assert assert_managed_leaf(tmp_path, path, allow_missing=True) == path
    path.write_text("profile", encoding="utf-8")
    assert assert_managed_leaf(tmp_path, path, allow_missing=True) == path


def test_managed_leaf_allow_missing_rejects_directory(tmp_path):
    path = tmp_path / "managed.profile"
    path.mkdir()

    with pytest.raises(ManagedPathError, match="must be regular files"):
        assert_managed_leaf(tmp_path, path, allow_missing=True)


def test_profile_path_requires_existing_regular_file(tmp_path):
    profile_id = ProfileId.parse("missing")

    with pytest.raises(ManagedPathError, match="does not exist"):
        profile_path(Path(tmp_path), profile_id, allow_missing=False)
