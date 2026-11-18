"""The saved display layouts: written in one step, in the encoding older versions read."""

import pytest

from superpaper import files
from superpaper.geometry import display_store
from superpaper.geometry.displays import Display, Layout
from superpaper.geometry.perspective import Perspective, Swivel, SwivelAxis, Tilt

DISPLAYS = (
    Display((1920, 1080), (0, 0), (527, 296), False, "left"),
    Display((1920, 1080), (1920, 0), (527, 296), False, "right"),
)
OTHER_DISPLAYS = (Display((2560, 1440), (0, 0), (597, 336), False, "only"),)
LAYOUT = Layout.initial(DISPLAYS).with_bezels([(4.5, 0.0), (0.0, 0.0)])
DESK = Perspective(
    "desk",
    0,
    (0.0, 0.0, 2000.0),
    (Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0),) * 2,
    (Tilt(0.0, 0.0, 0.0),) * 2,
)


def test_nothing_saved_reads_as_the_initial_layout(tmp_path):
    assert display_store.load(tmp_path, DISPLAYS) == Layout.initial(DISPLAYS)


def test_a_layout_reads_back_as_it_was_saved(tmp_path):
    other = Layout.initial(OTHER_DISPLAYS)
    display_store.save_layout(tmp_path, LAYOUT)
    display_store.save_layout(tmp_path, other)

    assert display_store.load(tmp_path, DISPLAYS).bezels_in_mm() == LAYOUT.bezels_in_mm()
    assert display_store.load(tmp_path, OTHER_DISPLAYS) == other


def test_every_saved_field_of_a_layout_and_its_perspectives_reads_back(tmp_path):
    couch = Perspective("couch", 1, (-5.5, 1.0, 900.0), DESK.swivels, DESK.tilts)
    layout = (
        Layout.initial(DISPLAYS)
        .with_offsets([(0, 0), (2000, 50)])
        .with_bezels([(4.5, 1.25), (0.0, 3.0)])
        .with_diagonals([27.0, 23.75])
        .with_perspective(DESK, use_perspective=True, is_default=False)
        .with_perspective(couch, use_perspective=True, is_default=True)
    )

    display_store.save_layout(tmp_path, layout)
    display_store.save_perspective_choice(tmp_path, layout)
    loaded = display_store.load(tmp_path, DISPLAYS)

    assert loaded.ppi_norm_offsets == layout.ppi_norm_offsets
    assert loaded.bezels_in_mm() == [(4.5, 1.25), (0.0, 3.0)]
    assert loaded.user_diagonal_inches == (27.0, 23.75)
    assert loaded.use_perspective is True
    assert loaded.default_perspective == "couch"
    assert loaded.perspectives == layout.perspectives == (DESK, couch)
    assert loaded == layout


def test_a_failed_save_leaves_the_saved_layouts_as_they_were(tmp_path, monkeypatch):
    display_store.save_layout(tmp_path, LAYOUT)
    saved = (tmp_path / display_store.LAYOUTS_FILE).read_bytes()

    def fail(source, target):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(files.os, "replace", fail)
    with pytest.raises(OSError, match="No space left"):
        display_store.save_layout(tmp_path, Layout.initial(OTHER_DISPLAYS))

    assert (tmp_path / display_store.LAYOUTS_FILE).read_bytes() == saved
    assert sorted(path.name for path in tmp_path.iterdir()) == [display_store.LAYOUTS_FILE]


def test_the_files_use_the_encoding_older_versions_read(tmp_path, monkeypatch):
    # Python's default text encoding, which is the ANSI code page on Windows.
    monkeypatch.setattr(display_store.locale, "getpreferredencoding", lambda do_setlocale=True: "cp1252")
    cafe = Perspective("café", 0, (0.0, 0.0, 2000.0), DESK.swivels, DESK.tilts)
    layout = LAYOUT.with_perspective(cafe, use_perspective=True, is_default=False)

    display_store.save_perspective_choice(tmp_path, layout)

    assert (tmp_path / f"{layout.key}.persp").read_bytes().startswith(b"[caf\xe9]\n")
    assert display_store.load(tmp_path, DISPLAYS).perspectives == (cafe,)
