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


def test_missing_active_profile_file_is_created(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    cache = prepare_profile(data, wpproc, monkeypatch, tmp_path)

    assert data.read_active_profile() is None
    assert (cache / "running_profile").is_file()
