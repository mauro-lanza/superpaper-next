def test_empty_monitor_source_does_not_shift_later_images(profile_modules, tmp_path):
    data, _ = profile_modules
    empty = tmp_path / "empty"
    empty.mkdir()
    image = tmp_path / "second.png"
    image.touch()

    handler = data.ProfileData.Filehandler([[str(empty)], [str(image)]], "alphabetical")

    assert handler.next_wallpaper_files() == []


def test_empty_later_source_does_not_consume_earlier_monitor(profile_modules, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "first.png"
    image.touch()
    empty = tmp_path / "empty"
    empty.mkdir()
    handler = data.ProfileData.Filehandler([[str(image)], [str(empty)]], "alphabetical")

    assert handler.next_wallpaper_files() == []
    assert handler.iterators[0].counter == 0


def test_deleted_indexed_file_reinitializes(profile_modules, tmp_path):
    data, _ = profile_modules
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.touch()
    second.touch()
    handler = data.ProfileData.Filehandler([[str(tmp_path)]], "alphabetical")
    first.unlink()

    assert handler.next_wallpaper_files() == [str(second)]
