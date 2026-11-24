"""Apply and the running profile: Apply saves, shows the chosen image and runs the profile (E7, D1-D4);
Save never changes the desktop or the countdown (D13); the running profile is marked in the tray
and the editor (D11); the editor opens on the running profile, else the last one edited (D18)."""

from types import SimpleNamespace

import pytest

from superpaper.desktop.tray_menu import Check, Item, Notice, Submenu
from superpaper.profiles.profile_id import NEW_PROFILE_LABEL
from superpaper.unsaved_changes import ApplyAnswer

RUNNING = " (running)"


def click_row(editor, index):
    """Click the source list's row ``index``."""
    editor.path_listctrl.Focus(index)
    editor.onWallpaperItemSelected(SimpleNamespace(GetIndex=lambda: index))


def close_and_wait(gui_env, editor):
    """Close the editor and wait until its window is gone, so that the next one is a new window."""
    editor.frame.Close()
    gui_env.wait_until(lambda: not editor.frame)


def new_profile_of_two_images(gui_env, editor, name):
    """The editor on a new profile: a still of two images, b.png and c.png."""
    editor.tc_name.SetValue(name)
    editor.populate_lc_browse([[str(gui_env.images / "b.png")], [str(gui_env.images / "c.png")]])


def edit_displays(editor):
    band = editor.display_band
    band.cb_diaginch.SetValue(True)
    band.onCheckboxDiaginch(None)
    band.tc_list_diaginch[1].SetValue("30")
    assert band.has_unsaved_changes()


def layout_saved(gui_env):
    return (gui_env.paths.config / "display_systems.dat").exists()


def active(gui_env):
    path = gui_env.paths.cache / "running_profile"
    return path.read_text(encoding="utf-8") if path.exists() else None


def dropdown_labels(editor):
    return editor.choice_profiles.GetStrings()


def profiles_menu(superpaper):
    (profiles,) = (entry for entry in superpaper.tray.menu() if isinstance(entry, Submenu))
    return profiles.items


def next_and_pause(superpaper):
    entries = {entry.label: entry for entry in superpaper.tray.menu() if isinstance(entry, (Item, Check))}
    return entries["Next Wallpaper"], entries["Pause Timer"]


def test_creating_a_profile_and_applying_it_runs_it_and_the_editor_reopens_on_it(gui_env, superpaper):
    editor = gui_env.open_editor(superpaper)
    new_profile_of_two_images(gui_env, editor, "Fresh")
    click_row(editor, 1)
    gui_env.shown()
    commands = len(gui_env.commands)

    editor.onApply(None)
    gui_env.settle(superpaper)

    stored = gui_env.saved(superpaper, "Fresh")
    assert gui_env.shown() == []
    assert stored.selection.images == [str(gui_env.images / "c.png")]
    assert superpaper.session.running is stored
    assert active(gui_env) == "Fresh"
    assert len(gui_env.commands) == commands + 1
    assert editor._pick is None
    assert not editor.has_unsaved_profile_changes()
    assert "Fresh" + RUNNING in dropdown_labels(editor)
    assert [(item.label, item.checked) for item in profiles_menu(superpaper) if item.label == "Fresh"] == [
        ("Fresh", True)
    ]

    close_and_wait(gui_env, editor)
    reopened = gui_env.open_editor(superpaper)

    assert reopened.tc_name.GetValue() == "Fresh"
    assert reopened.choice_profiles.GetStringSelection() == "Fresh" + RUNNING


def test_apply_with_unsaved_edits_saves_them_first(gui_env, running_work, editor):
    editor.tc_sshow_delay.SetValue("15")
    assert editor.has_unsaved_profile_changes()
    commands = len(gui_env.commands)

    editor.onApply(None)
    gui_env.settle(running_work)

    assert "delay=900.0" in gui_env.profile_file("Work").read_text(encoding="utf-8")
    assert not editor.has_unsaved_profile_changes()
    assert running_work.session.running is gui_env.saved(running_work, "Work")
    assert running_work.session.running.profile.delay == 900.0
    assert len(gui_env.commands) == commands + 1


def test_apply_with_invalid_edits_shows_the_problems_and_does_nothing_else(gui_env, running_work, editor):
    editor.tc_sshow_delay.SetValue("abc")
    commands = len(gui_env.commands)
    gui_env.shown()

    editor.onApply(None)
    gui_env.settle(running_work)

    assert [dialog[:2] for dialog in gui_env.shown()] == [("editor", "Error")]
    assert gui_env.apply_prompts == []
    assert len(gui_env.commands) == commands
    assert editor.has_unsaved_profile_changes()


def test_apply_shows_the_clicked_image_not_the_next_one_and_unpauses(gui_env, running_work, editor):
    running_work.session.toggle_pause()
    gui_env.settle(running_work)
    click_row(editor, 0)
    pick = editor._pick[1]
    editor.tc_sshow_delay.SetValue("15")

    editor.onApply(None)
    gui_env.settle(running_work)

    assert running_work.session.running.selection.images == [pick]
    assert running_work.session.paused is False
    assert running_work.session._deadline is not None


def test_apply_on_the_running_profile_restarts_the_countdown(gui_env, running_work, editor):
    running_work.session._deadline = 1.0

    editor.onApply(None)
    gui_env.settle(running_work)

    assert running_work.session._deadline > 1.0


@pytest.mark.parametrize(
    ("answer", "saves_layout", "runs"),
    [
        (ApplyAnswer.SAVE_DISPLAYS, True, True),
        (ApplyAnswer.USE_SAVED_DISPLAYS, False, True),
        (ApplyAnswer.CANCEL, False, False),
    ],
)
def test_apply_with_unsaved_displays_asks_and_follows_the_answer(
    gui_env, running_work, editor, answer, saves_layout, runs
):
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    editor._select_in_dropdown("Home")
    edit_displays(editor)
    gui_env.apply_answer = answer

    editor.onApply(None)
    gui_env.settle(running_work)

    assert gui_env.apply_prompts == [True]
    assert layout_saved(gui_env) is saves_layout
    assert editor.display_band.has_unsaved_changes() is (not saves_layout)
    assert running_work.session.running.profile.name == ("Home" if runs else "Work")
    assert active(gui_env) == ("Home" if runs else "Work")
    if saves_layout:
        assert running_work.session.layout.settings() == editor.staged.layout.settings()


def test_apply_with_an_invalid_layout_offers_no_saving(gui_env, running_work, editor):
    edit_displays(editor)
    editor.display_band.tc_list_diaginch[1].SetValue("abc")
    gui_env.apply_answer = ApplyAnswer.USE_SAVED_DISPLAYS

    editor.onApply(None)
    gui_env.settle(running_work)

    assert gui_env.apply_prompts == [False]
    assert not layout_saved(gui_env)
    assert running_work.session.running.profile.name == "Work"


def test_apply_with_a_clean_layout_does_not_ask(gui_env, running_work, editor):
    editor.onApply(None)
    gui_env.settle(running_work)

    assert gui_env.apply_prompts == []


def test_save_does_not_change_the_desktop_or_the_countdown(gui_env, running_work, editor):
    gui_env.settle(running_work)
    commands = len(gui_env.commands)
    deadline = running_work.session._deadline
    shown = running_work.session.running.selection.images
    editor.tc_sshow_delay.SetValue("15")

    editor.onSave(None)
    gui_env.settle(running_work)

    assert len(gui_env.commands) == commands
    assert running_work.session._deadline == deadline
    assert running_work.session.running.profile.delay == 900.0
    assert running_work.session.running.selection.images == shown


def test_save_with_a_clicked_image_selects_it_without_showing_it_and_does_not_start_a_profile(
    gui_env, running_work, editor
):
    gui_env.settle(running_work)
    commands = len(gui_env.commands)
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    editor._select_in_dropdown("Home")
    click_row(editor, 0)
    pick = editor._pick[1]
    editor.sld_zoom.SetValue(150)
    editor.onZoomOffsetChange(None)

    editor.onSave(None)
    gui_env.settle(running_work)

    assert gui_env.saved(running_work, "Home").selection.images == [pick]
    assert running_work.session.running.profile.name == "Work"
    assert len(gui_env.commands) == commands
    assert active(gui_env) == "Work"
    assert editor._pick is None


def test_a_paused_slideshow_stays_paused_and_unmoved_when_its_profile_is_saved(gui_env, running_work, editor):
    running_work.session.toggle_pause()
    gui_env.settle(running_work)
    editor.tc_sshow_delay.SetValue("15")

    editor.onSave(None)
    gui_env.settle(running_work)

    assert running_work.session.paused is True
    assert running_work.session._deadline is None


def test_the_clicked_image_is_forgotten_when_the_profile_changes(gui_env, running_work, editor):
    click_row(editor, 0)
    assert editor._pick is not None

    editor.populate_fields(gui_env.saved(running_work, "Home"))
    assert editor._pick is None

    click_row(editor, 0)
    editor.onCreateNewProfile(None)
    assert editor._pick is None

    editor.populate_fields(gui_env.saved(running_work, "Home"))
    click_row(editor, 0)
    editor.onRevert(None)
    assert editor._pick is None


def test_removing_the_clicked_source_forgets_the_clicked_image(gui_env, running_work, editor):
    click_row(editor, 0)

    editor.onRemoveSource(None)

    assert editor._pick is None


def test_a_click_that_resolves_no_image_leaves_the_clicked_image_unchanged(gui_env, running_work, editor):
    click_row(editor, 0)
    pick = editor._pick
    editor.populate_lc_browse([[str(gui_env.root / "missing-folder")]])

    click_row(editor, 1)

    assert editor._pick == pick


def test_the_clicked_image_goes_when_its_source_is_no_longer_listed(gui_env, running_work, editor):
    editor.populate_lc_browse([[str(gui_env.images / "b.png")]])
    click_row(editor, 1)
    assert editor._pick is not None

    editor.path_listctrl.DeleteItem(1)
    editor._update_dirty_state()

    assert editor._pick is None


def test_a_loaded_profile_deleted_by_reload_while_clean_becomes_a_new_profile(gui_env, running_work, editor):
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    editor._select_in_dropdown("Home")
    gui_env.profile_file("Home").unlink()

    gui_env.click(running_work, "Reload Profiles")
    gui_env.settle(running_work)

    assert editor.loaded_profile is None
    assert editor.tc_name.GetValue() == ""
    assert editor._dropdown_name() == NEW_PROFILE_LABEL
    assert not editor.has_unsaved_profile_changes()


def test_a_loaded_profile_deleted_by_reload_while_dirty_keeps_its_form_to_be_saved_anew(gui_env, running_work, editor):
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    editor._select_in_dropdown("Home")
    editor.tc_name.SetValue("Home")
    editor.sld_zoom.SetValue(150)
    editor.onZoomOffsetChange(None)
    gui_env.profile_file("Home").unlink()

    gui_env.click(running_work, "Reload Profiles")
    gui_env.settle(running_work)

    assert editor.loaded_profile is None
    assert editor.tc_name.GetValue() == "Home"
    assert editor._dropdown_name() == NEW_PROFILE_LABEL
    assert editor.has_unsaved_profile_changes()
    assert editor.button_save.IsEnabled()

    editor.onSave(None)
    gui_env.settle(running_work)

    assert "zoom=1.5" in gui_env.profile_file("Home").read_text(encoding="utf-8")
    assert editor.loaded_profile is gui_env.saved(running_work, "Home")
    assert not editor.has_unsaved_profile_changes()


def test_editing_another_profile_while_one_runs_changes_nothing_until_it_is_applied(gui_env, running_work, editor):
    gui_env.settle(running_work)
    commands = len(gui_env.commands)
    editor.onSelect(select_event(editor, "Home"))
    assert editor.tc_name.GetValue() == "Home"
    editor.sld_zoom.SetValue(150)
    editor.onZoomOffsetChange(None)

    editor.onSave(None)
    gui_env.settle(running_work)

    assert "zoom=1.5" in gui_env.profile_file("Home").read_text(encoding="utf-8")
    assert running_work.session.running.profile.name == "Work"
    assert len(gui_env.commands) == commands
    assert "Work" + RUNNING in dropdown_labels(editor)

    editor.onApply(None)
    gui_env.settle(running_work)

    assert running_work.session.running.profile.name == "Home"
    assert len(gui_env.commands) == commands + 1
    assert running_work.session._deadline is None
    assert "Home" + RUNNING in dropdown_labels(editor)
    assert "Work" in dropdown_labels(editor)
    assert active(gui_env) == "Home"


def select_event(editor, name):
    """The dropdown's selection event for the profile ``name``, as wx sends it after the selection changed."""
    import wx

    editor._select_in_dropdown(name)
    event = wx.CommandEvent(wx.EVT_COMBOBOX.typeId, editor.choice_profiles.GetId())
    event.SetEventObject(editor.choice_profiles)
    event.SetInt(editor.choice_profiles.GetSelection())
    return event


def test_the_dropdown_marker_follows_every_change_of_the_running_profile(gui_env, running_work, editor):
    def marked():
        gui_env.settle(running_work)
        return [label for label in dropdown_labels(editor) if label.endswith(RUNNING)]

    assert marked() == ["Work" + RUNNING]

    gui_env.start_profile(running_work, "Home")
    assert marked() == ["Home" + RUNNING]

    running_work.start_profile(gui_env.saved(running_work, "Work"))
    assert marked() == ["Work" + RUNNING]

    gui_env.profile_file("Work").unlink()
    gui_env.click(running_work, "Reload Profiles")
    gui_env.start_profile(running_work, "Home")
    assert marked() == ["Home" + RUNNING]

    editor.populate_fields(gui_env.saved(running_work, "Home"))
    editor._select_in_dropdown("Home")
    gui_env.yes_to_message_dialogs()
    editor.onDeleteProfile(None)
    assert marked() == []


def test_the_tray_marks_the_running_profile_and_enables_next_and_pause(gui_env, superpaper):
    next_item, pause = next_and_pause(superpaper)
    assert (next_item.enabled, pause.enabled) == (False, False)
    assert not any(item.checked for item in profiles_menu(superpaper) if isinstance(item, Check))

    gui_env.start_profile(superpaper, "Work")

    next_item, pause = next_and_pause(superpaper)
    assert (next_item.enabled, pause.enabled) == (True, True)
    assert [item.label for item in profiles_menu(superpaper) if item.checked] == ["Work"]

    gui_env.start_profile(superpaper, "Home")

    next_item, pause = next_and_pause(superpaper)
    assert (next_item.enabled, pause.enabled) == (True, False)
    assert [item.label for item in profiles_menu(superpaper) if item.checked] == ["Home"]


def test_the_tray_has_a_disabled_placeholder_when_there_are_no_profiles(gui_env):
    for path in gui_env.paths.profiles.iterdir():
        path.unlink()

    superpaper = gui_env.start()

    assert profiles_menu(superpaper) == (Notice("(no profiles)"),)


def test_picking_the_running_profile_in_the_tray_only_unpauses_and_restarts_the_countdown(gui_env, running_work):
    gui_env.settle(running_work)
    commands = len(gui_env.commands)
    shown = running_work.session.running.selection.images
    running_work.session.toggle_pause()
    gui_env.settle(running_work)
    assert running_work.session.paused is True

    gui_env.start_profile(running_work, "Work")

    assert running_work.session.paused is False
    assert running_work.session._deadline is not None
    assert len(gui_env.commands) == commands
    assert running_work.session.running.selection.images == shown


def test_deleting_the_running_profile_clears_the_remembered_one(gui_env, running_work, editor):
    assert active(gui_env) == "Work"
    gui_env.yes_to_message_dialogs()

    editor.onDeleteProfile(None)
    gui_env.settle(running_work)

    assert active(gui_env) is None
    assert running_work.session.running is None
    next_item, pause = next_and_pause(running_work)
    assert (next_item.enabled, pause.enabled) == (False, False)


def test_the_editor_opens_on_the_profile_last_edited_while_nothing_runs(gui_env, superpaper):
    editor = gui_env.open_editor(superpaper)
    assert editor.tc_name.GetValue() == ""
    editor.populate_fields(gui_env.saved(superpaper, "Home"))
    close_and_wait(gui_env, editor)

    reopened = gui_env.open_editor(superpaper)

    assert reopened.tc_name.GetValue() == "Home"
    assert reopened.choice_profiles.GetStringSelection() == "Home"


def test_the_editor_opens_on_the_running_profile_before_the_last_edited_one(gui_env, running_work, editor):
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    close_and_wait(gui_env, editor)

    reopened = gui_env.open_editor(running_work)

    assert reopened.tc_name.GetValue() == "Work"


def test_a_last_edited_profile_that_was_deleted_opens_a_new_one(gui_env, superpaper):
    editor = gui_env.open_editor(superpaper)
    editor.populate_fields(gui_env.saved(superpaper, "Home"))
    close_and_wait(gui_env, editor)
    gui_env.profile_file("Home").unlink()
    gui_env.click(superpaper, "Reload Profiles")

    reopened = gui_env.open_editor(superpaper)

    assert reopened.tc_name.GetValue() == ""
    assert reopened._dropdown_name() == NEW_PROFILE_LABEL


def test_saving_a_profile_makes_it_the_one_the_editor_reopens_on(gui_env, superpaper):
    editor = gui_env.open_editor(superpaper)
    new_profile_of_two_images(gui_env, editor, "Fresh")
    editor.onSave(None)
    gui_env.settle(superpaper)
    close_and_wait(gui_env, editor)

    reopened = gui_env.open_editor(superpaper)

    assert reopened.tc_name.GetValue() == "Fresh"
    assert superpaper.session.running is None
    assert active(gui_env) is None
