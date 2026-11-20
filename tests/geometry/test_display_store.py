"""The saved display layouts: written in one step, in the encoding older versions read."""

import configparser

import pytest

from superpaper import files
from superpaper.geometry import display_store
from superpaper.geometry.displays import Display, Layout
from superpaper.geometry.perspective import Perspective, Swivel, SwivelAxis, Tilt
from tests.geometry.conftest import (
    DISPLAY_SYSTEMS_DAT,
    DUAL_KEY,
    DUAL_MONITORS,
    DUAL_PERSP,
    LAPTOP_MONITORS,
    SAVED_COUCH,
    detect,
    edit_the_layout,
)

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

# A perspective typed by hand, or saved by an older version, holds whole numbers where
# the dialog writes floats; they must be written back as they were read.
WHOLE_NUMBER_PERSP = (
    "[wall]\ncentral_disp = 0\nviewer_pos = 0,0,2000\nswivels = 0,0,0,0;1,-25,40,20\ntilts = 0,0,0;5,8,0\n\n"
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
        .with_offsets([(0, 0), (2300, 50)])
        .with_bezels([(4.5, 1.25), (0.0, 3.0)])
        .with_diagonals([27.0, 23.75])
        .with_perspective(DESK, use_perspective=True, is_default=False)
        .with_perspective(couch, use_perspective=True, is_default=True)
    )

    display_store.save_layout(tmp_path, layout)
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

    display_store.save_layout(tmp_path, layout)

    assert (tmp_path / f"{layout.key}.persp").read_bytes().startswith(b"[caf\xe9]\n")
    assert display_store.load(tmp_path, DISPLAYS).perspectives == (cafe,)


def test_saving_an_unchanged_layout_is_byte_stable(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)
    dat = (saved_layouts / "display_systems.dat").read_bytes()
    persp = (saved_layouts / f"{DUAL_KEY}.persp").read_bytes()

    display_store.save_layout(saved_layouts, layout)

    # The laptop's section survives, and nothing drifts when the user saves without editing.
    assert (saved_layouts / "display_systems.dat").read_bytes() == dat
    assert (saved_layouts / f"{DUAL_KEY}.persp").read_bytes() == persp


def test_repeated_saves_are_byte_stable(monkeypatch, saved_layouts):
    for _ in range(3):
        display_store.save_layout(saved_layouts, detect(monkeypatch, saved_layouts, DUAL_MONITORS))

    assert (saved_layouts / "display_systems.dat").read_text(encoding="utf-8") == DISPLAY_SYSTEMS_DAT


def test_perspectives_with_whole_numbers_are_byte_stable(monkeypatch, tmp_path):
    persp_file = tmp_path / f"{DUAL_KEY}.persp"
    persp_file.write_text(WHOLE_NUMBER_PERSP, encoding="utf-8")

    layout = detect(monkeypatch, tmp_path, DUAL_MONITORS)
    display_store.save_layout(tmp_path, layout)

    assert persp_file.read_text(encoding="utf-8") == WHOLE_NUMBER_PERSP
    assert layout.perspectives[0].swivels[1] == Swivel(SwivelAxis.LEFT, -25, 40, 20)


@pytest.mark.parametrize(
    "broken",
    [
        WHOLE_NUMBER_PERSP.replace("0,0,2000", "0,0"),
        WHOLE_NUMBER_PERSP.replace("0,0,2000", "0,0,far"),
        WHOLE_NUMBER_PERSP.replace("1,-25,40,20", "3,-25,40,20"),
        WHOLE_NUMBER_PERSP.replace("5,8,0", "5,8"),
    ],
)
def test_a_perspective_that_is_not_made_of_numbers_is_refused(monkeypatch, tmp_path, broken):
    (tmp_path / f"{DUAL_KEY}.persp").write_text(broken, encoding="utf-8")

    with pytest.raises(ValueError):
        detect(monkeypatch, tmp_path, DUAL_MONITORS)


def test_a_fresh_layout_is_saved_with_float_bezels_as_earlier_versions_wrote_it(monkeypatch, tmp_path):
    layout = detect(monkeypatch, tmp_path, LAPTOP_MONITORS)

    display_store.save_layout(tmp_path, layout)

    assert "bezel_mms = 0.0,0.0\n" in (tmp_path / "display_systems.dat").read_text(encoding="utf-8")


def test_entered_diagonals_are_saved_as_entered(monkeypatch, tmp_path):
    layout = detect(monkeypatch, tmp_path, DUAL_MONITORS).with_diagonals([27.25, 23.75])

    display_store.save_layout(tmp_path, layout)
    reloaded = detect(monkeypatch, tmp_path, DUAL_MONITORS)

    assert reloaded.user_diagonal_inches == (27.25, 23.75)
    assert reloaded.ppi_norm_offsets == layout.ppi_norm_offsets


def test_saving_writes_the_perspectives_and_the_choice_with_the_layout(monkeypatch, saved_layouts):
    layout = edit_the_layout(detect(monkeypatch, saved_layouts, DUAL_MONITORS))
    layout = layout.without_perspective("desk").with_perspective(SAVED_COUCH, use_perspective=False, is_default=True)

    display_store.save_layout(saved_layouts, layout)

    dat = (saved_layouts / "display_systems.dat").read_text(encoding="utf-8")
    assert "use_perspective = 0\ndef_perspective = couch" in dat
    assert (saved_layouts / f"{DUAL_KEY}.persp").read_text(encoding="utf-8") == DUAL_PERSP[
        DUAL_PERSP.index("[couch]") :
    ]
    assert detect(monkeypatch, saved_layouts, DUAL_MONITORS) == layout


def test_no_perspective_file_is_made_for_a_layout_without_perspectives(monkeypatch, tmp_path):
    display_store.save_layout(tmp_path, detect(monkeypatch, tmp_path, LAPTOP_MONITORS))

    assert [path.name for path in tmp_path.iterdir()] == ["display_systems.dat"]


def test_a_layout_that_overlaps_is_never_saved(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)
    overlapping = layout.with_offsets([(0, 0), (10, 10)])
    dat = (saved_layouts / "display_systems.dat").read_bytes()

    with pytest.raises(ValueError, match="overlap"):
        display_store.save_layout(saved_layouts, overlapping)

    assert (saved_layouts / "display_systems.dat").read_bytes() == dat
    assert (
        display_store.save_or_failure(display_store.save_layout, saved_layouts, overlapping, "display settings")
        is not None
    )


def test_saving_replaces_a_layout_file_that_cannot_be_read_keeping_the_old_one_aside(
    monkeypatch, saved_layouts, caplog
):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS).without_perspective("couch")
    (saved_layouts / "display_systems.dat").write_text("no section header\n", encoding="utf-8")
    (saved_layouts / "display_systems.dat.corrupt").write_text("an earlier one\n", encoding="utf-8")
    with pytest.raises(configparser.Error):
        detect(monkeypatch, saved_layouts, DUAL_MONITORS)

    display_store.save_layout(saved_layouts, layout)

    assert detect(monkeypatch, saved_layouts, DUAL_MONITORS) == layout
    assert (saved_layouts / "display_systems.dat.corrupt").read_text(encoding="utf-8") == "no section header\n"
    assert "display_systems.dat.corrupt" in caplog.text


def test_saving_keeps_a_perspective_file_that_cannot_be_read_aside(monkeypatch, saved_layouts, caplog):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)
    persp = saved_layouts / f"{DUAL_KEY}.persp"
    persp.write_text("[desk]\ncentral_disp = x\n", encoding="utf-8")

    display_store.save_layout(saved_layouts, layout)

    assert (saved_layouts / f"{DUAL_KEY}.persp.corrupt").read_text(encoding="utf-8") == "[desk]\ncentral_disp = x\n"
    assert detect(monkeypatch, saved_layouts, DUAL_MONITORS) == layout
    assert ".persp.corrupt" in caplog.text


def test_a_saved_layout_whose_displays_overlap_does_not_load(monkeypatch, tmp_path):
    key = Layout.initial(DISPLAYS).key
    (tmp_path / display_store.LAYOUTS_FILE).write_text(
        f"[{key}]\nppi_norm_offsets = 0,0;10,10\nbezel_mms = 0.0,0.0;0.0,0.0\n"
        "user_diagonal_inches = None\nuse_perspective = 1\ndef_perspective = None\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="overlap"):
        display_store.load(tmp_path, DISPLAYS)


def test_a_layout_that_can_be_used_loads_without_a_problem(tmp_path):
    display_store.save_layout(tmp_path, LAYOUT)

    assert display_store.load_or_default(tmp_path, DISPLAYS) == display_store.LoadedLayout(
        display_store.load(tmp_path, DISPLAYS), None
    )


@pytest.mark.parametrize(
    ("file_name", "text"),
    [
        (display_store.LAYOUTS_FILE, "no section header\n"),
        (display_store.LAYOUTS_FILE, "[{key}]\nppi_norm_offsets = 0,0;10,10\n"),
        (
            display_store.LAYOUTS_FILE,
            "[{key}]\nppi_norm_offsets = 0,0;10,10\nbezel_mms = 0,0;0,0\nuser_diagonal_inches = None\n",
        ),
        ("{key}.persp", "[desk]\ncentral_disp = zero\n"),
    ],
    ids=["no-section", "missing-values", "overlapping", "corrupt-perspective"],
)
def test_files_that_cannot_be_used_give_the_default_arrangement_and_stay_as_they_are(tmp_path, file_name, text):
    default = Layout.initial(DISPLAYS)
    path = tmp_path / file_name.format(key=default.key)
    path.write_text(text.format(key=default.key), encoding="utf-8")
    before = path.read_bytes()

    loaded = display_store.load_or_default(tmp_path, DISPLAYS)

    assert loaded.layout == default
    assert "can't be used" in loaded.problem
    assert path.read_bytes() == before
