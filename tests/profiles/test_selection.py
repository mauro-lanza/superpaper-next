"""Which images a profile shows now and which come next: the order, the selection, and
when the sources are listed."""

from pathlib import Path

import pytest

from superpaper.profiles import selection
from superpaper.profiles.selection import Selection
from tests.conftest import load_profile, write_profile


def test_first_image_of_a_folder_is_first_by_name_among_supported(tmp_path):
    touch(tmp_path / "a.txt", tmp_path / "c.PNG", tmp_path / "b.jpg")

    assert selection.first_image(str(tmp_path)) == str(tmp_path / "b.jpg")


def test_first_image_of_a_file_is_the_file_and_of_nothing_is_none(tmp_path):
    (path,) = touch(tmp_path / "x.txt")

    assert selection.first_image(path) == path
    assert selection.first_image(str(tmp_path)) is None
    assert selection.first_image(str(tmp_path / "gone")) is None


def test_first_image_of_an_unreadable_folder_is_none_and_logged(tmp_path, monkeypatch, caplog):
    def refuse(path):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(selection.os, "listdir", refuse)

    assert selection.first_image(str(tmp_path)) is None
    assert "could not be listed" in caplog.text


def touch(*paths):
    for path in paths:
        path.touch()
    return [str(path) for path in paths]


@pytest.fixture
def remembered():
    """What a selection remembers, in order."""
    return []


def test_a_source_without_images_leaves_every_position_without_one(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (image,) = touch(tmp_path / "second.png")

    assert Selection([[str(empty)], [image]], "alphabetical", 2).advance() == []
    assert Selection([[image], [str(empty)]], "alphabetical", 2).advance() == []


def test_a_new_image_joins_the_slideshow_when_the_cycle_starts_again(tmp_path):
    a, b = touch(tmp_path / "a.png", tmp_path / "b.png")
    images = Selection([[str(tmp_path)]], "alphabetical", 1)
    assert [images.advance(), images.advance()] == [[a], [b]]

    (c,) = touch(tmp_path / "c.png")

    assert [images.advance() for _ in range(3)] == [[a], [b], [c]]


def test_an_image_deleted_after_listing_is_skipped(tmp_path):
    first, second = touch(tmp_path / "a.png", tmp_path / "b.png")
    images = Selection([[str(tmp_path)]], "alphabetical", 1)
    assert images.current() == [first]

    (tmp_path / "a.png").unlink()

    assert images.advance() == [second]


def test_identical_sources_avoid_showing_an_image_twice(tmp_path):
    a, b, c = touch(tmp_path / "a.png", tmp_path / "b.png", tmp_path / "c.png")
    images = Selection([[str(tmp_path)], [str(tmp_path)]], "alphabetical", 2)

    batches = [images.advance() for _ in range(4)]

    assert batches == [[a, b], [b, c], [c, a], [a, b]]


def test_the_matching_avoids_a_greedy_duplicate(tmp_path):
    first, second = touch(tmp_path / "a.png", tmp_path / "b.png")

    assert Selection([[first, second], [first]], "alphabetical", 2).advance() == [second, first]


def test_duplicates_are_shown_when_they_cant_be_avoided(tmp_path):
    touch(tmp_path / "a.png", tmp_path / "b.png")

    batch = Selection([[str(tmp_path)]] * 3, "alphabetical", 3).advance()

    assert len(batch) == 3
    assert len(set(batch)) == 2


def test_a_peek_repeats_until_the_images_are_taken(tmp_path):
    touch(tmp_path / "a.png", tmp_path / "b.png", tmp_path / "c.png")
    images = Selection([[str(tmp_path)], [str(tmp_path)]], "alphabetical", 2)

    first_peek = images.current()
    first_peek.clear()
    second_peek = images.current()

    assert images.advance() == second_peek
    assert images.advance() != second_peek


def test_a_symlink_and_its_target_are_one_image(tmp_path):
    (image,) = touch(tmp_path / "image.png")
    alias = tmp_path / "alias.png"
    alias.symlink_to(image)
    images = Selection([[image, str(alias)]], "alphabetical", 1)

    assert [images.advance(), images.advance()] == [[image], [image]]


def test_sources_are_listed_only_when_images_are_needed(tmp_path, monkeypatch):
    touch(tmp_path / "a.png")
    listed = []
    real_listdir = selection.os.listdir
    monkeypatch.setattr(selection.os, "listdir", lambda path: listed.append(path) or real_listdir(path))

    images = Selection([[str(tmp_path)]], "alphabetical", 1)
    assert listed == []

    images.current()
    images.advance()
    assert listed == [str(tmp_path)]


def test_missing_and_unreadable_sources_are_logged(tmp_path, monkeypatch, caplog):
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    real_listdir = selection.os.listdir

    def listdir(path):
        if path == str(unreadable):
            raise PermissionError(13, "Permission denied")
        return real_listdir(path)

    monkeypatch.setattr(selection.os, "listdir", listdir)
    (image,) = touch(tmp_path / "a.png")

    assert Selection([[str(tmp_path / "gone"), str(unreadable), image]], "alphabetical", 1).advance() == [image]
    assert "A source was not found" in caplog.text
    assert "could not be listed" in caplog.text


def test_a_peek_falls_back_to_the_sources_without_forgetting_the_selection(tmp_path, remembered):
    (image,) = touch(tmp_path / "available.png")
    unmounted = str(tmp_path / "unmounted.png")
    images = Selection([[image]], "alphabetical", 1, images=[unmounted], remember=remembered.append)

    assert images.current() == [image]
    assert images.images == [unmounted]
    assert remembered == []


def test_a_peek_names_the_selected_images_it_passed_over(tmp_path):
    (image,) = touch(tmp_path / "available.png")
    gone = str(tmp_path / "unmounted.png")
    images = Selection([[image]], "alphabetical", 1, images=[gone])

    assert images.current() == [image]
    assert images.take_skipped() == [gone]
    assert images.take_skipped() == []


def test_advancing_names_the_images_deleted_since_listing(tmp_path):
    first, second = touch(tmp_path / "a.png", tmp_path / "b.png")
    images = Selection([[first, second]], "alphabetical", 1)
    assert images.current() == [first]
    (tmp_path / "a.png").unlink()

    assert images.advance() == [second]
    assert images.take_skipped() == [first]


def test_advancing_replaces_a_selection_whose_images_are_gone(tmp_path, remembered):
    (image,) = touch(tmp_path / "available.png")
    images = Selection([[image]], "alphabetical", 1, images=[str(tmp_path / "gone.png")], remember=remembered.append)

    assert images.advance() == [image]
    assert images.images == [image]
    assert remembered == [[image]]


def test_the_selection_returned_is_a_copy(tmp_path):
    (image,) = touch(tmp_path / "selected.png")
    images = Selection([[image]], "alphabetical", 1, images=[image])

    images.current().clear()
    images.images.clear()

    assert images.images == [image]


def test_a_selection_needs_an_image_for_every_position(tmp_path, remembered):
    first, second = touch(tmp_path / "first.png", tmp_path / "second.png")
    images = Selection([[first], [second]], "alphabetical", 2, images=[first], remember=remembered.append)

    assert images.is_complete() is False
    images.pin([first, second])
    assert images.is_complete() is True
    assert remembered == [[first, second]]


def test_an_incomplete_batch_changes_nothing(tmp_path, remembered):
    (first,) = touch(tmp_path / "first.png")
    empty = tmp_path / "empty"
    empty.mkdir()
    images = Selection([[first], [str(empty)]], "alphabetical", 2, remember=remembered.append)

    assert images.advance() == []
    assert images.images is None
    assert remembered == []


def test_clearing_the_selection_is_remembered(tmp_path, remembered):
    (image,) = touch(tmp_path / "selected.png")
    images = Selection([[image]], "alphabetical", 1, images=[image], remember=remembered.append)

    images.pin(None)

    assert images.images is None
    assert remembered == [[]]


def test_advancing_replaces_a_duplicate_selection(tmp_path, remembered):
    first, _second = touch(tmp_path / "a.png", tmp_path / "b.png")
    images = Selection([[str(tmp_path)], [str(tmp_path)]], "alphabetical", 2, images=[first, first])

    assert images.current() == [first, first]
    assert len(set(images.advance())) == 2


@pytest.mark.parametrize("sortmode", ["shuffle", "date_seeded_shuffle", "alphabetical"])
def test_two_positions_never_show_the_same_file_while_there_are_others_however_the_order_is_arranged(
    tmp_path, sortmode
):
    originals = tmp_path / "originals"
    links = tmp_path / "links"
    originals.mkdir()
    links.mkdir()
    for name in "abcdefgh":
        original = originals / f"{name}.png"
        original.touch()
        (links / f"{name}.png").symlink_to(original)
    images = Selection([[str(originals)], [str(links)]], sortmode, 2)

    for _ in range(24):
        first, second = images.advance()
        assert Path(first).resolve() != Path(second).resolve()


@pytest.mark.parametrize(("name", "supported"), [("photo.JPG", True), ("photo.webp", True), ("notes.txt", False)])
def test_supported_images_are_recognised_by_extension_in_any_case(name, supported):
    assert selection.is_supported_image(name) is supported


@pytest.mark.parametrize(
    ("spanmode", "extra", "sources", "size"),
    [
        ("single", "", 1, 1),
        ("advanced", "", 1, 1),
        ("advanced", "spangroups=0,1\n", 2, 2),
        # One image per configured source: how many displays are connected now is the
        # renderer's concern, not the selection's.
        ("multi", "", 3, 3),
    ],
)
def test_a_selection_has_one_image_per_display_group_or_profile(app_paths, tmp_path, spanmode, extra, sources, size):
    images = [tmp_path / f"{name}.png" for name in "abc"]
    for image in images:
        image.touch()
    profile_path = write_profile(app_paths.profiles / "test.profile", spanmode=spanmode, sources=images[:sources])
    with profile_path.open("a", encoding="utf-8") as profile_file:
        profile_file.write(extra)

    stored = load_profile(app_paths, "test")

    assert stored.profile.selection_size == size
    assert len(stored.selection.advance()) == size


def test_a_selection_written_by_an_older_version_is_the_starting_point(app_paths, tmp_path):
    image = tmp_path / "selected.png"
    image.touch()
    write_profile(app_paths.profiles / "test.profile", sources=[tmp_path], selected=[image])

    assert load_profile(app_paths, "test").selection.images == [str(image)]


@pytest.mark.parametrize(("stored", "images"), [("[]", None), ('["/remembered.png"]', ["/remembered.png"])])
def test_a_remembered_selection_supersedes_an_older_versions(app_paths, tmp_path, stored, images):
    selection_file = app_paths.cache / "selections" / "test.json"
    selection_file.parent.mkdir()
    selection_file.write_text(stored, encoding="utf-8")
    write_profile(app_paths.profiles / "test.profile", sources=[tmp_path], selected=[tmp_path / "old.png"])

    assert load_profile(app_paths, "test").selection.images == images
