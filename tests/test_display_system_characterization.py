"""Display layouts as Superpaper v2.3.2 saved them.

display_systems.dat and the <key>.persp files hold the users' most hand-tuned data:
positions, bezels, diagonal overrides and perspectives. Their key is CPython's hash of
a tuple of ints describing the monitors, so anything that lets a string or a float into
that hash, or a CPython that hashes tuples differently, would silently orphan every
user's layout (L1). These tests pin the key, both formats and the loaded geometry
before the display code is restructured.

The file contents below were written by v2.3.2's own DisplaySystem for the monitors
below: a laptop whose physical size wasn't detected, then the two-monitor setup after
the user overrode both diagonals, entered a 10.5 mm bezel, dragged the second display
and saved two perspectives.
"""

from types import SimpleNamespace

import pytest


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


@pytest.fixture
def saved_layouts(tmp_path):
    """A config directory holding the files v2.3.2 wrote."""
    (tmp_path / "display_systems.dat").write_text(DISPLAY_SYSTEMS_DAT, encoding="utf-8")
    (tmp_path / f"{DUAL_KEY}.persp").write_text(DUAL_PERSP, encoding="utf-8")
    return tmp_path


def display_system(wpproc, monkeypatch, config_dir, monitors):
    monkeypatch.setattr(wpproc, "get_monitors", lambda: monitors)
    return wpproc.DisplaySystem(config_dir)


@pytest.mark.parametrize(("monitors", "key"), [(DUAL_MONITORS, DUAL_KEY), (LAPTOP_MONITORS, LAPTOP_KEY)])
def test_the_key_of_a_monitor_set_never_changes(profile_modules, monkeypatch, tmp_path, monitors, key):
    _, wpproc = profile_modules

    assert str(hash(display_system(wpproc, monkeypatch, tmp_path, monitors))) == key


def test_the_key_ignores_monitor_names_and_order(profile_modules, monkeypatch, tmp_path):
    _, wpproc = profile_modules
    renamed = [monitor(m.x, m.y, m.width, m.height, m.width_mm, m.height_mm, "renamed") for m in DUAL_MONITORS]

    assert str(hash(display_system(wpproc, monkeypatch, tmp_path, renamed[::-1]))) == DUAL_KEY


def test_a_saved_layout_loads(profile_modules, monkeypatch, saved_layouts):
    _, wpproc = profile_modules

    system = display_system(wpproc, monkeypatch, saved_layouts, DUAL_MONITORS)

    assert system.get_ppinorm_offsets() == [(0, 0), (2605.7204000891693, 98.49418762870297)]
    assert system.bezels_in_mm() == [(10.5, 0.0), (0.0, 0.0)]
    assert system.use_user_diags is True
    assert [display.diagonal_size()[1] for display in system.disp_list] == [27.0, 23.8]
    assert [display.detected_phys_size_mm for display in system.disp_list] == [(597, 336), (527, 296)]
    assert [display.ppi_norm_resolution for display in system.disp_list] == [(2560, 1440), (2257, 1269)]
    assert system.get_ppi_norm_crops([(0, 0), (0, 0)]) == [(0, 0, 2560, 1440), (2606, 98, 4863, 1367)]
    assert system.use_perspective is True
    assert system.default_perspective == "desk"
    assert system.perspective_dict == {
        "desk": {
            "central_disp": 0,
            "viewer_pos": [0.0, 0.0, 2783.8819102818975],
            "swivels": [(0, 0.0, 0.0, 0.0), (1, -25.0, 42.828952465875346, 21.414476232937673)],
            "tilts": [(0.0, 0.0, 0.0), (4.5, 8.565790493175069, 0.0)],
        },
        "couch": {
            "central_disp": 1,
            "viewer_pos": [-513.9474295905042, 171.31580986350139, 10278.948591810082],
            "swivels": [(2, 15.0, 0.0, 0.0), (0, 0.0, 0.0, 0.0)],
            "tilts": [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)],
        },
    }
    assert system.get_persp_data("default") is system.perspective_dict["desk"]


def test_saving_an_unchanged_layout_rewrites_the_same_bytes(profile_modules, monkeypatch, saved_layouts):
    _, wpproc = profile_modules
    system = display_system(wpproc, monkeypatch, saved_layouts, DUAL_MONITORS)
    dat = (saved_layouts / "display_systems.dat").read_bytes()
    persp = (saved_layouts / f"{DUAL_KEY}.persp").read_bytes()

    system.save_system()
    system.save_perspectives()

    # The laptop's section survives, and nothing drifts when the user saves without editing.
    assert (saved_layouts / "display_systems.dat").read_bytes() == dat
    assert (saved_layouts / f"{DUAL_KEY}.persp").read_bytes() == persp


def test_repeated_saves_do_not_drift(profile_modules, monkeypatch, saved_layouts):
    _, wpproc = profile_modules

    for _ in range(3):
        display_system(wpproc, monkeypatch, saved_layouts, DUAL_MONITORS).save_system()

    assert (saved_layouts / "display_systems.dat").read_text(encoding="utf-8") == DISPLAY_SYSTEMS_DAT


def test_the_laptop_layout_loads_with_its_diagonal_override(profile_modules, monkeypatch, saved_layouts):
    _, wpproc = profile_modules

    system = display_system(wpproc, monkeypatch, saved_layouts, LAPTOP_MONITORS)

    (laptop,) = system.disp_list
    assert laptop.phys_size_failed is True
    assert laptop.detected_phys_size_mm == (509, 286)
    assert laptop.diagonal_size()[1] == 15.6
    assert system.default_perspective is None
    assert system.perspective_dict == {}


def test_monitors_without_a_saved_layout_get_a_guessed_one(profile_modules, monkeypatch, saved_layouts):
    _, wpproc = profile_modules
    moved = [DUAL_MONITORS[0], monitor(0, 1440, 1920, 1080, 527, 296, "HDMI-A-1")]

    system = display_system(wpproc, monkeypatch, saved_layouts, moved)

    assert str(hash(system)) not in {DUAL_KEY, LAPTOP_KEY}
    assert system.use_user_diags is False
    assert system.bezels_in_mm() == [(0.0, 0.0), (0.0, 0.0)]
    assert system.get_ppinorm_offsets() == [(0, 0), (150, 1440)]
    assert system.default_perspective is None
    assert system.perspective_dict == {}
