"""The profiles directory: which profiles load, which can't and why, saving, renaming and
deleting them without losing edits made elsewhere, and the pointer to the running profile."""

import os
import sys
import unicodedata
from pathlib import Path

import pytest

from superpaper.profiles import profile_store, selection
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId, ProfileIdError
from superpaper.profiles.profile_store import ProfileDiagnosticKind, ProfileStore
from tests.conftest import load_profile, write_profile


def profile_bytes(name, extra=b""):
    return f"name={name}\nspanmode=single\nslideshow=false\n".encode() + extra


def loaded(app_paths):
    """The profiles that load, as the tray finds them."""
    store = ProfileStore(app_paths)
    store.reload()
    return store.profiles


def edited(name, **settings):
    """The settings the editor saves."""
    return Profile(name=name, slideshow=False, sources=(("source",),), **settings)


def stored_profile(app_paths, name, extra=""):
    path = app_paths.profiles / f"{name}.profile"
    path.write_text(f"name={name}\nspanmode=single\nslideshow=false\n{extra}", "utf-8")
    return load_profile(app_paths, name)


def save_over(app_paths, current, profile, **kwargs):
    """Save ``profile`` the way the editor does after opening ``current``."""
    return ProfileStore(app_paths).save(profile, current=current, **kwargs).path


def save_new(app_paths, profile):
    return ProfileStore(app_paths).save(profile).path


def prepare_profile(app_paths, tmp_path):
    image = tmp_path / "wallpaper.png"
    image.touch()
    write_profile(app_paths.profiles / "test.profile", sources=[image])
    return app_paths.cache


def running(app_paths):
    """The profile the tray starts with, as it finds it."""
    store = ProfileStore(app_paths)
    store.reload()
    return store.active()


def test_discovery_returns_valid_profiles_in_filename_order(app_paths):
    profiles = app_paths.profiles
    (profiles / "Zulu.profile").write_bytes(profile_bytes("Zulu"))
    (profiles / "Alpha.profile").write_bytes(profile_bytes("Alpha"))
    (profiles / "nested").mkdir()
    (profiles / "nested" / "Hidden.profile").write_bytes(profile_bytes("Hidden"))

    inventory = profile_store.discover(app_paths)

    assert [entry.profile_id.value for entry in inventory.entries] == ["Alpha", "Zulu"]
    assert [stored.profile_id for stored in loaded(app_paths)] == [ProfileId("Alpha"), ProfileId("Zulu")]


def test_a_filename_that_is_not_a_profile_name_is_diagnosed_and_left_alone(app_paths):
    path = app_paths.profiles / "cli.profile"
    original = profile_bytes("cli")
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
    ProfileStore(app_paths).delete(stored)
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
        ProfileStore(app_paths).delete(stored)

    assert path.read_bytes() == replacement


def test_deleting_a_symlinked_profile_removes_only_the_link(app_paths, tmp_path):
    dotfile = tmp_path / "dotfiles" / "Work.profile"
    dotfile.parent.mkdir()
    dotfile.write_bytes(profile_bytes("Work"))
    link = app_paths.profiles / "Work.profile"
    link.symlink_to(dotfile)

    ProfileStore(app_paths).delete(load_profile(app_paths, "Work"))

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


def test_a_value_that_cant_be_used_makes_a_profile_malformed(app_paths):
    path = app_paths.profiles / "broken.profile"
    original = profile_bytes("broken", b"delay=soon\n")
    path.write_bytes(original)

    store = ProfileStore(app_paths)
    (diagnostic,) = store.reload()

    assert store.profiles == []
    assert diagnostic.kind is ProfileDiagnosticKind.MALFORMED_CONTENT
    assert path.read_bytes() == original


def test_a_profile_earlier_versions_loaded_still_loads(app_paths):
    (app_paths.profiles / "lenient.profile").write_bytes(profile_bytes("lenient", b"zoom=\n"))

    assert [stored.profile_id.value for stored in loaded(app_paths)] == ["lenient"]


@pytest.mark.parametrize(("replaced_meanwhile", "deleted"), [(False, True), (True, False)])
def test_a_malformed_profile_is_deleted_only_as_it_was_diagnosed(app_paths, replaced_meanwhile, deleted):
    path = app_paths.profiles / "broken.profile"
    path.write_bytes(profile_bytes("broken", b"delay=not-a-number\n"))
    (diagnostic,) = ProfileStore(app_paths).reload()
    replacement = profile_bytes("broken", b"hotkey=control+x\n")
    if replaced_meanwhile:
        path.write_bytes(replacement)

    assert profile_store.delete_malformed(diagnostic) is deleted
    assert path.exists() is not deleted
    if replaced_meanwhile:
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


def test_sweep_forgets_selections_of_profiles_that_are_gone(app_paths):
    (app_paths.profiles / "Work.profile").write_text("name=Work\n", encoding="utf-8")
    selections = app_paths.cache / "selections"
    selections.mkdir()
    for name in ("Work.json", "Gone.json", "notes.txt"):
        (selections / name).write_text("[]", encoding="utf-8")

    ProfileStore(app_paths).sweep()

    assert sorted(path.name for path in selections.iterdir()) == ["Work.json", "notes.txt"]


def test_loading_a_profile_leaves_its_file_alone(app_paths, tmp_path):
    image = tmp_path / "wallpaper.png"
    image.touch()
    profile_path = app_paths.profiles / "noise.profile"
    raw = f"name=noise\r\nspanmode=single\r\ndisplay0paths={image}"
    profile_path.write_bytes(raw.encode())

    stored = load_profile(app_paths, "noise")
    stored.selection.advance()

    assert stored.profile.sources == ((str(image),),)
    assert profile_path.read_bytes() == raw.encode()


def test_source_paths_may_contain_equals_signs(app_paths, tmp_path):
    folder = tmp_path / "a=b"
    folder.mkdir()
    image = folder / "wallpaper.png"
    image.touch()

    write_profile(app_paths.profiles / "test.profile", sources=[folder])
    stored = load_profile(app_paths, "test")

    assert stored.profile.sources == ((str(folder),),)
    assert stored.selection.current() == [str(image)]


def test_loading_profiles_lists_no_sources(app_paths, tmp_path, monkeypatch):
    sources = tmp_path / "wallpapers"
    sources.mkdir()
    (sources / "a.png").touch()
    for name in ("one", "two"):
        write_profile(app_paths.profiles / f"{name}.profile", sources=[sources])
    listed = []
    real_listdir = selection.os.listdir
    monkeypatch.setattr(selection.os, "listdir", lambda path: listed.append(path) or real_listdir(path))

    store = ProfileStore(app_paths)
    store.reload()
    profiles = store.profiles

    assert [stored.profile.name for stored in profiles] == ["one", "two"]
    assert listed == []
    assert profiles[0].selection.current() == [str(sources / "a.png")]
    assert listed == [str(sources)]


def test_active_profile_round_trip(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)

    profile_store.write_active_profile(app_paths.cache, ProfileId("test"))

    assert (cache / "running_profile").read_text(encoding="utf-8") == "test"
    assert running(app_paths).profile.name == "test"


@pytest.mark.parametrize("content", [b"test\n", b"test\r\n", b"test\nmissing\n"])
def test_the_pointer_names_the_first_line(app_paths, tmp_path, content):
    cache = prepare_profile(app_paths, tmp_path)
    (cache / "running_profile").write_bytes(content)

    assert profile_store.read_active_profile_id(cache) == ProfileId("test")
    assert running(app_paths).profile.name == "test"


def test_empty_active_profile_returns_none(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)
    (cache / "running_profile").touch()

    assert profile_store.read_active_profile_id(cache) is None
    assert running(app_paths) is None


def test_missing_pointer_reads_as_none_without_creating_it(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)

    assert running(app_paths) is None
    assert not (cache / "running_profile").exists()


def test_invalid_active_profile_pointer_is_rejected_without_rewrite(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)
    pointer = cache / "running_profile"
    original = b"../test\n"
    pointer.write_bytes(original)

    assert running(app_paths) is None
    assert pointer.read_bytes() == original


def test_a_pointer_to_a_deleted_profile_is_none(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)
    (cache / "running_profile").write_text("deleted", encoding="utf-8")

    assert profile_store.read_active_profile_id(cache) == ProfileId("deleted")
    assert running(app_paths) is None


def test_pointer_resolves_a_profile_whose_name_line_differs(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)
    pointer = cache / "running_profile"
    pointer.write_text("test", encoding="utf-8")
    (app_paths.profiles / "test.profile").write_text("name=other\n", encoding="utf-8")

    assert running(app_paths).profile.name == "test"
    assert pointer.read_text(encoding="utf-8") == "test"


def test_pointer_resolves_a_symlinked_profile(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)
    profiles = app_paths.profiles
    target = tmp_path / "target.profile"
    target.write_bytes((profiles / "test.profile").read_bytes())
    (profiles / "test.profile").unlink()
    (profiles / "test.profile").symlink_to(target)
    (cache / "running_profile").write_text("test", encoding="utf-8")

    assert running(app_paths).profile.name == "test"


def test_invalid_active_profile_write_does_not_touch_pointer(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)
    pointer = cache / "running_profile"
    pointer.write_text("test", encoding="utf-8")

    with pytest.raises(ProfileIdError):
        profile_store.write_active_profile(app_paths.cache, ProfileId("../other"))

    assert pointer.read_text(encoding="utf-8") == "test"


def test_active_profile_write_never_replaces_a_directory(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)
    (cache / "running_profile").mkdir()

    with pytest.raises(OSError):
        profile_store.write_active_profile(app_paths.cache, ProfileId("test"))

    assert (cache / "running_profile").is_dir()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_active_profile_read_does_not_block_on_fifo(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)
    os.mkfifo(cache / "running_profile")

    assert profile_store.read_active_profile_id(cache) is None


def test_a_new_profile_with_an_unusable_name_is_rejected_without_write(app_paths):
    with pytest.raises((ProfileIdError, ValueError)):
        profile_store.validate_managed_profile_id(app_paths.profiles, "../escape")
    with pytest.raises(profile_store.ProfileTransactionError):
        save_new(app_paths, edited("../escape"))
    assert list(app_paths.profiles.iterdir()) == []


def test_new_profile_rejects_portable_collision(app_paths):
    profiles = app_paths.profiles
    existing = profiles / "Work.profile"
    existing.write_text("name=Work\n", encoding="utf-8")

    with pytest.raises(ValueError, match="collides"):
        profile_store.validate_managed_profile_id(profiles, "work")
    with pytest.raises(profile_store.ProfileTransactionError):
        save_new(app_paths, edited("work"))
    assert existing.read_text(encoding="utf-8") == "name=Work\n"
    assert [path.name for path in profiles.iterdir()] == ["Work.profile"]


def test_new_name_collides_with_a_file_that_does_not_load(app_paths):
    broken = app_paths.profiles / "Work.profile"
    broken.write_text("name=Work\ndelay=not-a-number\n", encoding="utf-8")

    with pytest.raises(profile_store.ProfileTransactionError):
        save_new(app_paths, edited("work"))

    assert broken.read_text(encoding="utf-8") == "name=Work\ndelay=not-a-number\n"


def test_case_only_rename_is_rejected(app_paths):
    profiles = app_paths.profiles
    current = stored_profile(app_paths, "Work")
    original = (profiles / "Work.profile").read_bytes()

    with pytest.raises(ValueError, match="collides"):
        profile_store.validate_managed_profile_id(profiles, "work", current.profile_id)
    with pytest.raises(profile_store.ProfileTransactionError):
        save_over(app_paths, current, edited("work"))
    assert (profiles / "Work.profile").read_bytes() == original


@pytest.mark.skipif(sys.platform == "win32", reason="this filename cannot exist on Windows")
def test_resave_keeps_a_name_that_new_profiles_may_not_use(app_paths):
    current = stored_profile(app_paths, "Work: dual")

    assert profile_store.validate_managed_profile_id(app_paths.profiles, "Work: dual", current.profile_id) == (
        current.profile_id
    )
    assert save_over(app_paths, current, edited("Work: dual", hotkey=("control", "x"))) == (
        app_paths.profiles / "Work: dual.profile"
    )
    assert load_profile(app_paths, "Work: dual").profile.hotkey == ("control", "x")


def test_create_then_resave(app_paths):
    profiles = app_paths.profiles

    assert save_new(app_paths, edited("Work")) == profiles / "Work.profile"
    current = load_profile(app_paths, "Work")
    assert save_over(app_paths, current, edited("Work", hotkey=("control", "x"))) == profiles / "Work.profile"
    assert load_profile(app_paths, "Work").profile.hotkey == ("control", "x")


def test_saving_a_symlinked_profile_writes_through_to_its_target(app_paths, tmp_path):
    dotfile = tmp_path / "dotfiles" / "Work.profile"
    dotfile.parent.mkdir()
    dotfile.write_text("name=Work\nspanmode=single\nslideshow=false\n", encoding="utf-8")
    link = app_paths.profiles / "Work.profile"
    link.symlink_to(dotfile)
    current = load_profile(app_paths, "Work")

    save_over(app_paths, current, edited("Work", hotkey=("control", "x")))

    assert link.is_symlink()
    assert "hotkey=control+x" in dotfile.read_text(encoding="utf-8")


def test_directory_named_like_a_profile_is_never_replaced(app_paths):
    (app_paths.profiles / "Work.profile").mkdir()

    with pytest.raises(profile_store.ProfileTransactionError):
        save_new(app_paths, edited("Work"))

    assert (app_paths.profiles / "Work.profile").is_dir()


def test_rename_rolls_back_destination_when_source_delete_fails(app_paths, monkeypatch):
    profiles = app_paths.profiles
    current = stored_profile(app_paths, "Work")
    source_path = profiles / "Work.profile"
    real_unlink = Path.unlink

    def fail_source_unlink(path, *args, **kwargs):
        if path == source_path:
            message = "injected source deletion failure"
            raise PermissionError(message)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_source_unlink)

    with pytest.raises(profile_store.ProfileTransactionError) as error:
        save_over(app_paths, current, edited("Renamed"))

    assert error.value.stage == "source removal"
    assert source_path.exists()
    assert not (profiles / "Renamed.profile").exists()


def test_save_rejects_a_profile_changed_after_the_editor_loaded_it(app_paths):
    current = stored_profile(app_paths, "Work")
    source_path = app_paths.profiles / "Work.profile"
    replacement = b"name=Work\nspanmode=single\nslideshow=false\nhotkey=control+x\n"
    source_path.write_bytes(replacement)

    with pytest.raises(profile_store.ProfileTransactionError) as error:
        save_over(app_paths, current, edited("Work"))

    assert error.value.stage == "source verification"
    assert str(error.value) == (
        "Profile save failed during source verification: 'Work' was changed outside the editor after it was "
        "opened. Revert to load the current version, then make your changes again."
    )
    assert source_path.read_bytes() == replacement


def test_rename_restores_source_and_destination_on_pointer_failure(app_paths, monkeypatch):
    current = stored_profile(app_paths, "Work")
    source_path = app_paths.profiles / "Work.profile"
    original = source_path.read_bytes()

    def fail_pointer(_cache_dir, _profile):
        message = "injected pointer failure"
        raise PermissionError(message)

    monkeypatch.setattr(profile_store, "write_active_profile", fail_pointer)

    with pytest.raises(profile_store.ProfileTransactionError) as error:
        save_over(app_paths, current, edited("Renamed"), update_active=True)

    assert error.value.stage == "active pointer update"
    assert source_path.read_bytes() == original
    assert not (app_paths.profiles / "Renamed.profile").exists()


def test_save_after_apply_succeeds(app_paths, tmp_path):
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.touch()
    second.touch()
    current = stored_profile(app_paths, "Work", f"display0paths={tmp_path}\nselected={first}\n")
    current.selection.pin([str(second)])  # what Apply does

    save_over(app_paths, current, edited("Work", hotkey=("control", "x")), selected=[str(second)])

    reloaded = load_profile(app_paths, "Work")
    assert reloaded.profile.hotkey == ("control", "x")
    assert reloaded.selection.images == [str(second)]


def test_save_after_a_slideshow_tick_succeeds(app_paths, tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "a.png").touch()
    (images / "b.png").touch()
    current = stored_profile(app_paths, "Work", f"sortmode=alphabetical\ndisplay0paths={images}\n")
    current.selection.advance()  # what a slideshow tick does while the editor is open

    save_over(app_paths, current, edited("Work"))

    assert load_profile(app_paths, "Work").selection.images == [str(images / "a.png")]


def test_save_carries_over_a_selection_from_an_older_version(app_paths, tmp_path):
    image = tmp_path / "chosen.png"
    image.touch()
    current = stored_profile(app_paths, "Work", f"selected={image}\n")

    save_over(app_paths, current, edited("Work"))

    assert "selected=" not in (app_paths.profiles / "Work.profile").read_text(encoding="utf-8")
    assert load_profile(app_paths, "Work").selection.images == [str(image)]


def test_remembering_a_selection_leaves_the_profile_file_alone(app_paths, tmp_path):
    image = tmp_path / "wallpaper.png"
    image.touch()
    current = stored_profile(app_paths, "Work", "display0paths=source\ncustom=value\n")
    original = (app_paths.profiles / "Work.profile").read_bytes()

    current.selection.pin([str(image)])

    assert (app_paths.profiles / "Work.profile").read_bytes() == original
    assert load_profile(app_paths, "Work").selection.images == [str(image)]


def test_rename_moves_the_selection_and_delete_forgets_it(app_paths, tmp_path):
    image = tmp_path / "wallpaper.png"
    image.touch()
    current = stored_profile(app_paths, "Work")
    current.selection.pin([str(image)])

    save_over(app_paths, current, edited("Renamed"))
    renamed = load_profile(app_paths, "Renamed")
    ProfileStore(app_paths).delete(renamed)
    recreated = stored_profile(app_paths, "Renamed")

    assert renamed.selection.images == [str(image)]
    assert recreated.selection.images is None


def test_the_store_saves_and_hands_out_one_record_per_profile(app_paths):
    store = ProfileStore(app_paths)
    store.reload()

    saved = store.save(edited("Work"))
    assert store.get(ProfileId("Work")) is saved
    assert store.profiles == [saved]

    renamed = store.save(edited("Home", hotkey=("alt", "h")), current=saved)
    assert [stored.profile_id.value for stored in store.profiles] == ["Home"]
    assert store.get(ProfileId("Home")) is renamed
    assert renamed.profile.hotkey == ("alt", "h")

    store.delete(renamed)
    assert store.profiles == []
    assert list(app_paths.profiles.iterdir()) == []


def test_reloading_keeps_the_record_of_an_unchanged_profile(app_paths, tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    for name in ("a.png", "b.png", "c.png"):
        (images / name).touch()
    stored_profile(app_paths, "Work", f"sortmode=alphabetical\ndisplay0paths={images}\n")
    stored_profile(app_paths, "Home")
    store = ProfileStore(app_paths)
    store.reload()
    work = store.get(ProfileId("Work"))
    work.selection.advance()

    (app_paths.profiles / "Home.profile").write_text("name=Home\nhotkey=alt+h\n", encoding="utf-8")
    store.reload()

    # Work's slideshow goes on where it was; Home is loaded again, with its change.
    assert store.get(ProfileId("Work")) is work
    assert work.selection.advance() == [str(images / "b.png")]
    assert store.get(ProfileId("Home")).profile.hotkey == ("alt", "h")
