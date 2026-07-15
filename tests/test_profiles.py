from tests.conftest import write_profile


def test_missing_persisted_selection_falls_back_to_source(profile_modules, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "available.png"
    image.touch()
    profile_path = write_profile(
        tmp_path / "test.profile",
        sources=[image],
        selected=[tmp_path / "deleted.png"],
    )

    profile = data.ProfileData(profile_path)

    assert profile.next_wallpaper_files(peek=True) == [str(image)]
    assert profile.selected is None
    assert "selected=" not in profile_path.read_text(encoding="utf-8")


def test_selection_return_is_a_copy(profile_modules, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "selected.png"
    image.touch()
    profile = data.ProfileData(write_profile(tmp_path / "test.profile", sources=[image], selected=[image]))

    selected = profile.next_wallpaper_files()
    selected.clear()

    assert profile.selected == [str(image)]


def test_multi_selection_is_atomic_when_a_monitor_has_no_images(profile_modules, tmp_path):
    data, _ = profile_modules
    first = tmp_path / "first.png"
    first.touch()
    empty = tmp_path / "empty"
    empty.mkdir()
    profile = data.ProfileData(write_profile(tmp_path / "test.profile", spanmode="multi", sources=[first, empty]))

    assert profile.advance_wallpaper() == []
    assert profile.selected is None


def test_clearing_selection_removes_persisted_line(profile_modules, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "selected.png"
    image.touch()
    profile_path = write_profile(tmp_path / "test.profile", sources=[image], selected=[image])
    profile = data.ProfileData(profile_path)

    profile.set_selected_wallpaper(None)

    assert "selected=" not in profile_path.read_text(encoding="utf-8")


def test_grouped_profile_requires_one_selection_per_group(profile_modules, tmp_path):
    data, _ = profile_modules
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.touch()
    second.touch()
    profile_path = write_profile(tmp_path / "test.profile", spanmode="advanced", sources=[first], selected=[first])
    with profile_path.open("a", encoding="utf-8") as profile_file:
        profile_file.write("spangroups=0,1\n")
    profile = data.ProfileData(profile_path)

    assert profile.has_valid_selection() is False
    profile.set_selected_wallpaper([str(first), str(second)], persist=False)
    assert profile.has_valid_selection() is True


def test_advance_replaces_duplicate_multi_selection(profile_modules, tmp_path):
    data, _ = profile_modules
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.touch()
    second.touch()
    profile_path = write_profile(
        tmp_path / "test.profile",
        spanmode="multi",
        sources=[tmp_path, tmp_path],
        selected=[first, first],
    )
    profile = data.ProfileData(profile_path)

    assert profile.next_wallpaper_files() == [str(first), str(first)]
    advanced = profile.advance_wallpaper()

    assert len(set(advanced)) == 2
    assert "selected=" + ";".join(advanced) in profile_path.read_text(encoding="utf-8")
