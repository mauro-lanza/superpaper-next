"""Saving a profile from the editor: the names it may have, and saving over, renaming and
deleting it without losing edits made elsewhere or the images it shows."""

import sys
from pathlib import Path

import pytest

from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.profiles import Profile


def edited(name, **settings):
    """The settings the editor saves."""
    return Profile(name=name, slideshow=False, sources=(("source",),), **settings)


def stored_profile(data, app_paths, name, extra=""):
    path = app_paths.profiles / f"{name}.profile"
    path.write_text(f"name={name}\nspanmode=single\nslideshow=false\n{extra}", "utf-8")
    return data.open_profile(app_paths, ProfileId(name))


def save_over(data, app_paths, loaded, profile, **kwargs):
    """Save ``profile`` the way the editor does after opening ``loaded``."""
    return data.save_managed_profile(
        app_paths, profile, current_profile_id=loaded.profile_id, expected_source_digest=loaded.digest, **kwargs
    )


@pytest.mark.parametrize("name", ["../escape", "cli", "bad=name", "trailing.", "Work: dual"])
def test_new_profile_with_unusable_name_is_rejected_without_write(profile_modules, app_paths, name):
    data, _ = profile_modules

    with pytest.raises((ProfileIdError, ValueError)):
        data.validate_managed_profile_id(app_paths.profiles, name)
    with pytest.raises(data.ProfileTransactionError):
        data.save_managed_profile(app_paths, edited(name))
    assert list(app_paths.profiles.iterdir()) == []


def test_new_profile_rejects_portable_collision(profile_modules, app_paths):
    data, _ = profile_modules
    profiles = app_paths.profiles
    existing = profiles / "Work.profile"
    existing.write_text("name=Work\n", encoding="utf-8")

    with pytest.raises(ValueError, match="collides"):
        data.validate_managed_profile_id(profiles, "work")
    with pytest.raises(data.ProfileTransactionError):
        data.save_managed_profile(app_paths, edited("work"))
    assert existing.read_text(encoding="utf-8") == "name=Work\n"
    assert [path.name for path in profiles.iterdir()] == ["Work.profile"]


def test_new_name_collides_with_a_file_that_does_not_load(profile_modules, app_paths):
    data, _ = profile_modules
    broken = app_paths.profiles / "Work.profile"
    broken.write_text("name=Work\ndelay=not-a-number\n", encoding="utf-8")

    with pytest.raises(data.ProfileTransactionError):
        data.save_managed_profile(app_paths, edited("work"))

    assert broken.read_text(encoding="utf-8") == "name=Work\ndelay=not-a-number\n"


def test_case_only_rename_is_rejected(profile_modules, app_paths):
    data, _ = profile_modules
    profiles = app_paths.profiles
    loaded = stored_profile(data, app_paths, "Work")
    original = (profiles / "Work.profile").read_bytes()

    with pytest.raises(ValueError, match="collides"):
        data.validate_managed_profile_id(profiles, "work", loaded.profile_id)
    with pytest.raises(data.ProfileTransactionError):
        save_over(data, app_paths, loaded, edited("work"))
    assert (profiles / "Work.profile").read_bytes() == original


@pytest.mark.skipif(sys.platform == "win32", reason="this filename cannot exist on Windows")
def test_resave_keeps_a_name_that_new_profiles_may_not_use(profile_modules, app_paths):
    data, _ = profile_modules
    loaded = stored_profile(data, app_paths, "Work: dual")

    assert data.validate_managed_profile_id(app_paths.profiles, "Work: dual", loaded.profile_id) == loaded.profile_id
    assert save_over(data, app_paths, loaded, edited("Work: dual", hotkey=("control", "x"))) == (
        app_paths.profiles / "Work: dual.profile"
    )
    assert data.open_profile(app_paths, "Work: dual").profile.hotkey == ("control", "x")


def test_create_then_resave(profile_modules, app_paths):
    data, _ = profile_modules
    profiles = app_paths.profiles

    assert data.save_managed_profile(app_paths, edited("Work")) == profiles / "Work.profile"
    loaded = data.open_profile(app_paths, ProfileId("Work"))
    assert save_over(data, app_paths, loaded, edited("Work", hotkey=("control", "x"))) == profiles / "Work.profile"
    assert data.open_profile(app_paths, ProfileId("Work")).profile.hotkey == ("control", "x")


def test_saving_a_symlinked_profile_writes_through_to_its_target(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    dotfile = tmp_path / "dotfiles" / "Work.profile"
    dotfile.parent.mkdir()
    dotfile.write_text("name=Work\nspanmode=single\nslideshow=false\n", encoding="utf-8")
    link = app_paths.profiles / "Work.profile"
    link.symlink_to(dotfile)
    loaded = data.open_profile(app_paths, ProfileId("Work"))

    save_over(data, app_paths, loaded, edited("Work", hotkey=("control", "x")))

    assert link.is_symlink()
    assert "hotkey=control+x" in dotfile.read_text(encoding="utf-8")


def test_directory_named_like_a_profile_is_never_replaced(profile_modules, app_paths):
    data, _ = profile_modules
    (app_paths.profiles / "Work.profile").mkdir()

    with pytest.raises(data.ProfileTransactionError):
        data.save_managed_profile(app_paths, edited("Work"))

    assert (app_paths.profiles / "Work.profile").is_dir()


def test_rename_rolls_back_destination_when_source_delete_fails(profile_modules, app_paths, monkeypatch):
    data, _ = profile_modules
    profiles = app_paths.profiles
    loaded = stored_profile(data, app_paths, "Work")
    source_path = profiles / "Work.profile"
    real_unlink = Path.unlink

    def fail_source_unlink(path, *args, **kwargs):
        if path == source_path:
            message = "injected source deletion failure"
            raise PermissionError(message)
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_source_unlink)

    with pytest.raises(data.ProfileTransactionError) as error:
        save_over(data, app_paths, loaded, edited("Renamed"))

    assert error.value.stage == "source removal"
    assert source_path.exists()
    assert not (profiles / "Renamed.profile").exists()


def test_save_rejects_a_profile_changed_after_the_editor_loaded_it(profile_modules, app_paths):
    data, _ = profile_modules
    loaded = stored_profile(data, app_paths, "Work")
    source_path = app_paths.profiles / "Work.profile"
    replacement = b"name=Work\nspanmode=single\nslideshow=false\nhotkey=control+x\n"
    source_path.write_bytes(replacement)

    with pytest.raises(data.ProfileTransactionError) as error:
        save_over(data, app_paths, loaded, edited("Work"))

    assert error.value.stage == "source verification"
    assert "Revert" in str(error.value)
    assert source_path.read_bytes() == replacement


def test_rename_restores_source_and_destination_on_pointer_failure(profile_modules, app_paths, monkeypatch):
    data, _ = profile_modules
    loaded = stored_profile(data, app_paths, "Work")
    source_path = app_paths.profiles / "Work.profile"
    original = source_path.read_bytes()

    def fail_pointer(_cache_dir, _profile):
        message = "injected pointer failure"
        raise PermissionError(message)

    monkeypatch.setattr(data, "write_active_profile", fail_pointer)

    with pytest.raises(data.ProfileTransactionError) as error:
        save_over(data, app_paths, loaded, edited("Renamed"), update_active=True)

    assert error.value.stage == "active pointer update"
    assert source_path.read_bytes() == original
    assert not (app_paths.profiles / "Renamed.profile").exists()


def test_save_after_apply_succeeds(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.touch()
    second.touch()
    loaded = stored_profile(data, app_paths, "Work", f"display0paths={tmp_path}\nselected={first}\n")
    loaded.selection.pin([str(second)])  # what Apply does

    save_over(data, app_paths, loaded, edited("Work", hotkey=("control", "x")), selected=[str(second)])

    reloaded = data.open_profile(app_paths, ProfileId("Work"))
    assert reloaded.profile.hotkey == ("control", "x")
    assert reloaded.selection.images == [str(second)]


def test_save_after_a_slideshow_tick_succeeds(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    images = tmp_path / "images"
    images.mkdir()
    (images / "a.png").touch()
    (images / "b.png").touch()
    loaded = stored_profile(data, app_paths, "Work", f"sortmode=alphabetical\ndisplay0paths={images}\n")
    loaded.selection.advance()  # what a slideshow tick does while the editor is open

    save_over(data, app_paths, loaded, edited("Work"))

    assert data.open_profile(app_paths, ProfileId("Work")).selection.images == [str(images / "a.png")]


def test_save_carries_over_a_selection_from_an_older_version(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "chosen.png"
    image.touch()
    loaded = stored_profile(data, app_paths, "Work", f"selected={image}\n")

    save_over(data, app_paths, loaded, edited("Work"))

    assert "selected=" not in (app_paths.profiles / "Work.profile").read_text(encoding="utf-8")
    assert data.open_profile(app_paths, ProfileId("Work")).selection.images == [str(image)]


def test_remembering_a_selection_leaves_the_profile_file_alone(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "wallpaper.png"
    image.touch()
    loaded = stored_profile(data, app_paths, "Work", "display0paths=source\ncustom=value\n")
    original = (app_paths.profiles / "Work.profile").read_bytes()

    loaded.selection.pin([str(image)])

    assert (app_paths.profiles / "Work.profile").read_bytes() == original
    assert data.open_profile(app_paths, ProfileId("Work")).selection.images == [str(image)]


def test_rename_moves_the_selection_and_delete_forgets_it(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "wallpaper.png"
    image.touch()
    loaded = stored_profile(data, app_paths, "Work")
    loaded.selection.pin([str(image)])

    save_over(data, app_paths, loaded, edited("Renamed"))
    renamed = data.open_profile(app_paths, ProfileId("Renamed"))
    data.delete_managed_profile(app_paths, renamed)
    recreated = stored_profile(data, app_paths, "Renamed")

    assert renamed.selection.images == [str(image)]
    assert recreated.selection.images is None
