import sys
from pathlib import Path

import pytest

from superpaper.profile_id import ProfileId


def temp_profile(data, name):
    profile = data.TempProfileData()
    profile.name = name
    profile.spanmode = "single"
    profile.slideshow = False
    profile.paths_array = ["source"]
    profile.is_list_valid_paths = lambda paths: True
    return profile


def stored_profile(data, app_paths, name, extra=""):
    path = app_paths.profiles / f"{name}.profile"
    path.write_text(f"name={name}\nspanmode=single\nslideshow=false\n{extra}", "utf-8")
    return data.open_profile(app_paths, ProfileId(name))


def save_over(data, app_paths, loaded, edited, **kwargs):
    """Save ``edited`` the way the editor does after opening ``loaded``."""
    return data.save_managed_profile(
        app_paths,
        edited,
        current_profile_id=loaded.profile_id,
        expected_source_digest=loaded.source_digest,
        **kwargs,
    )


@pytest.mark.parametrize("name", ["../escape", "cli", "bad=name", "trailing.", "Work: dual"])
def test_new_profile_with_unusable_name_is_rejected_without_write(
    profile_modules, app_paths, monkeypatch, tmp_path, name
):
    data, _ = profile_modules
    profiles = app_paths.profiles
    profile = temp_profile(data, name)

    assert profile.test_save(profiles_dir=app_paths.profiles) is False
    with pytest.raises(data.ProfileTransactionError):
        data.save_managed_profile(app_paths, profile)
    assert list(profiles.iterdir()) == []


def test_new_profile_rejects_portable_collision(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    existing = profiles / "Work.profile"
    existing.write_text("name=Work\n", encoding="utf-8")
    profile = temp_profile(data, "work")

    assert profile.test_save(profiles_dir=app_paths.profiles) is False
    with pytest.raises(data.ProfileTransactionError):
        data.save_managed_profile(app_paths, profile)
    assert existing.read_text(encoding="utf-8") == "name=Work\n"
    assert [path.name for path in profiles.iterdir()] == ["Work.profile"]


def test_new_name_collides_with_a_file_that_does_not_load(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    broken = profiles / "Work.profile"
    broken.write_text("name=Work\ndelay=not-a-number\n", encoding="utf-8")

    with pytest.raises(data.ProfileTransactionError):
        data.save_managed_profile(app_paths, temp_profile(data, "work"))

    assert broken.read_text(encoding="utf-8") == "name=Work\ndelay=not-a-number\n"


def test_case_only_rename_is_rejected(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    loaded = stored_profile(data, app_paths, "Work")
    original = (profiles / "Work.profile").read_bytes()
    renamed = temp_profile(data, "work")

    assert renamed.test_save(profiles_dir=app_paths.profiles, current_profile_id=loaded.profile_id) is False
    with pytest.raises(data.ProfileTransactionError):
        save_over(data, app_paths, loaded, renamed)
    assert (profiles / "Work.profile").read_bytes() == original


@pytest.mark.skipif(sys.platform == "win32", reason="this filename cannot exist on Windows")
def test_resave_keeps_a_name_that_new_profiles_may_not_use(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    loaded = stored_profile(data, app_paths, "Work: dual")
    edited = temp_profile(data, "Work: dual")
    edited.hk_binding = "control+x"

    assert edited.test_save(profiles_dir=app_paths.profiles, current_profile_id=loaded.profile_id) is True
    assert save_over(data, app_paths, loaded, edited) == profiles / "Work: dual.profile"
    assert data.open_profile(app_paths, "Work: dual").hk_binding == ("control", "x")


def test_create_then_resave(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    image = tmp_path / "wallpaper.png"
    image.touch()
    profile = temp_profile(data, "Work")
    profile.paths_array = [str(image)]

    assert profile.test_save(profiles_dir=app_paths.profiles) is True
    assert data.save_managed_profile(app_paths, profile) == profiles / "Work.profile"
    loaded = data.open_profile(app_paths, ProfileId("Work"))
    profile.hk_binding = "control+x"
    assert save_over(data, app_paths, loaded, profile) == profiles / "Work.profile"
    assert data.open_profile(app_paths, ProfileId("Work")).hk_binding == ("control", "x")


def test_unmanaged_preview_allows_reserved_cli_name(profile_modules, tmp_path):
    data, _ = profile_modules
    preview_path = tmp_path / "preview.profile"
    profile = temp_profile(data, "cli")

    assert profile.test_save() is True
    assert profile.save(filename=preview_path) == preview_path
    parsed = data.parse_profile_file(preview_path)
    assert parsed.name == "cli"
    assert parsed.profile_id is None


def test_saving_a_symlinked_profile_writes_through_to_its_target(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    dotfile = tmp_path / "dotfiles" / "Work.profile"
    dotfile.parent.mkdir()
    dotfile.write_text("name=Work\nspanmode=single\nslideshow=false\n", encoding="utf-8")
    link = profiles / "Work.profile"
    link.symlink_to(dotfile)
    loaded = data.open_profile(app_paths, ProfileId("Work"))
    edited = temp_profile(data, "Work")
    edited.hk_binding = "control+x"

    save_over(data, app_paths, loaded, edited)

    assert link.is_symlink()
    assert "hotkey=control+x" in dotfile.read_text(encoding="utf-8")


def test_directory_named_like_a_profile_is_never_replaced(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    (profiles / "Work.profile").mkdir()

    with pytest.raises(data.ProfileTransactionError):
        data.save_managed_profile(app_paths, temp_profile(data, "Work"))

    assert (profiles / "Work.profile").is_dir()


def test_rename_rolls_back_destination_when_source_delete_fails(profile_modules, app_paths, monkeypatch, tmp_path):
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
        save_over(data, app_paths, loaded, temp_profile(data, "Renamed"))

    assert error.value.stage == "source removal"
    assert source_path.exists()
    assert not (profiles / "Renamed.profile").exists()


def test_save_rejects_a_profile_changed_after_the_editor_loaded_it(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    loaded = stored_profile(data, app_paths, "Work")
    source_path = profiles / "Work.profile"
    replacement = b"name=Work\nspanmode=single\nslideshow=false\nhotkey=control+x\n"
    source_path.write_bytes(replacement)

    with pytest.raises(data.ProfileTransactionError) as error:
        save_over(data, app_paths, loaded, temp_profile(data, "Work"))

    assert error.value.stage == "source verification"
    assert "Revert" in str(error.value)
    assert source_path.read_bytes() == replacement


def test_rename_restores_source_and_destination_on_pointer_failure(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    loaded = stored_profile(data, app_paths, "Work")
    source_path = profiles / "Work.profile"
    original = source_path.read_bytes()

    def fail_pointer(_cache_dir, _profile):
        message = "injected pointer failure"
        raise PermissionError(message)

    monkeypatch.setattr(data, "write_active_profile", fail_pointer)

    with pytest.raises(data.ProfileTransactionError) as error:
        save_over(data, app_paths, loaded, temp_profile(data, "Renamed"), update_active=True)

    assert error.value.stage == "active pointer update"
    assert source_path.read_bytes() == original
    assert not (profiles / "Renamed.profile").exists()


def test_save_after_apply_succeeds(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.touch()
    second.touch()
    loaded = stored_profile(data, app_paths, "Work", f"display0paths={tmp_path}\nselected={first}\n")
    loaded.set_selected_wallpaper([str(second)], persist=True)  # what Apply does
    edited = temp_profile(data, "Work")
    edited.hk_binding = "control+x"
    edited.selected = [str(second)]

    save_over(data, app_paths, loaded, edited)

    reloaded = data.open_profile(app_paths, ProfileId("Work"))
    assert reloaded.hk_binding == ("control", "x")
    assert reloaded.selected == [str(second)]


def test_save_after_a_slideshow_tick_succeeds(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    images = tmp_path / "images"
    images.mkdir()
    (images / "a.png").touch()
    (images / "b.png").touch()
    loaded = stored_profile(data, app_paths, "Work", f"sortmode=alphabetical\ndisplay0paths={images}\n")
    loaded.advance_wallpaper()  # what a slideshow tick does while the editor is open

    save_over(data, app_paths, loaded, temp_profile(data, "Work"))

    assert data.open_profile(app_paths, ProfileId("Work")).selected == [str(images / "a.png")]


def test_save_carries_over_a_selection_from_an_older_version(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    image = tmp_path / "chosen.png"
    image.touch()
    loaded = stored_profile(data, app_paths, "Work", f"selected={image}\n")

    save_over(data, app_paths, loaded, temp_profile(data, "Work"))

    assert "selected=" not in (profiles / "Work.profile").read_text(encoding="utf-8")
    assert data.open_profile(app_paths, ProfileId("Work")).selected == [str(image)]


def test_remembering_a_selection_leaves_the_profile_file_alone(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = app_paths.profiles
    image = tmp_path / "wallpaper.png"
    image.touch()
    loaded = stored_profile(data, app_paths, "Work", "display0paths=source\ncustom=value\n")
    original = (profiles / "Work.profile").read_bytes()

    loaded.set_selected_wallpaper([str(image)], persist=True)

    assert (profiles / "Work.profile").read_bytes() == original
    assert data.open_profile(app_paths, ProfileId("Work")).selected == [str(image)]


def test_rename_moves_the_selection_and_delete_forgets_it(profile_modules, app_paths, monkeypatch, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "wallpaper.png"
    image.touch()
    loaded = stored_profile(data, app_paths, "Work")
    loaded.set_selected_wallpaper([str(image)], persist=True)

    save_over(data, app_paths, loaded, temp_profile(data, "Renamed"))
    renamed = data.open_profile(app_paths, ProfileId("Renamed"))
    data.delete_managed_profile(app_paths, renamed)
    recreated = stored_profile(data, app_paths, "Renamed")

    assert renamed.selected == [str(image)]
    assert recreated.selected is None


def test_unmanaged_preview_selection_is_never_persisted(profile_modules, tmp_path):
    data, _ = profile_modules
    path = tmp_path / "preview.profile"
    original = b"name=preview\nspanmode=single\nslideshow=false\n"
    path.write_bytes(original)
    preview = data.parse_profile_file(path)

    preview.set_selected_wallpaper(["wallpaper.png"], persist=True)

    assert path.read_bytes() == original


def test_validation_accepts_upper_case_image_extensions(profile_modules, tmp_path):
    data, _ = profile_modules
    camera = tmp_path / "camera"
    camera.mkdir()
    (camera / "IMG_0001.JPG").touch()
    profile = data.TempProfileData()
    profile.name = "camera"
    profile.spanmode = "single"
    profile.slideshow = False
    profile.paths_array = [str(camera)]

    assert profile.test_save() is True
