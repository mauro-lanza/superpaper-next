import pytest


def drafts(cache):
    return {path: path.stat().st_mtime_ns for path in (cache / "preview").glob("draft-?.png")}


def bezels_with_first(editor, millimetres):
    return [(millimetres, 0.0)] + [(0.0, 0.0)] * (len(editor.display_sys.disp_list) - 1)


def test_saved_display_settings_go_to_the_config_directory(gui_env, running_work, editor):
    editor.display_sys.update_bezels(bezels_with_first(editor, 4.5))
    editor.display_band.onSave(None)
    gui_env.settle(running_work)
    assert (gui_env.paths.config / "display_systems.dat").is_file()


def test_saving_display_settings_gives_the_session_a_reloaded_layout_with_them(gui_env, running_work, editor):
    before = running_work.session.display_system
    editor.display_sys.update_bezels(bezels_with_first(editor, 4.5))
    editor.display_band.onSave(None)
    gui_env.settle(running_work)
    layout = running_work.session.display_system
    assert layout is not before
    assert layout.bezels_in_mm() == editor.display_sys.bezels_in_mm()
    assert layout.bezels_in_mm()[0] == (4.5, 0.0)


def test_the_align_test_finds_its_bundled_image_and_renders_a_draft(gui_env, running_work, editor):
    gui_env.shown()
    editor.onAlignTest(None)
    gui_env.settle(running_work)
    assert not gui_env.shown()
    assert drafts(gui_env.paths.cache)


def test_the_align_test_returns_after_a_missing_test_image(gui_env, editor, monkeypatch):
    monkeypatch.setattr(gui_env.ui.editor, "resource", lambda name: gui_env.root / "nope" / name)
    gui_env.shown()
    returned = editor.onAlignTest(None)
    messages = gui_env.shown()
    assert returned == -1
    assert len(messages) == 1
    assert "not found" in messages[0][2]


@pytest.fixture
def perspective_dialog(gui_env, editor):
    dialog = gui_env.ui.perspective_dialog.PerspectiveConfig(editor)
    yield dialog
    dialog.Destroy()


def layout_of(dialog):
    return dialog.display_sys.default_perspective, sorted(dialog.display_sys.perspective_dict)


def test_the_open_editors_perspective_dialog_sees_a_setting_saved_meanwhile(gui_env, running_work, editor):
    running_work.apply_settings(warn_large_img=True)
    dialog = gui_env.ui.perspective_dialog.PerspectiveConfig(editor)
    warns = dialog.warn_large_img
    dialog.Destroy()
    assert warns is True


def test_a_dangling_default_perspective_is_shown_as_new_and_nothing_is_invented(gui_env, editor):
    editor.display_sys.default_perspective = "ghost"
    dialog = gui_env.ui.perspective_dialog.PerspectiveConfig(editor)
    name = dialog.tc_name.GetValue()
    dialog.Destroy()
    assert name == "ghost"
    assert "ghost" not in editor.display_sys.perspective_dict


def test_the_perspective_dialog_has_a_row_per_display(running_work, perspective_dialog):
    assert len(perspective_dialog.grid_rows) == len(running_work.session.display_system.disp_list)


def study_dialog(gui_env, editor):
    """A perspective dialog on unsaved diagonals, filled in to save the perspective "study" as the default."""
    editor.display_sys.update_display_diags([55.0] * len(editor.display_sys.disp_list))
    dialog = gui_env.ui.perspective_dialog.PerspectiveConfig(editor)
    dialog.warn_large_img = True
    dialog.tc_name.SetValue("study")
    dialog.cb_dispsys_def.SetValue(True)
    dialog.tclist_vieweroffs[2].SetValue("600")
    return dialog


def save_with_failing_check(dialog):
    """Save with a large-image check that raises; returns the layout before and after."""

    def failing_check(data):
        message = "check failed"
        raise RuntimeError(message)

    before = layout_of(dialog)
    dialog.check_for_large_image_size = failing_check
    with pytest.raises(RuntimeError):
        dialog.onSave(None)
    del dialog.check_for_large_image_size
    return before, layout_of(dialog)


def test_a_failed_perspective_check_leaves_the_layout_as_it_was(gui_env, editor):
    dialog = study_dialog(gui_env, editor)
    before, after = save_with_failing_check(dialog)
    dialog.Destroy()
    assert after == before


class SavedStudy:
    """The perspective "study" saved while the editor holds an unsaved band edit."""

    def __init__(self, gui_env, running_work, editor):
        self.editor = editor
        self.config = gui_env.paths.config
        # Saving the band first gives display_systems.dat for the perspective save to leave alone.
        editor.display_band.onSave(None)
        gui_env.settle(running_work)
        self.session_layout = running_work.session.display_system
        self.session_bezels = self.session_layout.bezels_in_mm()
        self.saved_max_ppi = self.session_layout.max_ppi()
        self.dialog = study_dialog(gui_env, editor)
        save_with_failing_check(self.dialog)
        self.saved_bezel_lines = self.bezel_lines()
        editor.display_sys.update_bezels(bezels_with_first(editor, 9.0))
        self.dialog.onSave(None)
        self.saved_dat = (self.config / "display_systems.dat").read_text(encoding="utf-8")
        self.saved_persp = (self.config / f"{editor.display_sys.key}.persp").read_text(encoding="utf-8")

    def bezel_lines(self):
        text = (self.config / "display_systems.dat").read_text(encoding="utf-8")
        return [line for line in text.splitlines() if "bezel_mms" in line]


@pytest.fixture
def saved_study(gui_env, running_work, editor):
    study = SavedStudy(gui_env, running_work, editor)
    yield study
    study.dialog.Destroy()


def test_a_perspective_save_leaves_the_unsaved_band_edit_unsaved_in_the_editor_and_on_disk(
    running_work, editor, saved_study
):
    assert [line for line in saved_study.saved_dat.splitlines() if "bezel_mms" in line] == saved_study.saved_bezel_lines
    assert editor.display_sys.bezels_in_mm()[0] == (9.0, 0.0)
    assert running_work.session.display_system is not editor.display_sys
    assert running_work.session.display_system.bezels_in_mm() == saved_study.session_bezels


def test_the_editor_holds_its_own_copy_of_the_layout_and_the_dialog_another(editor, saved_study):
    assert saved_study.dialog.display_sys is not editor.display_sys
    assert editor.display_sys is not saved_study.session_layout


def test_the_saved_perspective_is_converted_with_the_saved_layouts_density(editor, saved_study):
    depth_line = next(line for line in saved_study.saved_persp.splitlines() if line.startswith("viewer_pos"))
    viewer_depth = float(depth_line.split("=")[1].split(",")[2])
    assert abs(viewer_depth - 600 * saved_study.saved_max_ppi / 25.4) < 1e-6
    assert editor.display_sys.max_ppi() != saved_study.saved_max_ppi


def test_a_saved_perspective_becomes_the_default_in_memory_and_on_disk_with_no_scratch_entry(editor, saved_study):
    assert editor.display_sys.default_perspective == "study"
    assert sorted(editor.display_sys.perspective_dict) == ["study"]
    assert "def_perspective = study" in saved_study.saved_dat
    assert saved_study.saved_persp.startswith("[study]\n")
    assert "\0" not in saved_study.saved_dat + saved_study.saved_persp


def test_the_perspective_dialogs_test_renders_a_draft(gui_env, running_work, saved_study):
    before = drafts(gui_env.paths.cache)
    gui_env.shown()
    saved_study.dialog.test_image = str(gui_env.images / "c.png")
    tested = saved_study.dialog.onTestWallpaper(None)
    gui_env.settle(running_work)
    assert tested == 1
    assert drafts(gui_env.paths.cache) != before
    assert not gui_env.shown()


@pytest.fixture
def ending_dialog(perspective_dialog):
    """A perspective dialog with a viewer distance, whose EndModal records the code instead of closing."""
    perspective_dialog.tclist_vieweroffs[2].SetValue("600")
    perspective_dialog.ended = []
    perspective_dialog.EndModal = perspective_dialog.ended.append
    return perspective_dialog


def test_a_reserved_perspective_name_keeps_the_dialog_open_with_a_message(gui_env, ending_dialog):
    ending_dialog.tc_name.SetValue("default")
    gui_env.shown()
    ending_dialog.onOk(None)
    errors = gui_env.shown()
    assert ending_dialog.ended == []
    assert len(errors) == 1
    assert "reserved" in errors[0][2]


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
    ending_dialog.persp_dict["default"] = dict(ending_dialog.persp_dict["study2"])
    ending_dialog.tc_name.SetValue("default")
    ending_dialog.ended.clear()
    gui_env.shown()
    ending_dialog.onOk(None)
    assert ending_dialog.ended == [gui_env.ui.wx.ID_OK]
    assert not gui_env.shown()
