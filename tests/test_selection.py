"""Which images a profile shows now and which come next: the order, the selection, and
when the sources are listed."""

import pytest

from superpaper import selection
from superpaper.selection import Selection


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


@pytest.mark.parametrize(("name", "supported"), [("photo.JPG", True), ("photo.webp", True), ("notes.txt", False)])
def test_supported_images_are_recognised_by_extension_in_any_case(name, supported):
    assert selection.is_supported_image(name) is supported
