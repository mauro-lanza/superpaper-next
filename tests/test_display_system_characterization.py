"""Display layouts as Superpaper v2.3.2 saved them.

display_systems.dat and the <key>.persp files hold the users' most hand-tuned data:
positions, bezels, diagonal overrides and perspectives. Their key is CPython's hash of
a tuple of ints describing the monitors, so anything that lets a string or a float into
that hash, or a CPython that hashes tuples differently, would silently orphan every
user's layout (L1). These tests pin the key, both formats and the loaded geometry.

The file contents below were written by v2.3.2's own DisplaySystem for the monitors
below: a laptop whose physical size wasn't detected, then the two-monitor setup after
the user overrode both diagonals, entered a 10.5 mm bezel, dragged the second display
and saved two perspectives.
"""

import configparser
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from superpaper import display_detection, display_store
from superpaper.perspective import Default, Disabled, Named, Perspective, Swivel, SwivelAxis, Tilt


def monitor(x, y, width, height, width_mm, height_mm, name):
    return SimpleNamespace(x=x, y=y, width=width, height=height, width_mm=width_mm, height_mm=height_mm, name=name)


DUAL_MONITORS = [
    monitor(0, 0, 2560, 1440, 597, 336, "DP-1"),
    monitor(2560, 180, 1920, 1080, 527, 296, "HDMI-A-1"),
]
LAPTOP_MONITORS = [monitor(0, 0, 1920, 1080, None, None, "eDP-1")]
DUAL_KEY = "-2922184207299240822"
LAPTOP_KEY = "-1452157571017387289"

DISPLAY_SYSTEMS_DAT = (
    "[-1452157571017387289]\n"
    "ppi_norm_offsets = 0,0\n"
    "bezel_mms = 0.0,0.0\n"
    "user_diagonal_inches = 15.6\n"
    "use_perspective = 1\n"
    "def_perspective = None\n"
    "\n"
    "[-2922184207299240822]\n"
    "ppi_norm_offsets = 0,0;2605.7204000891693,98.49418762870297\n"
    "bezel_mms = 10.5,0.0;0.0,0.0\n"
    "user_diagonal_inches = 27.0,23.8\n"
    "use_perspective = 1\n"
    "def_perspective = desk\n"
    "\n"
)
DUAL_PERSP = (
    "[desk]\n"
    "central_disp = 0\n"
    "viewer_pos = 0.0,0.0,2783.8819102818975\n"
    "swivels = 0,0.0,0.0,0.0;1,-25.0,42.828952465875346,21.414476232937673\n"
    "tilts = 0.0,0.0,0.0;4.5,8.565790493175069,0.0\n"
    "\n"
    "[couch]\n"
    "central_disp = 1\n"
    "viewer_pos = -513.9474295905042,171.31580986350139,10278.948591810082\n"
    "swivels = 2,15.0,0.0,0.0;0,0.0,0.0,0.0\n"
    "tilts = 0.0,0.0,0.0;0.0,0.0,0.0\n"
    "\n"
)
# A perspective typed by hand, or saved by an older version, holds whole numbers where
# the dialog writes floats; they must be written back as they were read.
WHOLE_NUMBER_PERSP = (
    "[wall]\ncentral_disp = 0\nviewer_pos = 0,0,2000\nswivels = 0,0,0,0;1,-25,40,20\ntilts = 0,0,0;5,8,0\n\n"
)

DESK = Perspective(
    "desk",
    0,
    (0.0, 0.0, 2783.8819102818975),
    (Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0), Swivel(SwivelAxis.LEFT, -25.0, 42.828952465875346, 21.414476232937673)),
    (Tilt(0.0, 0.0, 0.0), Tilt(4.5, 8.565790493175069, 0.0)),
)
COUCH = Perspective(
    "couch",
    1,
    (-513.9474295905042, 171.31580986350139, 10278.948591810082),
    (Swivel(SwivelAxis.RIGHT, 15.0, 0.0, 0.0), Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0)),
    (Tilt(0.0, 0.0, 0.0), Tilt(0.0, 0.0, 0.0)),
)


@pytest.fixture
def saved_layouts(tmp_path):
    """A config directory holding the files v2.3.2 wrote."""
    (tmp_path / "display_systems.dat").write_text(DISPLAY_SYSTEMS_DAT, encoding="utf-8")
    (tmp_path / f"{DUAL_KEY}.persp").write_text(DUAL_PERSP, encoding="utf-8")
    return tmp_path


def detect(monkeypatch, config_dir, monitors):
    monkeypatch.setattr(display_detection, "get_monitors", lambda: monitors)
    return display_detection.detect_layout(config_dir)


@pytest.mark.parametrize(("monitors", "key"), [(DUAL_MONITORS, DUAL_KEY), (LAPTOP_MONITORS, LAPTOP_KEY)])
def test_the_key_of_a_monitor_set_never_changes(monkeypatch, tmp_path, monitors, key):
    layout = detect(monkeypatch, tmp_path, monitors)

    assert str(hash(layout.displays)) == key
    assert layout.key == key


def test_the_key_ignores_monitor_names_and_order(monkeypatch, tmp_path):
    renamed = [monitor(m.x, m.y, m.width, m.height, m.width_mm, m.height_mm, "renamed") for m in DUAL_MONITORS]

    assert detect(monkeypatch, tmp_path, renamed[::-1]).key == DUAL_KEY


def test_a_saved_layout_loads(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)

    assert layout.ppi_norm_offsets == ((0, 0), (2605.7204000891693, 98.49418762870297))
    assert layout.bezels_in_mm() == [(10.5, 0.0), (0.0, 0.0)]
    assert layout.uses_user_diagonals is True
    assert layout.diagonal_inches() == [27.0, 23.8]
    assert [display.detected_phys_size_mm for display in layout.displays] == [(597, 336), (527, 296)]
    assert layout.ppi_norm_resolutions() == [(2560, 1440), (2257, 1269)]
    assert layout.ppi_norm_crops([(0, 0), (0, 0)]) == [(0, 0, 2560, 1440), (2606, 98, 4863, 1367)]
    assert layout.use_perspective is True
    assert layout.default_perspective == "desk"
    assert layout.perspectives == (DESK, COUCH)


def test_perspective_choices_pick_the_perspective_they_mean(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)

    assert layout.perspective_for(Default()) is layout.perspective("desk")
    assert layout.perspective_for(Named("couch")) is layout.perspective("couch")
    assert layout.perspective_for(Disabled()) is None
    assert layout.perspective_for(Named("gone")) is None
    assert layout.without_perspective("desk").perspective_for(Default()) is None


def test_saving_an_unchanged_layout_rewrites_the_same_bytes(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)
    dat = (saved_layouts / "display_systems.dat").read_bytes()
    persp = (saved_layouts / f"{DUAL_KEY}.persp").read_bytes()

    display_store.save_layout(saved_layouts, layout)
    display_store.save_perspectives(saved_layouts, layout)

    # The laptop's section survives, and nothing drifts when the user saves without editing.
    assert (saved_layouts / "display_systems.dat").read_bytes() == dat
    assert (saved_layouts / f"{DUAL_KEY}.persp").read_bytes() == persp


def test_perspectives_with_whole_numbers_are_written_back_as_read(tmp_path):
    (tmp_path / "7.persp").write_text(WHOLE_NUMBER_PERSP, encoding="utf-8")

    perspectives = display_store.read_perspectives(tmp_path, "7")
    display_store.write_perspectives(tmp_path, "7", perspectives)

    assert (tmp_path / "7.persp").read_text(encoding="utf-8") == WHOLE_NUMBER_PERSP
    assert perspectives[0].swivels[1] == Swivel(SwivelAxis.LEFT, -25, 40, 20)


@pytest.mark.parametrize(
    "broken",
    [
        WHOLE_NUMBER_PERSP.replace("0,0,2000", "0,0"),
        WHOLE_NUMBER_PERSP.replace("0,0,2000", "0,0,far"),
        WHOLE_NUMBER_PERSP.replace("1,-25,40,20", "3,-25,40,20"),
        WHOLE_NUMBER_PERSP.replace("5,8,0", "5,8"),
    ],
)
def test_a_perspective_that_is_not_made_of_numbers_is_refused(tmp_path, broken):
    (tmp_path / "7.persp").write_text(broken, encoding="utf-8")

    with pytest.raises(ValueError):
        display_store.read_perspectives(tmp_path, "7")


def test_repeated_saves_do_not_drift(monkeypatch, saved_layouts):
    for _ in range(3):
        display_store.save_layout(saved_layouts, detect(monkeypatch, saved_layouts, DUAL_MONITORS))

    assert (saved_layouts / "display_systems.dat").read_text(encoding="utf-8") == DISPLAY_SYSTEMS_DAT


def test_the_laptop_layout_loads_with_its_diagonal_override(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, LAPTOP_MONITORS)

    (laptop,) = layout.displays
    assert laptop.phys_size_failed is True
    assert laptop.detected_phys_size_mm == (509, 286)
    assert layout.diagonal_inches() == [15.6]
    assert layout.default_perspective is None
    assert layout.perspectives == ()


def test_a_fresh_layout_is_saved_with_float_bezels_as_earlier_versions_wrote_it(monkeypatch, tmp_path):
    layout = detect(monkeypatch, tmp_path, LAPTOP_MONITORS)

    display_store.save_layout(tmp_path, layout)

    assert "bezel_mms = 0.0,0.0\n" in (tmp_path / "display_systems.dat").read_text(encoding="utf-8")


def test_monitors_without_a_saved_layout_get_a_guessed_one(monkeypatch, saved_layouts):
    moved = [DUAL_MONITORS[0], monitor(0, 1440, 1920, 1080, 527, 296, "HDMI-A-1")]

    layout = detect(monkeypatch, saved_layouts, moved)

    assert layout.key not in {DUAL_KEY, LAPTOP_KEY}
    assert layout.uses_user_diagonals is False
    assert layout.bezels_in_mm() == [(0.0, 0.0), (0.0, 0.0)]
    assert layout.ppi_norm_offsets == ((0, 0), (150, 1440))
    assert layout.default_perspective is None
    assert layout.perspectives == ()


def edit_the_layout(layout):
    """Unsaved band edits: diagonals, bezels and positions."""
    count = len(layout.displays)
    return (
        layout.with_diagonals([30.0] * count)
        .with_initial_offsets()
        .with_bezels([(3.0, 2.0)] * count)
        .with_offsets([(5, 6)] * count)
    )


def test_a_layout_is_never_changed_an_edit_is_a_new_layout(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)
    offsets = layout.ppi_norm_offsets

    edited = edit_the_layout(layout)

    with pytest.raises(FrozenInstanceError):
        layout.use_perspective = False  # ty: ignore[invalid-assignment]
    assert edited.ppi_norm_offsets == ((5, 6), (5, 6))
    assert layout.ppi_norm_offsets == offsets
    assert layout.uses_user_diagonals and layout.bezels_in_mm() == [(10.5, 0.0), (0.0, 0.0)]


def test_saving_the_perspective_choice_leaves_the_rest_of_the_saved_layout(monkeypatch, saved_layouts):
    layout = edit_the_layout(detect(monkeypatch, saved_layouts, DUAL_MONITORS))
    layout = layout.without_perspective("desk").with_perspective(COUCH, use_perspective=False, is_default=True)

    display_store.save_perspective_choice(saved_layouts, layout)

    expected = DISPLAY_SYSTEMS_DAT.replace(
        "use_perspective = 1\ndef_perspective = desk", "use_perspective = 0\ndef_perspective = couch"
    )
    assert (saved_layouts / "display_systems.dat").read_text(encoding="utf-8") == expected
    assert (saved_layouts / f"{DUAL_KEY}.persp").read_text(encoding="utf-8") == DUAL_PERSP[
        DUAL_PERSP.index("[couch]") :
    ]


def test_the_perspective_choice_of_displays_without_a_saved_layout_saves_the_fresh_layout(monkeypatch, tmp_path):
    layout = detect(monkeypatch, tmp_path, LAPTOP_MONITORS)
    fresh_offsets = layout.ppi_norm_offsets
    layout = replace(edit_the_layout(layout), default_perspective="desk")

    display_store.save_perspective_choice(tmp_path, layout)

    reloaded = detect(monkeypatch, tmp_path, LAPTOP_MONITORS)
    assert reloaded.ppi_norm_offsets == fresh_offsets
    assert reloaded.bezels_in_mm() == [(0.0, 0.0)]
    assert reloaded.uses_user_diagonals is False
    assert reloaded.default_perspective == "desk"


def test_an_unreadable_layout_file_leaves_the_perspectives_as_they_were(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS).without_perspective("couch")
    persp = (saved_layouts / f"{DUAL_KEY}.persp").read_bytes()
    (saved_layouts / "display_systems.dat").write_text("no section header\n", encoding="utf-8")

    with pytest.raises(configparser.Error):
        display_store.save_perspective_choice(saved_layouts, layout)

    assert (saved_layouts / f"{DUAL_KEY}.persp").read_bytes() == persp
    assert (saved_layouts / "display_systems.dat").read_text(encoding="utf-8") == "no section header\n"


def test_adding_a_perspective_keeps_the_order_and_replaces_one_of_the_same_name(monkeypatch, saved_layouts):
    layout = detect(monkeypatch, saved_layouts, DUAL_MONITORS)
    renamed_viewer = replace(DESK, viewer_pos=(0.0, 0.0, 1.0))
    new = replace(DESK, name="new")

    replaced = layout.with_perspective(renamed_viewer, use_perspective=True, is_default=False)
    added = layout.with_perspective(new, use_perspective=True, is_default=True)

    assert replaced.perspectives == (renamed_viewer, COUCH)
    assert replaced.default_perspective is None
    assert added.perspective_names() == ["desk", "couch", "new"]
    assert added.default_perspective == "new"
