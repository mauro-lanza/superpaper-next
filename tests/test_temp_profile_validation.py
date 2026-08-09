import pytest

from superpaper.profile_id import ProfileId


def prepare(data, monkeypatch, tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr(data.sp_paths, "PROFILES_PATH", str(profiles))
    return profiles


def temp_profile(data, name):
    profile = data.TempProfileData()
    profile.name = name
    profile.spanmode = "single"
    profile.slideshow = False
    profile.paths_array = ["source"]
    profile.is_list_valid_paths = lambda paths: True
    return profile


@pytest.mark.parametrize("name", ["../escape", "cli", "bad=name"])
def test_managed_validation_rejects_invalid_name_without_write(profile_modules, monkeypatch, tmp_path, name):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    profile = temp_profile(data, name)

    assert profile.test_save() is False
    assert profile.save() is None
    assert list(profiles.iterdir()) == []


def test_managed_save_rejects_portable_collision(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    existing = profiles / "Work.profile"
    existing.write_text("name=Work\n", encoding="utf-8")
    profile = temp_profile(data, "work")

    assert profile.test_save() is False
    assert profile.save() is None
    assert existing.read_text(encoding="utf-8") == "name=Work\n"
    assert not (profiles / "work.profile").exists()


def test_managed_save_rejects_case_only_rename(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    existing = profiles / "Work.profile"
    existing.write_text("name=Work\n", encoding="utf-8")
    profile = temp_profile(data, "work")

    assert profile.test_save(current_profile_id=ProfileId("Work")) is False
    assert profile.save(current_profile_id=ProfileId("Work")) is None
    assert existing.read_text(encoding="utf-8") == "name=Work\n"


def test_managed_save_allows_current_profile_and_safe_lookup(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    image = tmp_path / "wallpaper.png"
    image.touch()
    profile = temp_profile(data, "Work")
    profile.paths_array = [str(image)]
    current_id = ProfileId("Work")

    assert profile.test_save(current_profile_id=current_id) is True
    assert profile.save(current_profile_id=current_id) == profiles / "Work.profile"
    assert data.open_profile(current_id).profile_id == current_id


def test_unmanaged_preview_allows_reserved_cli_name(profile_modules, tmp_path):
    data, _ = profile_modules
    preview_path = tmp_path / "preview.profile"
    profile = temp_profile(data, "cli")

    assert profile.test_save(managed=False) is True
    assert profile.save(filename=preview_path) == preview_path
    parsed = data.parse_profile_file(preview_path)
    assert parsed.name == "cli"
    assert parsed.profile_id is None


def test_managed_save_rejects_symlink_without_touching_target(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("outside", encoding="utf-8")
    (profiles / "Work.profile").symlink_to(sentinel)
    profile = temp_profile(data, "Work")

    assert profile.save(current_profile_id=ProfileId("Work")) is None
    assert sentinel.read_text(encoding="utf-8") == "outside"


def test_managed_save_rejects_nonregular_destination(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    (profiles / "Work.profile").mkdir()
    profile = temp_profile(data, "Work")

    assert profile.save(current_profile_id=ProfileId("Work")) is None
    assert (profiles / "Work.profile").is_dir()


def test_managed_create_does_not_overwrite_collision(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    profile = temp_profile(data, "Work")
    real_atomic_write = data._atomic_write_regular

    def collide(path, content, *, may_replace):
        path.write_text("collision", encoding="utf-8")
        return real_atomic_write(path, content, may_replace=may_replace)

    monkeypatch.setattr(data, "_atomic_write_regular", collide)

    assert profile.save() is None
    assert (profiles / "Work.profile").read_text(encoding="utf-8") == "collision"


def test_managed_create_rejects_symlink_created_immediately_before_publish(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    if not data._HAS_DIR_FD_MUTATIONS:
        pytest.skip("directory-relative mutations are unavailable")
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "Work.profile"
    sentinel = tmp_path / "sentinel.profile"
    sentinel.write_bytes(b"outside")
    profile = temp_profile(data, "Work")
    real_identity = data._regular_destination_identity_at
    checks = 0

    def replace_before_publish(directory_fd, candidate, *, allow_missing):
        nonlocal checks
        if candidate == path and allow_missing:
            checks += 1
            if checks == 2:
                path.symlink_to(sentinel)
        return real_identity(directory_fd, candidate, allow_missing=allow_missing)

    monkeypatch.setattr(data, "_regular_destination_identity_at", replace_before_publish)

    assert profile.save() is None
    assert path.is_symlink()
    assert sentinel.read_bytes() == b"outside"


def test_rename_rolls_back_destination_when_source_delete_fails(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    source_path = profiles / "Work.profile"
    source_path.write_bytes(b"name=Work\nspanmode=single\nslideshow=false\n")
    source = data.open_profile(ProfileId("Work"))
    renamed = temp_profile(data, "Renamed")
    original_remove = data._remove_managed_path

    def fail_source_remove(path, identity):
        if path == source_path:
            message = "injected source deletion failure"
            raise PermissionError(message)
        return original_remove(path, identity)

    monkeypatch.setattr(data, "_remove_managed_path", fail_source_remove)

    with pytest.raises(data.ProfileTransactionError) as error:
        data.save_managed_profile(
            renamed,
            current_profile_id=source.profile_id,
            expected_source_identity=source.source_identity,
        )

    assert error.value.stage == "source removal"
    assert source_path.exists()
    assert not (profiles / "Renamed.profile").exists()


def test_save_rejects_source_replaced_after_dialog_load(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    source_path = profiles / "Work.profile"
    source_path.write_bytes(b"name=Work\nspanmode=single\nslideshow=false\n")
    loaded = data.open_profile(ProfileId("Work"))
    replacement = b"name=Work\nspanmode=single\nslideshow=false\nhotkey=control+x\n"
    source_path.unlink()
    source_path.write_bytes(replacement)
    edited = temp_profile(data, "Work")

    with pytest.raises(data.ProfileTransactionError) as error:
        data.save_managed_profile(
            edited,
            current_profile_id=loaded.profile_id,
            expected_source_identity=loaded.source_identity,
        )

    assert error.value.stage == "source verification"
    assert source_path.read_bytes() == replacement


def test_rename_rejects_destination_appearing_during_publication(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    if not data._HAS_DIR_FD_MUTATIONS:
        pytest.skip("directory-relative mutations are unavailable")
    profiles = prepare(data, monkeypatch, tmp_path)
    source_path = profiles / "Work.profile"
    destination = profiles / "Renamed.profile"
    source_path.write_bytes(b"name=Work\nspanmode=single\nslideshow=false\n")
    loaded = data.open_profile(ProfileId("Work"))
    renamed = temp_profile(data, "Renamed")
    real_link = data.os.link

    def collide_before_link(source, target, **kwargs):
        destination.write_bytes(b"concurrent")
        return real_link(source, target, **kwargs)

    monkeypatch.setattr(data.os, "link", collide_before_link)

    with pytest.raises(data.ProfileTransactionError) as error:
        data.save_managed_profile(
            renamed,
            current_profile_id=loaded.profile_id,
            expected_source_identity=loaded.source_identity,
        )

    assert error.value.stage == "destination write"
    assert source_path.exists()
    assert destination.read_bytes() == b"concurrent"


def test_rename_retains_source_replacement_made_immediately_before_unlink(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    if not data._HAS_DIR_FD_MUTATIONS:
        pytest.skip("directory-relative mutations are unavailable")
    profiles = prepare(data, monkeypatch, tmp_path)
    source_path = profiles / "Work.profile"
    source_path.write_bytes(b"name=Work\nspanmode=single\nslideshow=false\n")
    source = data.open_profile(ProfileId("Work"))
    renamed = temp_profile(data, "Renamed")
    replacement = b"name=Work\nspanmode=single\nslideshow=false\nhotkey=control+x\n"
    real_identity = data._regular_destination_identity_at
    injected = False

    def replace_before_check(directory_fd, path, *, allow_missing):
        nonlocal injected
        if path == source_path and not allow_missing and not injected:
            injected = True
            source_path.unlink()
            source_path.write_bytes(replacement)
        return real_identity(directory_fd, path, allow_missing=allow_missing)

    monkeypatch.setattr(data, "_regular_destination_identity_at", replace_before_check)

    with pytest.raises(data.ProfileTransactionError) as error:
        data.save_managed_profile(
            renamed,
            current_profile_id=source.profile_id,
            expected_source_identity=source.source_identity,
        )

    assert error.value.stage == "source removal"
    assert source_path.read_bytes() == replacement
    assert not (profiles / "Renamed.profile").exists()


def test_managed_replace_rejects_replacement_made_immediately_before_publish(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    if not data._HAS_DIR_FD_MUTATIONS:
        pytest.skip("directory-relative mutations are unavailable")
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "Work.profile"
    path.write_bytes(b"name=Work\nspanmode=single\nslideshow=false\n")
    loaded = data.open_profile(ProfileId("Work"))
    replacement = b"name=Work\nspanmode=single\nslideshow=false\nhotkey=control+x\n"
    real_identity = data._regular_destination_identity_at
    checks = 0

    def replace_before_check(directory_fd, candidate, *, allow_missing):
        nonlocal checks
        if candidate == path and allow_missing:
            checks += 1
            if checks == 2:
                path.unlink()
                path.write_bytes(replacement)
        return real_identity(directory_fd, candidate, allow_missing=allow_missing)

    monkeypatch.setattr(data, "_regular_destination_identity_at", replace_before_check)

    loaded.set_selected_wallpaper(["wallpaper.png"], persist=True)

    assert path.read_bytes() == replacement


def test_rename_restores_source_and_destination_on_pointer_failure(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    source_path = profiles / "Work.profile"
    original = b"name=Work\nspanmode=single\nslideshow=false\n"
    source_path.write_bytes(original)
    source = data.open_profile(ProfileId("Work"))
    renamed = temp_profile(data, "Renamed")

    def fail_pointer(_profile):
        message = "injected pointer failure"
        raise PermissionError(message)

    monkeypatch.setattr(data, "write_active_profile", fail_pointer)

    with pytest.raises(data.ProfileTransactionError) as error:
        data.save_managed_profile(
            renamed,
            current_profile_id=source.profile_id,
            expected_source_identity=source.source_identity,
            update_active=True,
        )

    assert error.value.stage == "active pointer update"
    assert source_path.read_bytes() == original
    assert not (profiles / "Renamed.profile").exists()


def test_managed_selection_write_is_atomic_and_rejects_symlink_replacement(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    image = tmp_path / "wallpaper.png"
    image.touch()
    path = profiles / "Work.profile"
    original = b"name=Work\nspanmode=single\nslideshow=false\ndisplay0paths=source\n"
    path.write_bytes(original)
    loaded = data.open_profile(ProfileId("Work"))
    path.unlink()
    sentinel = tmp_path / "sentinel.profile"
    sentinel.write_bytes(b"outside")
    path.symlink_to(sentinel)

    loaded.set_selected_wallpaper([str(image)], persist=True)

    assert path.is_symlink()
    assert sentinel.read_bytes() == b"outside"


def test_managed_selection_write_atomically_preserves_profile_bytes(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    image = tmp_path / "wallpaper.png"
    image.touch()
    path = profiles / "Work.profile"
    original = b"name=Work\nspanmode=single\nslideshow=false\ndisplay0paths=source\ncustom=value\n"
    path.write_bytes(original)
    loaded = data.open_profile(ProfileId("Work"))

    loaded.set_selected_wallpaper([str(image)], persist=True)

    assert path.read_bytes() == original + f"selected={image}\n".encode()


def test_unmanaged_preview_selection_is_never_persisted(profile_modules, tmp_path):
    data, _ = profile_modules
    path = tmp_path / "preview.profile"
    original = b"name=preview\nspanmode=single\nslideshow=false\n"
    path.write_bytes(original)
    preview = data.parse_profile_file(path)

    preview.set_selected_wallpaper(["wallpaper.png"], persist=True)

    assert path.read_bytes() == original
