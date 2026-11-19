"""Display layouts as Superpaper v2.3.2 saved them.

display_systems.dat and the <key>.persp files hold the users' most hand-tuned data:
positions, bezels, diagonal overrides and perspectives. Their key is CPython's hash of
a tuple of ints describing the monitors, so anything that lets a string or a float into
that hash, or a CPython that hashes tuples differently, would silently orphan every
user's layout (L1). The tests pin the key, both formats and the loaded geometry.

The file contents below were written by v2.3.2's own DisplaySystem for the monitors
below: a laptop whose physical size wasn't detected, then the two-monitor setup after
the user overrode both diagonals, entered a 10.5 mm bezel, dragged the second display
and saved two perspectives.
"""

import pytest

from superpaper.geometry import display_detection
from superpaper.geometry.perspective import Perspective, Swivel, SwivelAxis, Tilt
from tests.conftest import monitor

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

SAVED_DESK = Perspective(
    "desk",
    0,
    (0.0, 0.0, 2783.8819102818975),
    (Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0), Swivel(SwivelAxis.LEFT, -25.0, 42.828952465875346, 21.414476232937673)),
    (Tilt(0.0, 0.0, 0.0), Tilt(4.5, 8.565790493175069, 0.0)),
)
SAVED_COUCH = Perspective(
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


def edit_the_layout(layout):
    """Unsaved band edits: diagonals, bezels and positions."""
    count = len(layout.displays)
    return (
        layout.with_diagonals([30.0] * count)
        .with_initial_offsets()
        .with_bezels([(3.0, 2.0)] * count)
        .with_offsets([(5, 6)] * count)
    )
