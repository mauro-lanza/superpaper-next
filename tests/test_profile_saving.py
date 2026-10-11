"""Saving a profile from the editor: the names it may have, and saving over, renaming and
deleting it without losing edits made elsewhere or the images it shows."""

import sys
from pathlib import Path

import pytest

from superpaper import profile_store
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.profiles import Profile
from tests.conftest import load_profile


def edited(name, **settings):
    """The settings the editor saves."""
    return Profile(name=name, slideshow=False, sources=(("source",),), **settings)


def stored_profile(app_paths, name, extra=""):
    path = app_paths.profiles / f"{name}.profile"
    path.write_text(f"name={name}\nspanmode=single\nslideshow=false\n{extra}", "utf-8")
    return load_profile(app_paths, name)


def save_over(app_paths, loaded, profile, **kwargs):
    """Save ``profile`` the way the editor does after opening ``loaded``."""
    return profile_store.save_managed_profile(
        app_paths, profile, current_profile_id=loaded.profile_id, expected_source_digest=loaded.digest, **kwargs
    )


@pytest.mark.parametrize("name", ["../escape", "cli", "bad=name", "trailing.", "Work: dual"])
def test_new_profile_with_unusable_name_is_rejected_without_write(app_paths, name):
    with pytest.raises((ProfileIdError, ValueError)):
        profile_store.validate_managed_profile_id(app_paths.profiles, name)
    with pytest.raises(profile_store.ProfileTransactionError):
        profile_store.save_managed_profile(app_paths, edited(name))
    assert list(app_paths.profiles.iterdir()) == []


def test_new_profile_rejects_portable_collision(app_paths):
    profiles = app_paths.profiles
    existing = profiles / "Work.profile"
    existing.write_text("name=Work\n", encoding="utf-8")

    with pytest.raises(ValueError, match="collides"):
        profile_store.validate_managed_profile_id(profiles, "work")
    with pytest.raises(profile_store.ProfileTransactionError):
        profile_store.save_managed_profile(app_paths, edited("work"))
    assert existing.read_text(encoding="utf-8") == "name=Work\n"
    assert [path.name for path in profiles.iterdir()] == ["Work.profile"]


def test_new_name_collides_with_a_file_that_does_not_load(app_paths):
    broken = app_paths.profiles / "Work.profile"
    broken.write_text("name=Work\ndelay=not-a-number\n", encoding="utf-8")

    with pytest.raises(profile_store.ProfileTransactionError):
        profile_store.save_managed_profile(app_paths, edited("work"))

    assert broken.read_text(encoding="utf-8") == "name=Work\ndelay=not-a-number\n"


def test_case_only_rename_is_rejected(app_paths):
    profiles = app_paths.profiles
    loaded = stored_profile(app_paths, "Work")
    original = (profiles / "Work.profile").read_bytes()

    with pytest.raises(ValueError, match="collides"):
        profile_store.validate_managed_profile_id(profiles, "work", loaded.profile_id)
    with pytest.raises(profile_store.ProfileTransactionError):
        save_over(app_paths, loaded, edited("work"))
    assert (profiles / "Work.profile").read_bytes() == original


@pytest.mark.skipif(sys.platform == "win32", reason="this filename cannot exist on Windows")
def test_resave_keeps_a_name_that_new_profiles_may_not_use(app_paths):
    loaded = stored_profile(app_paths, "Work: dual")

    assert profile_store.validate_managed_profile_id(app_paths.profiles, "Work: dual", loaded.profile_id) == (
        loaded.profile_id
    )
    assert save_over(app_paths, loaded, edited("Work: dual", hotkey=("control", "x"))) == (
        app_paths.profiles / "Work: dual.profile"
    )
    assert load_profile(app_paths, "Work: dual").profile.hotkey == ("control", "x")


def test_create_then_resave(app_paths):
    profiles = app_paths.profiles

    assert profile_store.save_managed_profile(app_paths, edited("Work")) == profiles / "Work.profile"
    loaded = load_profile(app_paths, "Work")
    assert save_over(app_paths, loaded, edited("Work", hotkey=("control", "x"))) == profiles / "Work.profile"
    assert load_profile(app_paths, "Work").profile.hotkey == ("control", "x")


def test_saving_a_symlinked_profile_writes_through_to_its_target(app_paths, tmp_path):
    dotfile = tmp_path / "dotfiles" / "Work.profile"
    dotfile.parent.mkdir()
    dotfile.write_text("name=Work\nspanmode=single\nslideshow=false\n", encoding="utf-8")
    link = app_paths.profiles / "Work.profile"
    link.symlink_to(dotfile)
    loaded = load_profile(app_paths, "Work")

    save_over(app_paths, loaded, edited("Work", hotkey=("control", "x")))

    assert link.is_symlink()
    assert "hotkey=control+x" in dotfile.read_text(encoding="utf-8")


def test_directory_named_like_a_profile_is_never_replaced(app_paths):
    (app_paths.profiles / "Work.profile").mkdir()

    with pytest.raises(profile_store.ProfileTransactionError):
        profile_store.save_managed_profile(app_paths, edited("Work"))

    assert (app_paths.profiles / "Work.profile").is_dir()


def test_rename_rolls_back_destination_when_source_delete_fails(app_paths, monkeypatch):
    profiles = app_paths.profiles
    loaded = stored_profile(app_paths, "Work")
    source_path = profiles / "Work.profile"
    real_unlink = Path.unlink

    def fail_source_unlink(path, *args, **kwargs):
        if path == source_path:
            message = "injected source deletion failure"
            raise PermissionError(message)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_source_unlink)

    with pytest.raises(profile_store.ProfileTransactionError) as error:
        save_over(app_paths, loaded, edited("Renamed"))

    assert error.value.stage == "source removal"
    assert source_path.exists()
    assert not (profiles / "Renamed.profile").exists()


def test_save_rejects_a_profile_changed_after_the_editor_loaded_it(app_paths):
    loaded = stored_profile(app_paths, "Work")
    source_path = app_paths.profiles / "Work.profile"
    replacement = b"name=Work\nspanmode=single\nslideshow=false\nhotkey=control+x\n"
    source_path.write_bytes(replacement)

    with pytest.raises(profile_store.ProfileTransactionError) as error:
        save_over(app_paths, loaded, edited("Work"))

    assert error.value.stage == "source verification"
    assert str(error.value) == (
        "Profile save failed during source verification: 'Work' was changed outside the editor after it was "
        "opened. Revert to load the current version, then make your changes again."
    )
    assert source_path.read_bytes() == replacement


def test_rename_restores_source_and_destination_on_pointer_failure(app_paths, monkeypatch):
    loaded = stored_profile(app_paths, "Work")
    source_path = app_paths.profiles / "Work.profile"
    original = source_path.read_bytes()

    def fail_pointer(_cache_dir, _profile):
        message = "injected pointer failure"
        raise PermissionError(message)

    monkeypatch.setattr(profile_store, "write_active_profile", fail_pointer)

    with pytest.raises(profile_store.ProfileTransactionError) as error:
        save_over(app_paths, loaded, edited("Renamed"), update_active=True)

    assert error.value.stage == "active pointer update"
    assert source_path.read_bytes() == original
    assert not (app_paths.profiles / "Renamed.profile").exists()


def test_save_after_apply_succeeds(app_paths, tmp_path):
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.touch()
    second.touch()
    loaded = stored_profile(app_paths, "Work", f"display0paths={tmp_path}\nselected={first}\n")
    loaded.selection.pin([str(second)])  # what Apply does

    save_over(app_paths, loaded, edited("Work", hotkey=("control", "x")), selected=[str(second)])

    reloaded = load_profile(app_paths, "Work")
    assert reloaded.profile.hotkey == ("control", "x")
    assert reloaded.selection.images == [str(second)]


def test_save_after_a_slideshow_tick_succeeds(app_paths, tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "a.png").touch()
    (images / "b.png").touch()
    loaded = stored_profile(app_paths, "Work", f"sortmode=alphabetical\ndisplay0paths={images}\n")
    loaded.selection.advance()  # what a slideshow tick does while the editor is open

    save_over(app_paths, loaded, edited("Work"))

    assert load_profile(app_paths, "Work").selection.images == [str(images / "a.png")]


def test_save_carries_over_a_selection_from_an_older_version(app_paths, tmp_path):
    image = tmp_path / "chosen.png"
    image.touch()
    loaded = stored_profile(app_paths, "Work", f"selected={image}\n")

    save_over(app_paths, loaded, edited("Work"))

    assert "selected=" not in (app_paths.profiles / "Work.profile").read_text(encoding="utf-8")
    assert load_profile(app_paths, "Work").selection.images == [str(image)]


def test_remembering_a_selection_leaves_the_profile_file_alone(app_paths, tmp_path):
    image = tmp_path / "wallpaper.png"
    image.touch()
    loaded = stored_profile(app_paths, "Work", "display0paths=source\ncustom=value\n")
    original = (app_paths.profiles / "Work.profile").read_bytes()

    loaded.selection.pin([str(image)])

    assert (app_paths.profiles / "Work.profile").read_bytes() == original
    assert load_profile(app_paths, "Work").selection.images == [str(image)]


def test_rename_moves_the_selection_and_delete_forgets_it(app_paths, tmp_path):
    image = tmp_path / "wallpaper.png"
    image.touch()
    loaded = stored_profile(app_paths, "Work")
    loaded.selection.pin([str(image)])

    save_over(app_paths, loaded, edited("Renamed"))
    renamed = load_profile(app_paths, "Renamed")
    profile_store.delete_managed_profile(app_paths, renamed)
    recreated = stored_profile(app_paths, "Renamed")

    assert renamed.selection.images == [str(image)]
    assert recreated.selection.images is None


def test_the_store_saves_and_hands_out_one_record_per_profile(app_paths, tmp_path):
    store = profile_store.ProfileStore(app_paths)
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
    store = profile_store.ProfileStore(app_paths)
    store.reload()
    work = store.get(ProfileId("Work"))
    work.selection.advance()

    (app_paths.profiles / "Home.profile").write_text("name=Home\nhotkey=alt+h\n", encoding="utf-8")
    store.reload()

    # Work's slideshow goes on where it was; Home is loaded again, with its change.
    assert store.get(ProfileId("Work")) is work
    assert work.selection.advance() == [str(images / "b.png")]
    assert store.get(ProfileId("Home")).profile.hotkey == ("alt", "h")
