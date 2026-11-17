from types import SimpleNamespace

import pytest

from superpaper import displays

MONITORS = [
    SimpleNamespace(x=0, y=0, width=1920, height=1080, width_mm=527, height_mm=296, name="A"),
    SimpleNamespace(x=1920, y=0, width=1920, height=1080, width_mm=527, height_mm=296, name="B"),
]


@pytest.fixture
def system(monkeypatch, tmp_path):
    monkeypatch.setattr(displays, "get_monitors", lambda: MONITORS)
    return displays.DisplaySystem(tmp_path)


def bezel_px(system, mm):
    return mm * system.max_ppi() / 25.4


def test_a_diagonal_change_keeps_the_bezels_in_millimetres(system):
    system.update_display_diags([27.0, 27.0])
    system.update_bezels([(8.5, 0.0), (0.0, 3.3)])
    px_before = system.bezels_in_px()

    system.update_display_diags([28.0, 28.0])
    assert system.bezels_in_mm() == [(8.5, 0.0), (0.0, 3.3)]
    assert system.bezels_in_px() != px_before

    system.update_display_diags([27.0, 27.0])
    assert system.bezels_in_mm() == [(8.5, 0.0), (0.0, 3.3)]
    assert system.bezels_in_px() == pytest.approx(px_before)


def test_a_fresh_layout_gets_the_initial_layout_when_bezels_are_set(system):
    system.update_bezels([(10.0, 0.0), (0.0, 0.0)])

    assert system.get_ppinorm_offsets() == pytest.approx([(0, 0), (1920 + bezel_px(system, 10.0), 0)], abs=1)


def test_a_missing_layout_gets_the_initial_layout_when_bezels_are_set(system):
    for dsp in system.disp_list:
        dsp.ppi_norm_offset = None

    system.update_bezels([(10.0, 0.0), (0.0, 0.0)])

    assert system.get_ppinorm_offsets() == pytest.approx([(0, 0), (1920 + bezel_px(system, 10.0), 0)], abs=1)


def test_an_overlapping_layout_gets_the_initial_layout_when_bezels_are_set(system):
    system.update_ppinorm_offsets([(0, 0), (100, 0)])

    system.update_bezels([(10.0, 0.0), (0.0, 0.0)])

    assert system.get_ppinorm_offsets() == pytest.approx([(0, 0), (1920 + bezel_px(system, 10.0), 0)], abs=1)


def test_dragged_positions_survive_setting_bezels(system):
    system.update_ppinorm_offsets([(0.5, 300.25), (2400.0, 0.0)])

    system.update_bezels([(0.0, 0.0), (0.0, 5.0)])

    assert system.get_ppinorm_offsets() == [(0.5, 300.25), (2400.0, 0.0)]


def test_displays_after_a_bezel_move_by_exactly_its_growth(system):
    system.update_ppinorm_offsets([(0, 300), (2400.0, 0)])

    system.update_bezels([(10.0, 0.0), (0.0, 0.0)])

    left, right = system.get_ppinorm_offsets()
    assert left == (0, 300)
    assert right == pytest.approx((2400.0 + bezel_px(system, 10.0), 0))


def test_corner_touching_displays_do_not_overlap_after_setting_bezels(system):
    system.update_ppinorm_offsets([(0, 0), (1920, 1080)])

    system.update_bezels([(10.0, 10.0), (10.0, 10.0)])

    assert system._layout_is_valid()


def test_a_gap_between_dragged_displays_is_kept_when_a_bezel_changes_back(system):
    system.update_ppinorm_offsets([(0, 0), (2400.0, 0)])
    system.update_bezels([(10.0, 0.0), (0.0, 0.0)])

    system.update_bezels([(0.0, 0.0), (0.0, 0.0)])

    assert system.get_ppinorm_offsets() == [(0, 0), pytest.approx((2400.0, 0))]
