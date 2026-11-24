"""Displays are detected again when the OS reports a change, once per burst of reports; an
open editor shows the new displays' layout, asking before it drops unsaved changes."""

from tests.conftest import TWO_DISPLAYS, monitor

THREE_DISPLAYS = [*TWO_DISPLAYS, monitor(3200, 0, 1920, 1080, 531, 299)]
LARGER_FIRST_DISPLAY = [monitor(0, 0, 2560, 1440, 597, 336), monitor(2560, 0, 1280, 1024, 376, 301)]


def count_use_displays(monkeypatch, superpaper):
    handed = []
    real = superpaper.session.use_displays
    monkeypatch.setattr(superpaper.session, "use_displays", lambda layout: (handed.append(layout), real(layout)))
    return handed


def current_panel(editor):
    return editor.frame._panel


def test_a_burst_of_reports_detects_the_displays_once(gui_env, monkeypatch, superpaper):
    handed = count_use_displays(monkeypatch, superpaper)

    gui_env.change_displays(THREE_DISPLAYS, notifications=5)
    assert handed == []
    gui_env.wait_for_displays(superpaper)

    assert len(handed) == 1
    assert len(handed[0].displays) == 3
    assert len(superpaper.layout.displays) == 3


def test_a_report_without_a_change_hands_the_session_nothing(gui_env, monkeypatch, superpaper):
    handed = count_use_displays(monkeypatch, superpaper)

    gui_env.change_displays(list(TWO_DISPLAYS))
    gui_env.wait_for_displays(superpaper)

    assert handed == []


def test_next_does_not_detect_the_displays_where_the_os_reports_changes(gui_env, running_work, monkeypatch):
    handed = count_use_displays(monkeypatch, running_work)
    gui_env.change_displays(THREE_DISPLAYS, notifications=0)

    gui_env.click(running_work, "Next Wallpaper")
    gui_env.settle(running_work)

    assert handed == []


def test_next_detects_the_displays_where_the_os_cannot_report_changes(gui_env, monkeypatch):
    gui_env.os_notifies = False
    superpaper = gui_env.start()
    gui_env.start_profile(superpaper, "Work")
    handed = count_use_displays(monkeypatch, superpaper)
    gui_env.change_displays(THREE_DISPLAYS, notifications=0)

    gui_env.click(superpaper, "Next Wallpaper")
    gui_env.settle(superpaper)

    assert len(handed) == 1
    assert len(superpaper.layout.displays) == 3


def test_the_open_editor_shows_the_new_displays_and_keeps_its_profile(gui_env, running_work, editor):
    assert len(editor.staged.layout.displays) == 2
    gui_env.shown()

    gui_env.change_displays(THREE_DISPLAYS)
    gui_env.wait_for_displays(running_work)

    panel = current_panel(editor)
    assert panel is not editor
    assert len(panel.staged.layout.displays) == 3
    assert panel.loaded_profile.profile.name == "Work"
    assert gui_env.shown() == []
    assert not panel.has_unsaved_changes()


def test_the_editor_asks_before_dropping_unsaved_display_settings(gui_env, running_work, editor):
    gui_env.answer_yes = False
    staged = editor.staged.layout.with_bezels([(6.0, 0.0), (0.0, 0.0)])
    editor.staged.layout = staged
    editor.display_band.update_dirty()

    gui_env.change_displays(THREE_DISPLAYS)
    gui_env.wait_for_displays(running_work)

    assert current_panel(editor) is editor
    assert editor.staged.layout is staged
    (_, _, question) = gui_env.shown()[-1]
    assert question.startswith("The displays changed")

    gui_env.answer_yes = True
    gui_env.change_displays(LARGER_FIRST_DISPLAY)
    gui_env.wait_for_displays(running_work)

    panel = current_panel(editor)
    assert panel is not editor
    assert panel.staged.layout.displays[0].resolution == (2560, 1440)
    assert not panel.display_band.has_unsaved_changes()


def test_unsaved_profile_changes_stay_when_the_number_of_displays_does(gui_env, running_work, editor):
    editor.tc_name.SetValue("Work renamed")
    assert editor.has_unsaved_profile_changes()
    gui_env.shown()

    gui_env.change_displays(LARGER_FIRST_DISPLAY)
    gui_env.wait_for_displays(running_work)

    panel = current_panel(editor)
    assert panel is not editor
    assert panel.tc_name.GetValue() == "Work renamed"
    assert panel.has_unsaved_profile_changes()
    assert panel.loaded_profile.profile.name == "Work"
    assert gui_env.shown() == []


def test_unsaved_profile_changes_are_kept_when_the_number_of_displays_changes(gui_env, running_work, editor):
    editor.tc_name.SetValue("Work renamed")
    gui_env.shown()

    gui_env.change_displays(THREE_DISPLAYS)
    gui_env.wait_for_displays(running_work)

    panel = current_panel(editor)
    assert panel is not editor
    assert len(panel.staged.layout.displays) == 3
    assert panel.tc_name.GetValue() == "Work renamed"
    assert panel.has_unsaved_profile_changes()
    assert len(panel._offset_fields()) == 3
    assert gui_env.shown() == []


def test_a_declined_change_is_asked_again_at_the_next_re_detect_point(gui_env, running_work, editor):
    gui_env.answer_yes = False
    editor.staged.layout = editor.staged.layout.with_bezels([(6.0, 0.0), (0.0, 0.0)])
    editor.display_band.update_dirty()
    gui_env.shown()
    gui_env.change_displays(THREE_DISPLAYS)
    gui_env.wait_for_displays(running_work)
    assert len(gui_env.shown()) == 1

    gui_env.start_profile(running_work, "Home")

    assert [kind for _, kind, _ in gui_env.shown()] == ["Displays changed"]
    assert current_panel(editor) is editor


def test_the_window_keeps_its_size_when_the_editor_is_rebuilt(gui_env, running_work, editor):
    editor.frame.SetSize(900, 700)
    size = editor.frame.GetSize()

    gui_env.change_displays(THREE_DISPLAYS)
    gui_env.wait_for_displays(running_work)

    assert current_panel(editor) is not editor
    assert editor.frame.GetSize() == size


MULTI = "name=Multi\nspanmode=multi\nslideshow=false\ndisplay0paths={images}\ndisplay1paths={images}\ndisplay2paths={images}\n"


def open_multi_after_a_display_vanished(gui_env, superpaper):
    gui_env.change_displays(THREE_DISPLAYS)
    gui_env.wait_for_displays(superpaper)
    gui_env.write_profile("Multi", MULTI.format(images=gui_env.images))
    superpaper.reload_profiles()
    gui_env.start_profile(superpaper, "Multi")
    panel = gui_env.open_editor(superpaper)
    assert panel.path_listctrl.GetItemCount() == 3
    gui_env.shown()
    gui_env.change_displays(TWO_DISPLAYS)
    gui_env.wait_for_displays(superpaper)
    return current_panel(panel)


def test_sources_of_a_vanished_display_are_kept_with_a_warning(gui_env, superpaper):
    panel = open_multi_after_a_display_vanished(gui_env, superpaper)

    assert len(panel.staged.layout.displays) == 2
    assert panel.path_listctrl.GetItemCount() == 3
    assert [text for _, _, text in gui_env.shown()] == [vanished_message()]
    assert not panel.has_unsaved_profile_changes()


def vanished_message():
    from superpaper.ui.editor import VANISHED_SOURCES_MESSAGE

    return VANISHED_SOURCES_MESSAGE.splitlines()[0]


def test_save_asks_before_removing_sources_of_a_vanished_display(gui_env, superpaper):
    panel = open_multi_after_a_display_vanished(gui_env, superpaper)
    gui_env.answer_yes = False

    assert panel._save_profile() is False
    assert panel.path_listctrl.GetItemCount() == 3

    gui_env.answer_yes = True
    saved = panel._save_profile()
    assert saved is True, gui_env.shown()
    assert panel.path_listctrl.GetItemCount() == 2


def test_a_display_change_during_a_modal_waits_until_it_closes(gui_env, superpaper, monkeypatch):
    panel = open_multi_after_a_display_vanished(gui_env, superpaper)

    def question(message, title="Info", parent=None):
        with gui_env.ui.message.modal():
            gui_env.change_displays(THREE_DISPLAYS)
            gui_env.wait_for_displays(superpaper)
            assert current_panel(panel) is panel
        return True

    monkeypatch.setattr(gui_env.ui.editor, "confirm", question)

    assert panel._save_profile() is True

    gui_env.wait_for_displays(superpaper)
    assert len(current_panel(panel).staged.layout.displays) == 3
    assert current_panel(panel) is not panel


def test_saving_the_display_settings_does_not_rebuild_the_editor(gui_env, running_work, editor):
    editor.staged.layout = editor.staged.layout.with_bezels([(4.5, 0.0), (0.0, 0.0)])
    editor.display_band.update_dirty()
    gui_env.shown()

    editor.display_band.onSave(None)
    gui_env.settle(running_work)

    assert current_panel(editor) is editor
    assert gui_env.shown() == []
