"""Finding the profiles in the profiles directory: which load, which can't and why, and
deleting them."""

import os
import sys
import unicodedata

import pytest

from superpaper import profile_store
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.profile_store import ProfileDiagnosticKind, ProfileStore
from tests.conftest import load_profile


def profile_bytes(name, extra=b""):
    return f"name={name}\nspanmode=single\nslideshow=false\n".encode() + extra


def loaded(app_paths):
    """The profiles that load, as the tray finds them."""
    store = ProfileStore(app_paths)
    store.reload()
    return store.profiles


def test_discovery_returns_valid_profiles_in_filename_order(app_paths):
    profiles = app_paths.profiles
    (profiles / "Zulu.profile").write_bytes(profile_bytes("Zulu"))
    (profiles / "Alpha.profile").write_bytes(profile_bytes("Alpha"))
    (profiles / "nested").mkdir()
    (profiles / "nested" / "Hidden.profile").write_bytes(profile_bytes("Hidden"))

    inventory = profile_store.discover(app_paths)

    assert [entry.profile_id.value for entry in inventory.entries] == ["Alpha", "Zulu"]
    assert [stored.profile_id for stored in loaded(app_paths)] == [ProfileId("Alpha"), ProfileId("Zulu")]


@pytest.mark.parametrize("stem", ["back\\slash", "bell\x07", "cli", "Create a new profile"])
def test_unsafe_filenames_are_diagnosed_and_left_alone(app_paths, stem):
    path = app_paths.profiles / f"{stem}.profile"
    original = profile_bytes(stem)
    path.write_bytes(original)

    store = ProfileStore(app_paths)
    diagnostics = store.reload()

    assert store.profiles == []
    assert [diagnostic.kind for diagnostic in diagnostics] == [ProfileDiagnosticKind.INVALID_FILENAME]
    assert path.read_bytes() == original


@pytest.mark.skipif(sys.platform == "win32", reason="these filenames cannot exist on Windows")
@pytest.mark.parametrize(
    ("stem", "name_line"),
    [
        ("bad=name", "bad=name"),
        ("Work: dual", "Work: dual"),
        ("saved", "renamed by hand"),
        ("Work", "work"),
    ],
)
def test_profiles_saved_by_older_versions_keep_loading(app_paths, stem, name_line):
    path = app_paths.profiles / f"{stem}.profile"
    original = profile_bytes(name_line)
    path.write_bytes(original)

    (stored,) = loaded(app_paths)

    assert stored.profile_id == ProfileId(stem)
    assert stored.profile.name == stem
    assert path.read_bytes() == original


def test_case_variant_profiles_both_load(app_paths):
    profiles = app_paths.profiles
    (profiles / "Work.profile").write_bytes(profile_bytes("Work"))
    (profiles / "work.profile").write_bytes(profile_bytes("work"))
    if len(list(profiles.iterdir())) == 1:
        pytest.skip("the filesystem is case-insensitive")

    inventory = profile_store.discover(app_paths)

    assert [entry.profile_id.value for entry in inventory.entries] == ["Work", "work"]
    assert load_profile(app_paths, "Work").profile.name == "Work"
    assert load_profile(app_paths, "work").profile.name == "work"


@pytest.mark.parametrize("outside", [False, True])
def test_symlinked_profiles_load(app_paths, tmp_path, outside):
    target = (tmp_path if outside else app_paths.profiles) / "target"
    target.write_bytes(profile_bytes("linked"))
    (app_paths.profiles / "linked.profile").symlink_to(target)

    inventory = profile_store.discover(app_paths)

    assert [entry.profile_id.value for entry in inventory.entries] == ["linked"]
    assert load_profile(app_paths, "linked").profile_id == ProfileId("linked")


def test_broken_symlink_is_a_diagnostic(app_paths, tmp_path):
    (app_paths.profiles / "gone.profile").symlink_to(tmp_path / "missing")

    inventory = profile_store.discover(app_paths)

    assert inventory.entries == ()
    assert [diagnostic.kind for diagnostic in inventory.diagnostics] == [ProfileDiagnosticKind.NOT_REGULAR_FILE]


def test_unicode_names_load_by_their_own_form(app_paths):
    composed = unicodedata.normalize("NFC", "Työ")
    decomposed = unicodedata.normalize("NFD", "Työ")
    (app_paths.profiles / f"{composed}.profile").write_bytes(profile_bytes(composed))
    if composed != decomposed:
        (app_paths.profiles / f"{decomposed}.profile").write_bytes(profile_bytes(decomposed))

    names = [stored.profile.name for stored in loaded(app_paths)]

    assert composed in names
    assert decomposed in names
    assert load_profile(app_paths, ProfileId(composed)).profile_id == ProfileId(composed)


def test_a_name_line_never_becomes_an_identity(app_paths, tmp_path):
    (app_paths.profiles / "Original.profile").write_bytes(profile_bytes("../outside", b"hotkey=control+x\n"))
    outside = tmp_path / "outside.profile"
    outside.write_bytes(b"sentinel")

    (stored,) = loaded(app_paths)

    assert stored.profile_id == ProfileId("Original")
    assert stored.profile.hotkey == ("control", "x")
    with pytest.raises(ProfileIdError):
        ProfileId.parse("../outside")
    profile_store.delete_managed_profile(app_paths, stored)
    assert outside.read_bytes() == b"sentinel"


def test_delete_uses_loaded_content_and_rejects_replacement(app_paths):
    path = app_paths.profiles / "Work.profile"
    original = profile_bytes("Work", b"hotkey=control+x\n")
    replacement = profile_bytes("Work", b"hotkey=control+y\n")
    path.write_bytes(original)
    original_stat = path.stat()
    stored = load_profile(app_paths, "Work")
    path.write_bytes(replacement)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    with pytest.raises(profile_store.ManagedPathError):
        profile_store.delete_managed_profile(app_paths, stored)

    assert path.read_bytes() == replacement


def test_deleting_a_symlinked_profile_removes_only_the_link(app_paths, tmp_path):
    dotfile = tmp_path / "dotfiles" / "Work.profile"
    dotfile.parent.mkdir()
    dotfile.write_bytes(profile_bytes("Work"))
    link = app_paths.profiles / "Work.profile"
    link.symlink_to(dotfile)

    profile_store.delete_managed_profile(app_paths, load_profile(app_paths, "Work"))

    assert not link.is_symlink()
    assert dotfile.read_bytes() == profile_bytes("Work")


def test_deleting_one_profile_leaves_the_others(app_paths):
    profiles = app_paths.profiles
    (profiles / "Work.profile").write_bytes(profile_bytes("Work"))
    (profiles / "Other.profile").write_bytes(profile_bytes("Other"))
    store = ProfileStore(app_paths)
    store.reload()

    store.delete(store.get(ProfileId("Work")))

    assert [path.name for path in profiles.iterdir()] == ["Other.profile"]
    assert [stored.profile_id for stored in store.profiles] == [ProfileId("Other")]


@pytest.mark.parametrize("setting", [b"diagonal_inches=0;24\n", b"delay=soon\n", b"ppi=96.5\n"])
def test_a_value_that_cant_be_used_makes_a_profile_malformed(app_paths, setting):
    path = app_paths.profiles / "broken.profile"
    original = profile_bytes("broken", setting)
    path.write_bytes(original)

    store = ProfileStore(app_paths)
    (diagnostic,) = store.reload()

    assert store.profiles == []
    assert diagnostic.kind is ProfileDiagnosticKind.MALFORMED_CONTENT
    assert path.read_bytes() == original


@pytest.mark.parametrize("setting", [b"zoom=\n", b"align=\n", b"a line without a setting\n", b"name\n"])
def test_a_profile_earlier_versions_loaded_still_loads(app_paths, setting):
    (app_paths.profiles / "lenient.profile").write_bytes(profile_bytes("lenient", setting))

    assert [stored.profile_id.value for stored in loaded(app_paths)] == ["lenient"]


def test_a_malformed_profile_is_deleted_as_it_was_diagnosed(app_paths):
    path = app_paths.profiles / "broken.profile"
    path.write_bytes(profile_bytes("broken", b"delay=not-a-number\n"))
    (diagnostic,) = ProfileStore(app_paths).reload()

    assert profile_store.delete_malformed(diagnostic) is True
    assert not path.exists()


def test_a_malformed_profile_replaced_meanwhile_is_kept(app_paths):
    path = app_paths.profiles / "broken.profile"
    path.write_bytes(profile_bytes("broken", b"delay=not-a-number\n"))
    (diagnostic,) = ProfileStore(app_paths).reload()
    replacement = profile_bytes("broken", b"hotkey=control+x\n")
    path.write_bytes(replacement)

    assert profile_store.delete_malformed(diagnostic) is False
    assert path.read_bytes() == replacement


def test_loading_a_read_only_profile_never_writes(app_paths):
    path = app_paths.profiles / "saved.profile"
    original = profile_bytes("other")
    path.write_bytes(original)
    path.chmod(0o444)

    assert [stored.profile.name for stored in loaded(app_paths)] == ["saved"]
    assert path.read_bytes() == original


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions, not root")
def test_an_unreadable_profile_is_an_io_error_not_malformed(app_paths):
    path = app_paths.profiles / "saved.profile"
    path.write_bytes(profile_bytes("saved"))
    path.chmod(0)

    store = ProfileStore(app_paths)
    diagnostics = store.reload()
    path.chmod(0o644)

    assert store.profiles == []
    assert [diagnostic.kind for diagnostic in diagnostics] == [ProfileDiagnosticKind.IO_ERROR]
    assert path.read_bytes() == profile_bytes("saved")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_fifo_profile_is_diagnostic_without_blocking(app_paths):
    os.mkfifo(app_paths.profiles / "pipe.profile")

    inventory = profile_store.discover(app_paths)

    assert inventory.entries == ()
    assert inventory.diagnostics[0].kind is ProfileDiagnosticKind.NOT_REGULAR_FILE


def test_selections_of_profiles_that_are_gone_are_forgotten(app_paths):
    selections = app_paths.cache / "selections"
    selections.mkdir()
    for name in ("Work.json", "Gone.json", "notes.txt"):
        (selections / name).write_text("[]", encoding="utf-8")

    profile_store.sweep_selections(app_paths.cache, [ProfileId("Work")])

    assert sorted(path.name for path in selections.iterdir()) == ["Work.json", "notes.txt"]
