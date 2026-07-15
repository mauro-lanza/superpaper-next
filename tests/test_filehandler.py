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


def test_identical_pools_avoid_duplicates(profile_modules, tmp_path):
    data, _ = profile_modules
    images = []
    for name in ("a.png", "b.png", "c.png"):
        image = tmp_path / name
        image.touch()
        images.append(str(image))
    handler = data.ProfileData.Filehandler([[str(tmp_path)], [str(tmp_path)]], "alphabetical")

    batches = [handler.next_wallpaper_files() for _ in range(4)]

    assert batches == [
        [images[0], images[1]],
        [images[1], images[2]],
        [images[2], images[0]],
        [images[0], images[1]],
    ]
    assert all(len(set(batch)) == 2 for batch in batches)


def test_matching_avoids_greedy_duplicate(profile_modules, tmp_path):
    data, _ = profile_modules
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.touch()
    second.touch()
    handler = data.ProfileData.Filehandler(
        [[str(first), str(second)], [str(first)]],
        "alphabetical",
    )

    assert handler.next_wallpaper_files() == [str(second), str(first)]


def test_collision_search_wraps_across_cycle_boundary(profile_modules, tmp_path):
    data, _ = profile_modules
    for name in ("a.png", "b.png", "c.png"):
        (tmp_path / name).touch()
    handler = data.ProfileData.Filehandler([[str(tmp_path)], [str(tmp_path)]], "alphabetical")
    for iterable in handler.iterators:
        iterable.counter = 2

    batch = handler.next_wallpaper_files()

    assert len(set(batch)) == 2
    assert str(tmp_path / "c.png") in batch


def test_duplicates_are_allowed_when_unavoidable(profile_modules, tmp_path):
    data, _ = profile_modules
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.touch()
    second.touch()
    handler = data.ProfileData.Filehandler([[str(tmp_path)]] * 3, "alphabetical")

    batch = handler.next_wallpaper_files()

    assert len(batch) == 3
    assert len(set(batch)) == 2


def test_peek_is_repeatable_and_consumed_once(profile_modules, tmp_path):
    data, _ = profile_modules
    for name in ("a.png", "b.png", "c.png"):
        (tmp_path / name).touch()
    handler = data.ProfileData.Filehandler([[str(tmp_path)], [str(tmp_path)]], "alphabetical")

    first_peek = handler.next_wallpaper_files(peek=True)
    first_peek.clear()
    second_peek = handler.next_wallpaper_files(peek=True)

    assert second_peek == handler.next_wallpaper_files()
    assert handler.next_wallpaper_files() != second_peek


def test_symlink_and_real_path_share_identity(profile_modules, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "image.png"
    image.touch()
    alias = tmp_path / "alias.png"
    alias.symlink_to(image)
    handler = data.ProfileData.Filehandler([[str(image), str(alias)]], "alphabetical")

    assert handler.all_files_in_paths == [[str(image)]]
