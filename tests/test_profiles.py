"""A loaded profile's selection: how many images it has, which it starts from, and that
loading a profile doesn't list its sources."""

import pytest

from superpaper import selection
from tests.conftest import write_profile


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
def test_a_selection_has_one_image_per_display_group_or_profile(
    profile_modules, app_paths, tmp_path, spanmode, extra, sources, size
):
    data, _ = profile_modules
    images = [tmp_path / f"{name}.png" for name in "abc"]
    for image in images:
        image.touch()
    profile_path = write_profile(app_paths.profiles / "test.profile", spanmode=spanmode, sources=images[:sources])
    with profile_path.open("a", encoding="utf-8") as profile_file:
        profile_file.write(extra)

    stored = data.open_profile(app_paths, "test")

    assert stored.profile.selection_size == size
    assert len(stored.selection.advance()) == size


def test_a_selection_written_by_an_older_version_is_the_starting_point(profile_modules, app_paths, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "selected.png"
    image.touch()
    write_profile(app_paths.profiles / "test.profile", sources=[tmp_path], selected=[image])

    assert data.open_profile(app_paths, "test").selection.images == [str(image)]


@pytest.mark.parametrize(("stored", "images"), [("[]", None), ('["/remembered.png"]', ["/remembered.png"])])
def test_a_remembered_selection_supersedes_an_older_versions(profile_modules, app_paths, tmp_path, stored, images):
    data, _ = profile_modules
    selection_file = app_paths.cache / "selections" / "test.json"
    selection_file.parent.mkdir()
    selection_file.write_text(stored, encoding="utf-8")
    write_profile(app_paths.profiles / "test.profile", sources=[tmp_path], selected=[tmp_path / "old.png"])

    assert data.open_profile(app_paths, "test").selection.images == images


def test_loading_profiles_lists_no_sources(profile_modules, app_paths, tmp_path, monkeypatch):
    data, _ = profile_modules
    sources = tmp_path / "wallpapers"
    sources.mkdir()
    (sources / "a.png").touch()
    for name in ("one", "two"):
        write_profile(app_paths.profiles / f"{name}.profile", sources=[sources])
    listed = []
    real_listdir = selection.os.listdir
    monkeypatch.setattr(selection.os, "listdir", lambda path: listed.append(path) or real_listdir(path))

    loaded = data.list_profiles(app_paths)

    assert [stored.profile.name for stored in loaded] == ["one", "two"]
    assert listed == []
    assert loaded[0].selection.current() == [str(sources / "a.png")]
    assert listed == [str(sources)]
