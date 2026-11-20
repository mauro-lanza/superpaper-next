"""The display layout of a user whose portable display was entered as 15.6 inch: the displays
never overlap on screen, on disk, or when loaded (journey J5).

The monitors are an LG and a portrait portable whose EDID size is rejected, so that it counts
as 23 inch until its diagonal is typed.
"""

import pytest

from superpaper.desktop import linux
from superpaper.geometry import display_store, layout_edit
from superpaper.geometry.display_detection import detect_layout
from tests.geometry.conftest import OVERLAPPING_DAT, OVERLAPPING_KEY, OVERLAPPING_MONITORS


@pytest.fixture(autouse=True)
def user_monitors(gui_env, monkeypatch):
    monkeypatch.setattr(linux, "detect_monitors", lambda: OVERLAPPING_MONITORS)
    gui_env.profile_file("Broken").unlink()


def dat(gui_env):
    return (gui_env.paths.config / "display_systems.dat").read_text(encoding="utf-8")


def type_diagonal(band, index, text):
    band.tc_list_diaginch[index].SetValue(text)


def stage_typed_diagonals(band):
    band.cb_diaginch.SetValue(True)
    band.onCheckboxDiaginch(None)
    for typed in ("1", "15", "15.", "15.6"):
        type_diagonal(band, 1, typed)


def drag_second_display_onto_the_first(layout_editor):
    layout_editor.onConfigure(None)
    first, second = layout_editor.draggable_shapes
    second.pos = (first.pos[0] + 5, first.pos[1] + 5)
    layout_editor.positions_dragged = True


def drag_second_display(layout_editor, dx):
    layout_editor.onConfigure(None)
    shape = layout_editor.draggable_shapes[1]
    shape.pos = (shape.pos[0] + dx, shape.pos[1])
    layout_editor.positions_dragged = True


def test_typing_the_portables_diagonal_leaves_the_displays_apart_without_a_gap_from_passing_values(
    gui_env, superpaper
):
    panel = gui_env.open_editor(superpaper)
    band = panel.display_band
    before = panel.staged.layout

    stage_typed_diagonals(band)

    staged = panel.staged.layout
    assert staged.diagonal_inches()[1] == 15.6
    assert staged.is_valid()
    assert staged == layout_edit.fit_resized(before.with_diagonals(staged.user_diagonal_inches)).layout
    assert staged.ppi_norm_offsets[0] == before.ppi_norm_offsets[0]
    assert band.button_system_save.IsEnabled()
    assert gui_env.shown() == []


def test_an_invalid_diagonal_is_marked_and_keeps_the_band_from_saving(gui_env, superpaper):
    from superpaper.ui.display_band import INVALID_COLOUR

    panel = gui_env.open_editor(superpaper)
    band = panel.display_band
    stage_typed_diagonals(band)
    typed = panel.staged.layout

    type_diagonal(band, 1, "abc")

    assert panel.staged.layout == typed
    assert band.tc_list_diaginch[1].GetBackgroundColour() == INVALID_COLOUR
    assert not band.button_system_save.IsEnabled()
    assert band.button_system_revert.IsEnabled()

    type_diagonal(band, 1, "1001")
    assert not band.button_system_save.IsEnabled()

    type_diagonal(band, 1, "15,6")
    assert band.tc_list_diaginch[1].GetBackgroundColour() != INVALID_COLOUR
    assert band.button_system_save.IsEnabled()
    assert panel.staged.layout.diagonal_inches()[1] == 15.6


def test_the_positions_button_is_labelled_done_and_refuses_displays_that_overlap(gui_env, superpaper):
    panel = gui_env.open_editor(superpaper)
    layout_editor = panel.wpprev_pnl.layout_editor
    stage_typed_diagonals(panel.display_band)
    staged = panel.staged.layout
    profile_save_enabled = panel.button_save.IsEnabled()
    gui_env.shown()

    drag_second_display_onto_the_first(layout_editor)
    assert layout_editor.button_save.GetLabel() == "Done"
    layout_editor.onSave(None)

    assert [dialog[:2] for dialog in gui_env.shown()] == [("layout_editor", "Error")]
    assert layout_editor.config_mode
    assert panel.staged.layout == staged

    shape = layout_editor.draggable_shapes[1]
    shape.pos = (shape.pos[0] + 20000, shape.pos[1])
    layout_editor.onSave(None)

    assert not layout_editor.config_mode
    assert panel.staged.layout.is_valid()
    assert panel.display_band.button_system_save.IsEnabled()
    assert panel.button_save.IsEnabled() == profile_save_enabled


def test_the_journey_from_typing_to_the_saved_layout_after_a_restart(gui_env, superpaper):
    panel = gui_env.open_editor(superpaper)
    band = panel.display_band
    stage_typed_diagonals(band)
    layout_editor = panel.wpprev_pnl.layout_editor
    drag_second_display(layout_editor, 40)
    layout_editor.onSave(None)
    staged = panel.staged.layout
    assert not (gui_env.paths.config / "display_systems.dat").exists()

    band.onSave(None)
    gui_env.settle(superpaper)

    assert staged.is_valid()
    assert not band.button_system_save.IsEnabled()
    assert superpaper.session.layout.ppi_norm_offsets == staged.ppi_norm_offsets
    assert detect_layout(gui_env.paths.config, linux).ppi_norm_offsets == staged.ppi_norm_offsets

    gui_env.quit(superpaper)
    restarted = gui_env.start()
    reopened = gui_env.open_editor(restarted)

    assert reopened.staged.layout.ppi_norm_offsets == staged.ppi_norm_offsets
    assert reopened.staged.layout.user_diagonal_inches == staged.user_diagonal_inches
    assert reopened.display_band.tc_list_diaginch[1].GetValue() == "15.6"
    assert not reopened.display_band.button_system_save.IsEnabled()


def test_a_perspective_is_staged_with_the_band_and_written_by_its_save(gui_env, superpaper):
    panel = gui_env.open_editor(superpaper)
    band = panel.display_band
    dialog = gui_env.open_perspectives(panel)
    dialog.tc_name.SetValue("desk")
    dialog.cb_dispsys_def.SetValue(True)
    dialog.tclist_vieweroffs[2].SetValue("700")

    assert dialog.onSave(None) is True

    assert not (gui_env.paths.config / "display_systems.dat").exists()
    assert not list(gui_env.paths.config.glob("*.persp"))
    assert band.button_system_save.IsEnabled()

    band.onSave(None)
    gui_env.settle(superpaper)

    assert "def_perspective = desk" in dat(gui_env)
    assert next(gui_env.paths.config.glob("*.persp")).read_text(encoding="utf-8").startswith("[desk]\n")
    assert superpaper.session.layout.default_perspective == "desk"


def test_the_saved_layout_that_overlaps_starts_as_the_default_arrangement_with_one_message(gui_env):
    (gui_env.paths.config / "display_systems.dat").write_text(OVERLAPPING_DAT, encoding="utf-8")
    superpaper = gui_env.start()
    gui_env.settle(superpaper)

    assert superpaper.session.layout.key == OVERLAPPING_KEY
    assert superpaper.session.layout.is_valid()
    assert superpaper.session.layout.uses_user_diagonals is False
    messages = [message for message in gui_env.shown() if message[1] == "Error"]
    assert [message[0] for message in messages] == ["app"]
    assert "can't be used" in messages[0][2]
    assert dat(gui_env) == OVERLAPPING_DAT

    panel = gui_env.open_editor(superpaper)
    assert panel.staged.layout.is_valid()
    assert not panel.display_band.button_system_save.IsEnabled()

    stage_typed_diagonals(panel.display_band)
    panel.display_band.onSave(None)
    gui_env.settle(superpaper)

    assert dat(gui_env) != OVERLAPPING_DAT
    assert display_store.load(gui_env.paths.config, superpaper.session.layout.displays).is_valid()
    assert gui_env.shown() == []


def test_a_corrupt_layout_file_does_not_stop_the_app_from_starting(gui_env):
    (gui_env.paths.config / "display_systems.dat").write_text("not a layout\n", encoding="utf-8")
    (gui_env.paths.config / f"{OVERLAPPING_KEY}.persp").write_text("[desk]\ncentral_disp = x\n", encoding="utf-8")

    superpaper = gui_env.start()
    gui_env.settle(superpaper)

    assert superpaper.session.layout.is_valid()
    assert [message[:2] for message in gui_env.shown() if message[1] == "Error"] == [("app", "Error")]
    assert (gui_env.paths.config / "display_systems.dat").read_text(encoding="utf-8") == "not a layout\n"
