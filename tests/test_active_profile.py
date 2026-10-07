import os

import pytest

from superpaper.profile_id import ProfileId, ProfileIdError
from tests.conftest import write_profile


def prepare_profile(app_paths, tmp_path):
    image = tmp_path / "wallpaper.png"
    image.touch()
    write_profile(app_paths.profiles / "test.profile", sources=[image])
    return app_paths.cache


def test_active_profile_round_trip(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)

    data.write_active_profile(app_paths.cache, "test")

    assert (cache / "running_profile").read_text(encoding="utf-8") == "test"
    assert data.read_active_profile(app_paths).name == "test"


def test_active_profile_accepts_lf(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)
    (cache / "running_profile").write_text("test\n", encoding="utf-8")

    assert data.read_active_profile(app_paths).name == "test"


def test_active_profile_accepts_crlf(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)
    (cache / "running_profile").write_bytes(b"test\r\n")

    assert data.read_active_profile(app_paths).name == "test"


def test_active_profile_uses_first_record(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)
    (cache / "running_profile").write_text("test\nmissing\n", encoding="utf-8")

    assert data.read_active_profile(app_paths).name == "test"


def test_empty_active_profile_returns_none(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)
    (cache / "running_profile").touch()

    assert data.read_active_profile(app_paths) is None


def test_missing_pointer_reads_as_none_without_creating_it(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)

    assert data.read_active_profile(app_paths) is None
    assert not (cache / "running_profile").exists()


def test_invalid_active_profile_pointer_is_rejected_without_rewrite(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)
    pointer = cache / "running_profile"
    original = b"../test\n"
    pointer.write_bytes(original)

    assert data.read_active_profile(app_paths) is None
    assert pointer.read_bytes() == original


def test_pointer_resolves_a_profile_whose_name_line_differs(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)
    pointer = cache / "running_profile"
    pointer.write_text("test", encoding="utf-8")
    profiles = app_paths.profiles
    (profiles / "test.profile").write_text("name=other\n", encoding="utf-8")

    assert data.read_active_profile(app_paths).name == "test"
    assert pointer.read_text(encoding="utf-8") == "test"


def test_pointer_resolves_a_symlinked_profile(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)
    profiles = app_paths.profiles
    target = tmp_path / "target.profile"
    target.write_bytes((profiles / "test.profile").read_bytes())
    (profiles / "test.profile").unlink()
    (profiles / "test.profile").symlink_to(target)
    (cache / "running_profile").write_text("test", encoding="utf-8")

    assert data.read_active_profile(app_paths).name == "test"


def test_invalid_active_profile_write_does_not_touch_pointer(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)
    pointer = cache / "running_profile"
    pointer.write_text("test", encoding="utf-8")

    with pytest.raises(ProfileIdError):
        data.write_active_profile(app_paths.cache, "../other")

    assert pointer.read_text(encoding="utf-8") == "test"


def test_active_profile_write_accepts_profile_id(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)

    data.write_active_profile(app_paths.cache, ProfileId("test"))

    assert (cache / "running_profile").read_text(encoding="utf-8") == "test"


def test_active_profile_write_never_replaces_a_directory(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)
    (cache / "running_profile").mkdir()

    with pytest.raises(OSError):
        data.write_active_profile(app_paths.cache, "test")

    assert (cache / "running_profile").is_dir()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_active_profile_read_does_not_block_on_fifo(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    cache = prepare_profile(app_paths, tmp_path)
    os.mkfifo(cache / "running_profile")

    assert data.read_active_profile(app_paths) is None
