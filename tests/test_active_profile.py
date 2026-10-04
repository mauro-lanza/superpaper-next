import os

import pytest

from superpaper.profile_id import ProfileId, ProfileIdError
from tests.conftest import write_profile


def prepare_profile(data, wpproc, monkeypatch, tmp_path):
    profiles = tmp_path / "profiles"
    cache = tmp_path / "cache"
    profiles.mkdir()
    cache.mkdir(exist_ok=True)
    image = tmp_path / "wallpaper.png"
    image.touch()
    write_profile(profiles / "test.profile", sources=[image])
    monkeypatch.setattr(data.sp_paths, "PROFILES_PATH", str(profiles))
    monkeypatch.setattr(data.sp_paths, "TEMP_PATH", str(cache))
    monkeypatch.setattr(wpproc, "NUM_DISPLAYS", 1)
    monkeypatch.setattr(wpproc, "RESOLUTION_ARRAY", [(1920, 1080)])
    return cache


def test_active_profile_round_trip(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)

    data.write_active_profile("test")

    assert (cache / "running_profile").read_text(encoding="utf-8") == "test"
    assert data.read_active_profile().name == "test"


def test_active_profile_accepts_lf(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)
    (cache / "running_profile").write_text("test\n", encoding="utf-8")

    assert data.read_active_profile().name == "test"


def test_active_profile_accepts_crlf(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)
    (cache / "running_profile").write_bytes(b"test\r\n")

    assert data.read_active_profile().name == "test"


def test_active_profile_uses_first_record(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)
    (cache / "running_profile").write_text("test\nmissing\n", encoding="utf-8")

    assert data.read_active_profile().name == "test"


def test_empty_active_profile_returns_none(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)
    (cache / "running_profile").touch()

    assert data.read_active_profile() is None


def test_missing_pointer_reads_as_none_without_creating_it(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)

    assert data.read_active_profile() is None
    assert not (cache / "running_profile").exists()


def test_invalid_active_profile_pointer_is_rejected_without_rewrite(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)
    pointer = cache / "running_profile"
    original = b"../test\n"
    pointer.write_bytes(original)

    assert data.read_active_profile() is None
    assert pointer.read_bytes() == original


def test_pointer_resolves_a_profile_whose_name_line_differs(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)
    pointer = cache / "running_profile"
    pointer.write_text("test", encoding="utf-8")
    profiles = tmp_path / "profiles"
    (profiles / "test.profile").write_text("name=other\n", encoding="utf-8")

    assert data.read_active_profile().name == "test"
    assert pointer.read_text(encoding="utf-8") == "test"


def test_pointer_resolves_a_symlinked_profile(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)
    profiles = tmp_path / "profiles"
    target = tmp_path / "target.profile"
    target.write_bytes((profiles / "test.profile").read_bytes())
    (profiles / "test.profile").unlink()
    (profiles / "test.profile").symlink_to(target)
    (cache / "running_profile").write_text("test", encoding="utf-8")

    assert data.read_active_profile().name == "test"


def test_invalid_active_profile_write_does_not_touch_pointer(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)
    pointer = cache / "running_profile"
    pointer.write_text("test", encoding="utf-8")

    with pytest.raises(ProfileIdError):
        data.write_active_profile("../other")

    assert pointer.read_text(encoding="utf-8") == "test"


def test_active_profile_write_accepts_profile_id(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)

    data.write_active_profile(ProfileId("test"))

    assert (cache / "running_profile").read_text(encoding="utf-8") == "test"


def test_active_profile_write_never_replaces_a_directory(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)
    (cache / "running_profile").mkdir()

    with pytest.raises(OSError):
        data.write_active_profile("test")

    assert (cache / "running_profile").is_dir()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_active_profile_read_does_not_block_on_fifo(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)
    os.mkfifo(cache / "running_profile")

    assert data.read_active_profile() is None
