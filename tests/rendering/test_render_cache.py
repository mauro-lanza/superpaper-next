"""Rendered wallpapers on disk: kept in turns, found by their exact names, and swept."""

import os

import pytest
from PIL import Image

from superpaper.rendering import render_cache
from superpaper.rendering.render_cache import Slot
from tests.conftest import TINY_DISPLAYS, pixels


def names(directory):
    return sorted(path.name for path in directory.iterdir())


def touch(directory, *filenames, modified=None):
    for filename in filenames:
        path = directory / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        if modified is not None:
            os.utime(path, ns=(modified, modified))


def test_renders_take_turns_so_the_one_on_screen_is_never_rewritten(tmp_path):
    work = Slot(tmp_path, "work")
    image = Image.new("RGB", (5, 3), (10, 20, 30))

    first = render_cache.save(work, image, extension="png", signature="s")
    second = render_cache.save(work, image, extension="png", signature="s")
    assert names(tmp_path) == ["work-a.png", "work-a.png.sig", "work-b.png", "work-b.png.sig"]
    render_cache.forget_previous(second)
    third = render_cache.save(work, image, extension="png", signature="s")
    render_cache.forget_previous(third)

    assert (first.name, second.name, third.name) == ("work-a.png", "work-b.png", "work-a.png")
    assert names(tmp_path) == ["work-a.png", "work-a.png.sig"]
    with Image.open(third) as saved:
        assert (saved.format, saved.size, saved.getpixel((4, 2))) == ("PNG", (5, 3), (10, 20, 30))


@pytest.mark.parametrize(("newer", "older"), [("a", "b"), ("b", "a")])
def test_the_next_render_replaces_the_older_one(tmp_path, newer, older):
    touch(tmp_path, f"work-{newer}.png", modified=2_000_000_000)
    touch(tmp_path, f"work-{older}.png", modified=1_000_000_000)

    saved = render_cache.save(Slot(tmp_path, "work"), Image.new("RGB", (1, 1)), extension="png", signature="s")

    assert saved.name == f"work-{older}.png"


def test_a_new_render_leaves_none_of_the_pieces_of_the_one_it_replaces(tmp_path, display_layout):
    touch(tmp_path, "work-a.png", modified=2_000_000_000)
    touch(tmp_path, "work-b.png", "work-b-crop-0.png", "work-b-crop-1.png", "work-b-crop-2.png", modified=1_000_000_000)
    work = Slot(tmp_path, "work")

    saved = render_cache.save(work, Image.new("RGB", (5, 3)), extension="png", signature="s")
    pieces = render_cache.cut_pieces(saved, display_layout(TINY_DISPLAYS))

    latest = render_cache.latest(work)
    assert latest is not None
    assert latest.pieces == tuple(pieces)
    assert len(pieces) == 2


def test_a_render_whose_signature_was_not_written_is_unknown(tmp_path):
    touch(tmp_path, "work-a.jpg", modified=2_000_000_000)
    touch(tmp_path, "work-b.jpg", "work-b.jpg.sig", modified=1_000_000_000)
    (tmp_path / "work-b.jpg.sig").write_text("old", encoding="utf-8")
    transparent = Image.new("RGBA", (1, 1))  # JPEG can't hold it: the save stops before the signature

    with pytest.raises(OSError, match="RGBA"):
        render_cache.save(Slot(tmp_path, "work"), transparent, extension="jpg", signature="new")

    assert not (tmp_path / "work-b.jpg.sig").exists()


def test_renders_are_saved_with_the_given_extension(tmp_path):
    saved = render_cache.save(Slot(tmp_path, "work"), Image.new("RGB", (5, 3)), extension="jpg", signature="s")

    assert saved.name == "work-a.jpg"
    with Image.open(saved) as image:
        assert image.format == "JPEG"


def test_drafts_are_kept_apart_from_the_profiles(tmp_path):
    saved = render_cache.save(
        render_cache.draft_slot(tmp_path), Image.new("RGB", (5, 3)), extension="png", signature="s"
    )

    assert saved == tmp_path / "preview" / "draft-a.png"
    assert names(tmp_path) == ["preview"]


def test_a_render_is_cut_into_one_image_per_display(tmp_path, display_layout):
    desktop = tmp_path / "p-a.png"
    with Image.new("RGB", (5, 3)) as image:
        image.putdata([(x, y, 0) for y in range(3) for x in range(5)])
        image.save(desktop)

    pieces = render_cache.cut_pieces(desktop, display_layout(TINY_DISPLAYS))

    assert pieces == [tmp_path / "p-a-crop-0.png", tmp_path / "p-a-crop-1.png"]
    with Image.open(pieces[0]) as first, Image.open(pieces[1]) as second:
        assert pixels(first) == [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
        assert pixels(second) == [(3, 1, 0), (4, 1, 0), (3, 2, 0), (4, 2, 0)]


def test_files_are_matched_by_their_exact_names(tmp_path):
    touch(tmp_path, "work-a.png", "work-b.png", "work-b-crop-0.png")
    # Other profiles' renders whose names merely start or end alike, and a file that
    # isn't a render at all.
    others = ["homework-b-crop-0.png", "network-b.png", "work-a-b.png", "work-a-a-crop-0.png", "work-backup.png"]
    touch(tmp_path, *others)

    render_cache.forget_previous(tmp_path / "work-a.png")

    assert names(tmp_path) == sorted(["work-a.png", *others])


def test_the_latest_render_comes_with_its_pieces_in_display_order(tmp_path):
    touch(tmp_path, "work-a.png", "work-a-crop-0.png", modified=1_000_000_000)
    pieces = [f"work-b-crop-{index}.png" for index in range(12)]
    touch(tmp_path, "work-b.png", *pieces, modified=2_000_000_000)
    (tmp_path / "work-b.png.sig").write_text("what it was made from", encoding="utf-8")
    touch(tmp_path, "plain-a.png")

    latest = render_cache.latest(Slot(tmp_path, "work"))

    assert latest == render_cache.Rendered(
        tmp_path / "work-b.png", tuple(tmp_path / piece for piece in pieces), "what it was made from"
    )
    assert render_cache.latest(Slot(tmp_path, "home")) is None
    unsigned = render_cache.latest(Slot(tmp_path, "plain"))
    assert unsigned is not None
    assert unsigned.signature is None


def test_the_sweep_removes_only_renders_of_profiles_that_are_gone(tmp_path):
    kept = ["main2-a.png", "main2-a.png.sig", "main2-a-crop-0.png", "log", "running_profile", "notes.txt"]
    gone = ["main_2-a.png", "main_2-a.png.sig", "main-b-crop-1.png", "cli-b.png", "cli-b-crop-0.png"]
    touch(tmp_path, *kept, *gone, "selections/main2.json", "preview/draft-a.png")

    render_cache.sweep(tmp_path, ["main2"])

    assert names(tmp_path) == sorted([*kept, "preview", "selections"])
    assert names(tmp_path / "preview") == ["draft-a.png"]


def test_sweeping_a_missing_directory_does_nothing(tmp_path):
    render_cache.sweep(tmp_path / "missing", [])
