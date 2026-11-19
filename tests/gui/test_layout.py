from dataclasses import replace

import pytest


def drafts(cache):
    return {path: path.stat().st_mtime_ns for path in (cache / "preview").glob("draft-?.png")}


def bezels_with_first(editor, millimetres):
    return [(millimetres, 0.0)] + [(0.0, 0.0)] * (len(editor.staged.layout.displays) - 1)


def stage_bezels(editor, millimetres):
    editor.staged.layout = editor.staged.layout.with_bezels(bezels_with_first(editor, millimetres))


def test_saved_display_settings_go_to_the_config_directory(gui_env, running_work, editor):
    stage_bezels(editor, 4.5)
    editor.display_band.onSave(None)
    gui_env.settle(running_work)
    assert (gui_env.paths.config / "display_systems.dat").is_file()


def test_saving_display_settings_gives_the_session_a_reloaded_layout_with_them(gui_env, running_work, editor):
    before = running_work.session.layout
    stage_bezels(editor, 4.5)
    editor.display_band.onSave(None)
    gui_env.settle(running_work)
    layout = running_work.session.layout
    assert layout is not before
    assert layout.bezels_in_mm() == editor.staged.layout.bezels_in_mm()
    assert layout.bezels_in_mm()[0] == (4.5, 0.0)


def test_the_align_test_finds_its_bundled_image_and_renders_a_draft(gui_env, running_work, editor):
    gui_env.shown()
    editor.onAlignTest(None)
    gui_env.settle(running_work)
    assert not gui_env.shown()
    assert drafts(gui_env.paths.cache)


def test_the_align_test_reports_a_missing_test_image_and_renders_nothing(gui_env, running_work, editor, monkeypatch):
    monkeypatch.setattr(gui_env.ui.editor, "resource", lambda name: gui_env.root / "nope" / name)
    gui_env.shown()
    editor.onAlignTest(None)
    gui_env.settle(running_work)
    messages = gui_env.shown()
    assert len(messages) == 1
    assert "not found" in messages[0][2]
    assert not drafts(gui_env.paths.cache)


def test_an_unsaved_perspective_pick_survives_the_perspective_dialog(gui_env, saved_layout, running_work, editor):
    wx = gui_env.ui.wx

    def pick(label):
        editor.ch_persp.SetSelection(editor.ch_persp.FindString(label))
        event = wx.CommandEvent(wx.EVT_COMBOBOX.typeId, editor.ch_persp.GetId())
        event.SetEventObject(editor.ch_persp)
        event.SetString(label)
        editor.ch_persp.GetEventHandler().ProcessEvent(event)

    saved_label = editor.ch_persp.GetStringSelection()
    assert not editor.button_save.IsEnabled()
    pick("wall")
    assert editor.button_save.IsEnabled()

    gui_env.open_perspectives(editor)

    assert editor.ch_persp.GetStringSelection() == "wall"
    assert editor.button_save.IsEnabled()
    pick(saved_label)
    assert not editor.button_save.IsEnabled()


def test_a_failed_display_settings_save_is_reported_and_stays_unsaved(gui_env, running_work, editor):
    (gui_env.paths.config / "display_systems.dat").mkdir()
    stage_bezels(editor, 4.5)
    editor.display_band.update_dirty()
    gui_env.shown()

    editor.display_band.onSave(None)

    assert [dialog[:2] for dialog in gui_env.shown()] == [("display_band", "Error")]
    assert editor.display_band.button_system_save.IsEnabled()


def test_a_unit_switch_with_a_non_number_is_reported_and_changes_nothing(gui_env, running_work, editor):
    layout_editor = editor.wpprev_pnl.layout_editor
    layout_editor.onConfigure(None)
    layout_editor.onEntry(None)
    (entry,) = [
        window for window in gui_env.ui.wx.GetTopLevelWindows() if type(window).__name__ == "DisplayPositionEntry"
    ]
    entry.grid_rows[0][1].SetValue("abc")
    gui_env.shown()

    entry.cb_use_px.SetValue(True)
    entry.onCbusepx(None)

    assert [dialog[:2] for dialog in gui_env.shown()] == [("positions_dialog", "Error")]
    assert entry.cb_use_px.GetValue() is False
    assert entry.grid_rows[0][1].GetValue() == "abc"


def test_the_positions_dialog_controls_sit_in_a_panel_not_straight_on_the_frame(gui_env, editor):
    layout_editor = editor.wpprev_pnl.layout_editor
    layout_editor.onConfigure(None)
    layout_editor.onEntry(None)
    (entry,) = [
        window for window in gui_env.ui.wx.GetTopLevelWindows() if type(window).__name__ == "DisplayPositionEntry"
    ]
    assert list(entry.GetChildren()) == [entry.panel]
    assert entry.panel.HasFlag(gui_env.ui.wx.TAB_TRAVERSAL)
    assert entry.grid_rows[0][5].GetParent() is entry.panel


@pytest.fixture
def perspective_dialog(gui_env, editor):
    return gui_env.open_perspectives(editor)


def test_the_open_editors_perspective_dialog_sees_a_setting_saved_meanwhile(gui_env, running_work, editor):
    running_work.apply_settings(replace(running_work.settings, warn_large_img=True))
    assert gui_env.open_perspectives(editor).warn_large_img is True


def test_a_dangling_default_perspective_is_shown_as_new_and_nothing_is_invented(gui_env, editor):
    editor.staged.layout = replace(editor.staged.layout, default_perspective="ghost")
    assert gui_env.open_perspectives(editor).tc_name.GetValue() == "ghost"
    assert "ghost" not in editor.staged.layout.perspective_names()


def test_the_perspective_dialog_has_a_row_per_display(running_work, perspective_dialog):
    assert len(perspective_dialog.grid_rows) == len(running_work.session.layout.displays)


def study_dialog(gui_env, editor):
    """A perspective dialog on unsaved diagonals, filled in to save the perspective "study" as the default."""
    editor.staged.layout = editor.staged.layout.with_diagonals(
        [55.0] * len(editor.staged.layout.displays)
    ).with_initial_offsets()
    dialog = gui_env.open_perspectives(editor)
    dialog.warn_large_img = True
    dialog.tc_name.SetValue("study")
    dialog.cb_dispsys_def.SetValue(True)
    dialog.tclist_vieweroffs[2].SetValue("600")
    return dialog


class SavedStudy:
    """The perspective "study" saved while the editor holds an unsaved band edit."""

    def __init__(self, gui_env, running_work, editor):
        self.editor = editor
        self.config = gui_env.paths.config
        # Saving the band first gives display_systems.dat for the perspective save to leave alone.
        editor.display_band.onSave(None)
        gui_env.settle(running_work)
        self.session_layout = running_work.session.layout
        self.session_bezels = self.session_layout.bezels_in_mm()
        self.saved_max_ppi = self.session_layout.max_ppi()
        self.dialog = study_dialog(gui_env, editor)
        self.saved_bezel_lines = self.bezel_lines()
        stage_bezels(editor, 9.0)
        self.dialog.onSave(None)
        self.saved_dat = (self.config / "display_systems.dat").read_text(encoding="utf-8")
        self.saved_persp = (self.config / f"{editor.staged.layout.key}.persp").read_text(encoding="utf-8")

    def bezel_lines(self):
        text = (self.config / "display_systems.dat").read_text(encoding="utf-8")
        return [line for line in text.splitlines() if "bezel_mms" in line]


@pytest.fixture
def saved_study(gui_env, running_work, editor):
    return SavedStudy(gui_env, running_work, editor)


def test_a_perspective_save_leaves_the_unsaved_band_edit_unsaved_in_the_editor_and_on_disk(
    running_work, editor, saved_study
):
    assert [line for line in saved_study.saved_dat.splitlines() if "bezel_mms" in line] == saved_study.saved_bezel_lines
    assert editor.staged.layout.bezels_in_mm()[0] == (9.0, 0.0)
    assert running_work.session.layout != editor.staged.layout
    assert running_work.session.layout.bezels_in_mm() == saved_study.session_bezels


def test_the_editor_stages_its_own_layout_and_the_dialog_works_on_the_saved_one(editor, saved_study):
    assert saved_study.dialog.layout.bezels_in_mm() == saved_study.session_bezels
    assert editor.staged.layout.bezels_in_mm() != saved_study.session_bezels
    assert saved_study.session_layout.bezels_in_mm() == saved_study.session_bezels


def test_the_saved_perspective_is_converted_with_the_saved_layouts_density(editor, saved_study):
    depth_line = next(line for line in saved_study.saved_persp.splitlines() if line.startswith("viewer_pos"))
    viewer_depth = float(depth_line.split("=")[1].split(",")[2])
    assert abs(viewer_depth - 600 * saved_study.saved_max_ppi / 25.4) < 1e-6
    assert editor.staged.layout.max_ppi() != saved_study.saved_max_ppi


def test_a_saved_perspective_becomes_the_default_in_memory_and_on_disk_with_no_scratch_entry(editor, saved_study):
    assert editor.staged.layout.default_perspective == "study"
    assert sorted(editor.staged.layout.perspective_names()) == ["study"]
    assert "def_perspective = study" in saved_study.saved_dat
    assert saved_study.saved_persp.startswith("[study]\n")
    assert "\0" not in saved_study.saved_dat + saved_study.saved_persp


def test_the_perspective_dialogs_test_renders_a_draft(gui_env, running_work, saved_study):
    before = drafts(gui_env.paths.cache)
    gui_env.shown()
    saved_study.dialog.test_image = str(gui_env.images / "c.png")
    saved_study.dialog.onTestWallpaper(None)
    gui_env.settle(running_work)
    assert drafts(gui_env.paths.cache) != before
    assert not gui_env.shown()


@pytest.fixture
def ending_dialog(perspective_dialog):
    """A perspective dialog with a viewer distance, whose EndModal records the code instead of closing."""
    perspective_dialog.tclist_vieweroffs[2].SetValue("600")
    perspective_dialog.ended = []
    perspective_dialog.EndModal = perspective_dialog.ended.append
    return perspective_dialog


def test_the_perspective_name_field_takes_40_characters(ending_dialog):
    ending_dialog.tc_name.SetValue("p" * 40)
    assert len(ending_dialog.tc_name.GetValue()) == 40


def test_a_valid_perspective_name_closes_the_dialog(gui_env, ending_dialog):
    ending_dialog.tc_name.SetValue("study2")
    ending_dialog.onOk(None)
    assert ending_dialog.ended == [gui_env.ui.wx.ID_OK]


def test_an_existing_reserved_name_perspective_can_be_saved_again(gui_env, ending_dialog):
    ending_dialog.tc_name.SetValue("study2")
    ending_dialog.onOk(None)
    ending_dialog.layout = ending_dialog.layout.with_perspective(
        replace(ending_dialog.layout.perspective("study2"), name="default"), use_perspective=True, is_default=False
    )
    ending_dialog.tc_name.SetValue("default")
    ending_dialog.ended.clear()
    gui_env.shown()
    ending_dialog.onOk(None)
    assert ending_dialog.ended == [gui_env.ui.wx.ID_OK]
    assert not gui_env.shown()
