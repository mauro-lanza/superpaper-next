"""Smaller spec items of the editor: Browse OK (E5), source notes (E6), one image per display (D12b),
profile hotkeys (E4, D24, S2), a single display (X3) and Reload Profiles (T8)."""

from types import SimpleNamespace

from tests.conftest import TWO_DISPLAYS

MULTI = "name=Multi\nspanmode=multi\nslideshow=false\ndisplay0paths={images}\ndisplay1paths={images}\n"


def click_row(editor, index):
    editor.path_listctrl.Focus(index)
    editor.onWallpaperItemSelected(SimpleNamespace(GetIndex=lambda: index))


def sources(editor):
    return [editor.path_listctrl.GetItemText(row, 0) for row in range(editor.path_listctrl.GetItemCount())]


def test_browse_ok_adds_new_sources_and_ignores_duplicates(gui_env, running_work, editor):
    listed = sources(editor)
    extra = str(gui_env.images / "a.png")

    editor.populate_lc_browse([[listed[0]], [extra], [extra]])

    assert sources(editor) == [*listed, extra]
    assert editor.has_unsaved_profile_changes()


def test_the_browse_dialog_lists_a_source_once(gui_env, running_work, editor):
    browse = gui_env.open_browse(editor)
    assert browse.paths_listctrl.GetItemCount() == 0
    browse.dir3.SetPath(str(gui_env.images))

    browse.onAdd(None)
    browse.onAdd(None)

    assert browse.paths_listctrl.GetItemCount() == 1


def test_a_missing_source_row_shows_a_note_and_keeps_the_pick(gui_env, running_work, editor):
    click_row(editor, 0)
    pick = editor._pick
    editor.path_listctrl.SetItem(0, 0, str(gui_env.root / "gone"))

    click_row(editor, 0)

    assert "was not found" in editor.st_source_note.GetLabel()
    assert editor._pick == pick


def test_a_profile_whose_images_are_gone_shows_a_note(gui_env, running_work, editor):
    editor.populate_fields(gui_env.saved(running_work, "Nas"))

    assert editor.st_source_note.GetLabel() == "The images of this profile were not found."


def test_clicking_a_row_in_multi_mode_changes_only_that_display(gui_env, running_work, editor, monkeypatch):
    gui_env.write_profile("Multi", MULTI.format(images=gui_env.images))
    gui_env.click(running_work, "Reload Profiles")
    gui_env.start_profile(running_work, "Multi")
    editor.populate_fields(gui_env.saved(running_work, "Multi"))
    editor.path_listctrl.SetItem(1, 1, str(gui_env.images / "b.png"))
    shown = editor.loaded_profile.selection.current()
    previews = []
    monkeypatch.setattr(editor.wpprev_pnl, "preview_wallpaper", lambda images, *args: previews.append(images))

    click_row(editor, 1)

    expected = [shown[0], str(gui_env.images / "b.png")]
    assert previews == [expected]
    assert editor._picked_images() == expected
    assert editor._pick is None


def test_the_profile_hotkey_field_stays_editable_with_a_note_while_hotkeys_are_off(gui_env, running_work, editor):
    editor.cb_hotkey.SetValue(True)
    editor.onCheckboxHotkey(None)

    assert editor.tc_hotkey_bind.IsEnabled()
    assert editor.st_hotkeys_off.GetLabel() == "Hotkeys are off in Settings"
    assert editor.st_hotkeys_off.IsShown()


def test_the_hotkeys_off_note_follows_the_setting_on_open_and_when_a_profile_loads(gui_env, running_work, editor):
    from dataclasses import replace

    assert editor.st_hotkeys_off.IsShown()

    running_work.update_settings(replace(running_work.settings, use_hotkeys=True))
    editor.populate_fields(gui_env.saved(running_work, "Home"))

    assert not editor.st_hotkeys_off.IsShown()


def test_a_profile_hotkey_used_elsewhere_is_refused_on_save(gui_env, running_work, editor):
    gui_env.write_profile("Keyed", "name=Keyed\nspanmode=single\nslideshow=false\nhotkey=control+x\n")
    gui_env.click(running_work, "Reload Profiles")
    gui_env.shown()
    editor.cb_hotkey.SetValue(True)
    editor.tc_hotkey_bind.SetValue("control+x")

    assert editor._save_profile() is False

    assert gui_env.shown() == [("editor", "Error", "The hotkey 'control+x' is already used by the profile 'Keyed'.")]
    assert "hotkey=" not in gui_env.profile_file("Work").read_text(encoding="utf-8")


def test_the_settings_dialog_refuses_hotkeys_that_clash(gui_env, superpaper):
    ui = gui_env.ui
    frame = ui.settings_dialog.SettingsFrame(lambda: superpaper.settings, save_settings=superpaper.apply_settings)
    panel = gui_env.child_of(frame, ui.settings_dialog.SettingsPanel)
    before = gui_env.settings_path.read_text(encoding="utf-8")
    panel.tc_hk_next.SetValue("control+n")
    panel.tc_hk_pause.SetValue("control+n")
    gui_env.shown()

    panel.onSave(None)

    assert [kind for _, kind, _ in gui_env.shown()] == ["Error"]
    assert gui_env.settings_path.read_text(encoding="utf-8") == before
    frame.Destroy()


def test_a_single_display_disables_positions_and_the_per_display_controls(gui_env, superpaper):
    gui_env.change_displays(TWO_DISPLAYS[:1])
    gui_env.wait_for_displays(superpaper)

    editor = gui_env.open_editor(superpaper)
    editor.populate_fields(gui_env.saved(superpaper, "Work"))

    assert not editor.cb_spangroups.IsEnabled()
    assert not editor.cb_offsets.IsEnabled()
    assert not editor.wpprev_pnl.layout_editor.button_config.IsEnabled()


def test_reload_profiles_shows_an_outside_edit_in_a_clean_form_and_keeps_a_dirty_one(gui_env, running_work, editor):
    work = gui_env.profile_file("Work")

    work.write_text(work.read_text(encoding="utf-8").replace("delay=600", "delay=900"), encoding="utf-8")
    gui_env.click(running_work, "Reload Profiles")
    assert editor.tc_sshow_delay.GetValue() == "15.0"
    assert not editor.has_unsaved_profile_changes()

    editor.tc_sshow_delay.SetValue("20")
    work.write_text(work.read_text(encoding="utf-8").replace("delay=900", "delay=1200"), encoding="utf-8")
    gui_env.click(running_work, "Reload Profiles")
    assert editor.tc_sshow_delay.GetValue() == "20"
    assert editor.has_unsaved_profile_changes()
