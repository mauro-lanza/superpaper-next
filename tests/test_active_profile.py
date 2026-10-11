"""Which profile was running when Superpaper last exited: the running_profile pointer."""

import os

import pytest

from superpaper import profile_store
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.profile_store import ProfileStore
from tests.conftest import write_profile


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


def test_active_profile_round_trip(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)

    profile_store.write_active_profile(app_paths.cache, "test")

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
        profile_store.write_active_profile(app_paths.cache, "../other")

    assert pointer.read_text(encoding="utf-8") == "test"


def test_active_profile_write_accepts_profile_id(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)

    profile_store.write_active_profile(app_paths.cache, ProfileId("test"))

    assert (cache / "running_profile").read_text(encoding="utf-8") == "test"


def test_active_profile_write_never_replaces_a_directory(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)
    (cache / "running_profile").mkdir()

    with pytest.raises(OSError):
        profile_store.write_active_profile(app_paths.cache, "test")

    assert (cache / "running_profile").is_dir()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_active_profile_read_does_not_block_on_fifo(app_paths, tmp_path):
    cache = prepare_profile(app_paths, tmp_path)
    os.mkfifo(cache / "running_profile")

    assert profile_store.read_active_profile_id(cache) is None
