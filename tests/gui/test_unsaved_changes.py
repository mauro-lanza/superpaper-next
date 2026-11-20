"""Leaving the editor with unsaved changes (D5): Close, the window's own close, switching
profile, New and the tray's Exit ask whether to save, discard or keep editing; D25: saving the
profile leaves the display band unsaved."""

import pytest
import wx

from superpaper.profiles.profile_id import NEW_PROFILE_LABEL
from superpaper.ui.display_band import LABEL, UNSAVED_MARKER
from superpaper.unsaved_changes import Answer

PROFILE_ONLY = "The profile has unsaved changes."
DISPLAYS_ONLY = "The display layout has unsaved changes."
BOTH = "The profile and the display layout have unsaved changes."
EDITED_DELAY = "delay=42000.0"  # the 700 minutes typed in edit_profile


def edit_profile(editor, delay="700"):
    editor.tc_sshow_delay.SetValue(delay)
    assert editor.has_unsaved_profile_changes()


def edit_displays(editor):
    band = editor.display_band
    band.cb_diaginch.SetValue(True)
    band.onCheckboxDiaginch(None)
    band.tc_list_diaginch[1].SetValue("30")
    assert band.has_unsaved_changes()


def stored_delay(gui_env, name):
    return next(line for line in gui_env.profile_file(name).read_text().splitlines() if line.startswith("delay="))


def layout_saved(gui_env):
    return (gui_env.paths.config / "display_systems.dat").exists()


def is_open(editor):
    # A closed window is destroyed once the event loop is idle.
    wx.YieldIfNeeded()
    return bool(editor.frame)


def close_by_window_manager(editor):
    editor.frame.Close()


def close_by_button(editor):
    editor.onClose(None)


CLOSES = [close_by_button, close_by_window_manager]


@pytest.mark.parametrize("close", CLOSES)
def test_closing_a_clean_editor_does_not_ask(gui_env, editor, close):
    close(editor)

    assert gui_env.unsaved_prompts == []
    assert not is_open(editor)


@pytest.mark.parametrize("close", CLOSES)
@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda editor: edit_profile(editor), PROFILE_ONLY),
        (edit_displays, DISPLAYS_ONLY),
        (lambda editor: (edit_profile(editor), edit_displays(editor)), BOTH),
    ],
)
def test_closing_asks_one_question_naming_what_is_unsaved(gui_env, editor, close, edit, message):
    edit(editor)
    gui_env.unsaved_answer = Answer.CANCEL

    close(editor)

    assert gui_env.unsaved_prompts == [message]
    assert is_open(editor)


@pytest.mark.parametrize("close", CLOSES)
def test_discarding_closes_without_saving_anything(gui_env, editor, close):
    edit_profile(editor)
    edit_displays(editor)
    gui_env.unsaved_answer = Answer.DISCARD

    close(editor)

    assert not is_open(editor)
    assert stored_delay(gui_env, "Work") == "delay=600"
    assert not layout_saved(gui_env)


@pytest.mark.parametrize("close", CLOSES)
def test_saving_saves_the_profile_and_the_displays_and_closes(gui_env, running_work, editor, close):
    edit_profile(editor)
    edit_displays(editor)
    gui_env.unsaved_answer = Answer.SAVE

    close(editor)
    gui_env.settle(running_work)

    assert not is_open(editor)
    assert stored_delay(gui_env, "Work") == EDITED_DELAY
    assert layout_saved(gui_env)


def test_saving_only_the_displays_when_only_they_changed(gui_env, editor):
    edit_displays(editor)
    gui_env.unsaved_answer = Answer.SAVE

    editor.onClose(None)

    assert not is_open(editor)
    assert layout_saved(gui_env)
    assert stored_delay(gui_env, "Work") == "delay=600"


@pytest.mark.parametrize("close", CLOSES)
def test_a_failed_profile_save_keeps_the_editor_open_and_shows_the_error(gui_env, editor, close):
    edit_profile(editor, delay="abc")
    edit_displays(editor)
    gui_env.unsaved_answer = Answer.SAVE
    gui_env.shown()

    close(editor)

    assert is_open(editor)
    assert [dialog[:2] for dialog in gui_env.shown()] == [("editor", "Error")]
    assert not layout_saved(gui_env)


def test_a_failed_display_save_keeps_the_editor_open_and_shows_the_error(gui_env, editor):
    edit_displays(editor)
    editor.display_band.tc_list_diaginch[1].SetValue("abc")
    gui_env.unsaved_answer = Answer.SAVE
    gui_env.shown()

    editor.onClose(None)

    assert is_open(editor)
    assert [dialog[:2] for dialog in gui_env.shown()] == [("display_band", "Error")]
    assert not layout_saved(gui_env)


def test_a_close_that_cannot_be_vetoed_discards_without_asking(gui_env, editor, caplog):
    from superpaper.ui.editor import logger

    edit_profile(editor)

    with caplog.at_level("WARNING", logger=logger.name):
        assert editor.allow_close(can_veto=False)

    assert gui_env.unsaved_prompts == []
    assert "discarding its unsaved changes" in caplog.text


@pytest.mark.parametrize("answer", [Answer.CANCEL, Answer.DISCARD])
def test_switching_profile_asks_only_about_the_profile(gui_env, editor, answer):
    edit_profile(editor)
    edit_displays(editor)
    gui_env.unsaved_answer = answer

    editor.choice_profiles.SetSelection(editor.choice_profiles.FindString("Home"))
    editor.onSelect(select_event(editor, "Home"))

    assert gui_env.unsaved_prompts == [PROFILE_ONLY]
    expected = "Home" if answer is Answer.DISCARD else "Work"
    assert editor.choice_profiles.GetStringSelection() == expected
    assert editor.tc_name.GetValue() == expected
    assert editor.display_band.has_unsaved_changes()


def test_cancelling_a_switch_keeps_the_edits(gui_env, editor):
    edit_profile(editor)
    gui_env.unsaved_answer = Answer.CANCEL

    editor.onSelect(select_event(editor, "Home"))

    assert editor.tc_sshow_delay.GetValue() == "700"
    assert editor.has_unsaved_profile_changes()


def test_saving_before_a_switch_stores_the_edits_and_switches(gui_env, editor):
    edit_profile(editor)
    gui_env.unsaved_answer = Answer.SAVE

    editor.onSelect(select_event(editor, "Home"))

    assert stored_delay(gui_env, "Work") == EDITED_DELAY
    assert editor.tc_name.GetValue() == "Home"
    assert not editor.has_unsaved_profile_changes()


def test_a_failed_save_before_a_switch_stays_on_the_profile(gui_env, editor):
    edit_profile(editor, delay="abc")
    gui_env.unsaved_answer = Answer.SAVE

    editor.onSelect(select_event(editor, "Home"))

    assert editor.tc_name.GetValue() == "Work"
    assert editor.choice_profiles.GetStringSelection() == "Work"
    assert editor.has_unsaved_profile_changes()


def test_switching_a_clean_profile_does_not_ask(gui_env, editor):
    editor.onSelect(select_event(editor, "Home"))

    assert gui_env.unsaved_prompts == []
    assert editor.tc_name.GetValue() == "Home"


@pytest.mark.parametrize(("answer", "blank"), [(Answer.DISCARD, True), (Answer.CANCEL, False), (Answer.SAVE, True)])
def test_new_profile_asks_the_same_question(gui_env, editor, answer, blank):
    edit_profile(editor)
    gui_env.unsaved_answer = answer

    editor.onSelect(select_event(editor, NEW_PROFILE_LABEL))

    assert gui_env.unsaved_prompts == [PROFILE_ONLY]
    assert (editor.tc_name.GetValue() == "") is blank
    assert editor.choice_profiles.GetStringSelection() == (NEW_PROFILE_LABEL if blank else "Work")
    if answer is Answer.SAVE:
        assert stored_delay(gui_env, "Work") == EDITED_DELAY


def test_the_marker_shows_while_the_displays_are_unsaved_and_goes_with_save_or_revert(gui_env, editor):
    band = editor.display_band
    assert band.GetLabel() == LABEL

    edit_displays(editor)
    assert UNSAVED_MARKER in band.GetLabel()

    band.onRevert(None)
    assert band.GetLabel() == LABEL

    edit_displays(editor)
    band.onSave(None)
    assert band.GetLabel() == LABEL


def test_saving_the_profile_leaves_the_displays_unsaved(gui_env, editor):
    edit_profile(editor)
    edit_displays(editor)

    editor.onSave(None)

    assert stored_delay(gui_env, "Work") == EDITED_DELAY
    assert not layout_saved(gui_env)
    assert UNSAVED_MARKER in editor.display_band.GetLabel()
    assert editor.display_band.button_system_save.IsEnabled()


def exit_with_unsaved_changes(gui_env, superpaper, answer):
    gui_env.unsaved_answer = answer
    gui_env.menu_entry(superpaper, "Exit").action()


def test_exit_with_a_clean_editor_quits_without_asking(gui_env, running_work, editor):
    gui_env.quit(running_work)

    assert gui_env.unsaved_prompts == []


def test_exit_without_an_editor_quits_without_asking(gui_env, running_work):
    gui_env.quit(running_work)

    assert gui_env.unsaved_prompts == []


def test_exit_cancelled_keeps_the_application_and_the_edits(gui_env, running_work, editor):
    edit_profile(editor)
    edit_displays(editor)

    exit_with_unsaved_changes(gui_env, running_work, Answer.CANCEL)

    assert gui_env.unsaved_prompts == [BOTH]
    assert running_work.tray.menu()
    assert is_open(editor)
    assert editor.has_unsaved_profile_changes()
    assert running_work.session.running is not None


def test_exit_with_a_failed_save_does_not_quit(gui_env, running_work, editor):
    edit_profile(editor, delay="abc")

    exit_with_unsaved_changes(gui_env, running_work, Answer.SAVE)

    assert gui_env.unsaved_prompts == [PROFILE_ONLY]
    assert running_work.session.running is not None
    assert editor.has_unsaved_profile_changes()


def test_exit_after_saving_stores_both_and_quits(gui_env, running_work, editor):
    edit_profile(editor)
    edit_displays(editor)
    gui_env.started.remove(running_work)

    exit_with_unsaved_changes(gui_env, running_work, Answer.SAVE)

    assert stored_delay(gui_env, "Work") == EDITED_DELAY
    assert layout_saved(gui_env)


def test_exit_after_discarding_quits_and_saves_nothing(gui_env, running_work, editor):
    edit_profile(editor)
    gui_env.started.remove(running_work)

    exit_with_unsaved_changes(gui_env, running_work, Answer.DISCARD)

    assert stored_delay(gui_env, "Work") == "delay=600"


def test_a_second_close_or_exit_during_the_question_is_refused_without_asking_again(gui_env, running_work, editor):
    edit_profile(editor)
    nested = []

    def ask_then_close_again(message, parent=None):
        gui_env.unsaved_prompts.append(message)
        nested.append(editor.settle_unsaved_changes())
        nested.append(editor.allow_close(can_veto=True))
        editor.frame.Close()
        return Answer.CANCEL

    gui_env.monkeypatch.setattr(gui_env.ui.editor, "ask_unsaved_changes", ask_then_close_again)

    assert editor.settle_unsaved_changes() is False

    assert nested == [False, False]
    assert gui_env.unsaved_prompts == [PROFILE_ONLY]
    assert is_open(editor)


def test_the_guard_is_released_after_the_question(gui_env, editor):
    edit_profile(editor)
    gui_env.unsaved_answer = Answer.CANCEL

    assert editor.settle_unsaved_changes() is False
    assert editor.settle_unsaved_changes() is False

    assert len(gui_env.unsaved_prompts) == 2


def select_event(editor, label):
    """The dropdown's selection event for ``label``, as wx sends it after the selection changed."""
    import wx

    editor.choice_profiles.SetSelection(editor.choice_profiles.FindString(label))
    event = wx.CommandEvent(wx.EVT_COMBOBOX.typeId, editor.choice_profiles.GetId())
    event.SetEventObject(editor.choice_profiles)
    event.SetString(label)
    event.SetInt(editor.choice_profiles.GetSelection())
    return event
