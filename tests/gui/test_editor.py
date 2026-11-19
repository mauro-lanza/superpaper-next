import threading
from types import SimpleNamespace

import pytest

from superpaper.profiles.form import spangroups_of
from superpaper.profiles.profile_id import ProfileId
from superpaper.profiles.profile_store import ProfileStore


def slideshow_armed(superpaper):
    return superpaper.session._deadline is not None


def drafts(cache):
    return list((cache / "preview").glob("draft-?.png"))


def colour_at(bitmap, x, y):
    image = bitmap.ConvertToImage()
    return (image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y))


def test_the_editor_opens_on_the_running_profile(editor):
    assert editor.tc_name.GetValue() == "Work"


def test_the_editor_has_one_offset_group_and_diagonal_field_per_display(running_work, editor):
    displays = len(running_work.session.layout.displays)
    counts = (len(editor.tc_list_offsets), len(editor.ch_list_spangroups), len(editor.display_band.tc_list_diaginch))
    assert displays == 2
    assert counts == (displays,) * 3


def test_apply_renders_a_draft_and_leaves_the_running_render_alone(gui_env, running_work, editor):
    editor.onApply(None)
    gui_env.settle(running_work)
    assert drafts(gui_env.paths.cache)
    assert (gui_env.paths.cache / "Work-a.png").is_file()


@pytest.fixture
def applied_then_saved(gui_env, running_work, editor):
    gui_env.shown()
    assert "selected=" not in gui_env.profile_file("Work").read_text(encoding="utf-8")
    editor.onApply(None)
    gui_env.settle(running_work)
    store = ProfileStore(gui_env.paths)
    store.reload()
    stored = store.get(ProfileId("Work")).selection.images
    editor.tc_sshow_delay.SetValue("15")
    editor.onSave(None)
    gui_env.settle(running_work)
    work_text = gui_env.profile_file("Work").read_text(encoding="utf-8")
    return stored, gui_env.shown(), work_text


def test_apply_then_save_shows_no_error(applied_then_saved):
    assert not applied_then_saved[1]


def test_apply_keeps_the_selection_out_of_the_profile_file(applied_then_saved):
    stored, _, work_text = applied_then_saved
    assert stored
    assert "selected=" not in work_text


def test_apply_then_save_writes_the_edit_to_disk(applied_then_saved):
    assert "delay=900.0" in applied_then_saved[2]


def test_after_save_the_editor_and_the_slideshow_hold_the_stores_one_record(
    gui_env, running_work, editor, applied_then_saved
):
    assert editor.loaded_profile is gui_env.saved(running_work, "Work") is running_work.session.running
    assert running_work.session.running.profile.delay == 900.0


@pytest.fixture
def home_edited_outside(gui_env, running_work, editor):
    """Home saved at zoom 150% in the editor, then its file changed to 175% behind its back."""
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    editor.sld_zoom.SetValue(150)
    editor.onZoomOffsetChange(None)
    editor.onSave(None)
    gui_env.settle(running_work)
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    editor.choice_profiles.SetSelection(editor.choice_profiles.FindString("Home"))
    home = gui_env.profile_file("Home")
    home.write_text(home.read_text(encoding="utf-8").replace("zoom=1.5", "zoom=1.75"), encoding="utf-8")
    gui_env.shown()
    return home


def test_saving_over_a_profile_changed_outside_the_editor_is_refused_pointing_at_revert(
    gui_env, home_edited_outside, editor
):
    editor.onSave(None)
    errors = gui_env.shown()
    assert len(errors) == 1
    assert "Revert" in errors[0][2]
    assert "zoom=1.75" in home_edited_outside.read_text(encoding="utf-8")


def test_revert_loads_the_change_made_outside_the_editor(gui_env, running_work, home_edited_outside, editor):
    editor.onRevert(None)
    assert editor.loaded_profile is gui_env.saved(running_work, "Home")
    assert editor.loaded_profile.profile.zoom == 1.75
    assert editor.sld_zoom.GetValue() == 175


def test_a_profile_picked_after_revert_is_the_one_named_when_the_profiles_changed_outside(
    gui_env, running_work, editor
):
    gui_env.write_profile("Aaa", "name=Aaa\nspanmode=single\nslideshow=false\n")
    editor.onRevert(None)
    dropdown = editor.choice_profiles
    dropdown.SetSelection(dropdown.FindString("Home"))

    editor.onSelect(
        SimpleNamespace(
            GetEventObject=lambda: dropdown,
            GetSelection=dropdown.GetSelection,
            GetString=lambda: dropdown.GetString(dropdown.GetSelection()),
        )
    )

    assert editor.tc_name.GetValue() == "Home"


def test_after_revert_the_profile_saves(gui_env, home_edited_outside, editor):
    editor.onRevert(None)
    editor.onSave(None)
    assert not gui_env.shown()
    assert "zoom=1.75" in home_edited_outside.read_text(encoding="utf-8")


def test_deleting_the_running_profile_stops_its_slideshow_and_forgets_its_selection(gui_env, running_work, editor):
    gui_env.write_profile(
        "Temp",
        f"name=Temp\nspanmode=single\nslideshow=true\ndelay=600\nsortmode=alphabetical\ndisplay0paths={gui_env.images}\n",
    )
    gui_env.click(running_work, "Reload Profiles")
    gui_env.start_profile(running_work, "Temp")
    armed = slideshow_armed(running_work)
    selection = gui_env.paths.cache / "selections" / "Temp.json"
    had_selection = selection.is_file()
    editor.update_choiceprofile()
    editor.choice_profiles.SetSelection(editor.choice_profiles.FindString("Temp"))
    editor.populate_fields(gui_env.saved(running_work, "Temp"))
    gui_env.yes_to_message_dialogs()
    gui_env.shown()
    editor.onDeleteProfile(None)
    gui_env.settle(running_work)
    assert not gui_env.profile_file("Temp").exists()
    assert running_work.session.running is None
    assert armed
    assert not slideshow_armed(running_work)
    assert had_selection
    assert not selection.exists()
    assert gui_env.shown() == [("editor", "Confirm Delete", "Do you want to delete profile: Temp?")]


def test_save_doesnt_ask_about_a_broken_profile_but_reload_profiles_does(gui_env, running_work, editor):
    gui_env.write_profile("Broken2", "name=Broken2\ndelay=soon\n")
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    editor.choice_profiles.SetSelection(editor.choice_profiles.FindString("Home"))
    gui_env.shown()
    editor.onSave(None)
    gui_env.settle(running_work)
    asked_on_save = [dialog for dialog in gui_env.shown() if "Broken2.profile" in dialog[2]]
    gui_env.answer_yes = False
    gui_env.click(running_work, "Reload Profiles")
    asked_on_reload = [dialog for dialog in gui_env.shown() if "Broken2.profile" in dialog[2]]
    assert asked_on_save == []
    assert len(asked_on_reload) == 1


def test_the_editor_opens_a_profile_whose_images_are_on_an_unavailable_drive(gui_env, running_work, editor):
    editor.populate_fields(gui_env.saved(running_work, "Nas"))
    assert not editor._loading
    assert editor.tc_name.GetValue() == "Nas"


def test_opening_such_a_profile_keeps_its_selection(gui_env, running_work, editor):
    editor.populate_fields(gui_env.saved(running_work, "Nas"))
    assert "selected=/nonexistent/nas/a.png" in gui_env.profile_file("Nas").read_text(encoding="utf-8")


def test_the_preview_applies_exif_orientation_like_the_renderer(gui_env, editor):
    bitmap = editor.wpprev_pnl.resize_and_bitmap(str(gui_env.images / "rotated.jpg"), (20, 40))
    left, right = colour_at(bitmap, 3, 20), colour_at(bitmap, 16, 20)
    assert left[2] > 150
    assert right[0] > 150


def test_apply_returns_while_its_draft_is_still_rendering(gui_env, running_work, editor, monkeypatch):
    session_module = gui_env.ui.session
    real_show = session_module.show
    release = threading.Event()
    finished = []

    def slow_show(*args, **kwargs):
        release.wait(30)
        result = real_show(*args, **kwargs)
        finished.append(True)
        return result

    editor.populate_fields(gui_env.saved(running_work, "Work"))
    monkeypatch.setattr(session_module, "show", slow_show)
    gui_env.shown()
    try:
        editor.onApply(None)
        returned_early = not finished
    finally:
        release.set()
    gui_env.settle(running_work)
    assert returned_early
    assert not gui_env.shown()


def test_a_draft_that_cant_be_shown_says_why_in_the_editor(gui_env, running_work, editor):
    bad = gui_env.root / "bad"
    bad.mkdir()
    (bad / "broken.png").write_bytes(b"not an image")
    gui_env.write_profile("Bad", f"name=Bad\nspanmode=single\nslideshow=false\ndisplay0paths={bad / 'broken.png'}\n")
    gui_env.click(running_work, "Reload Profiles")
    editor.update_choiceprofile()
    editor.populate_fields(gui_env.saved(running_work, "Bad"))
    gui_env.shown()
    editor.onApply(None)
    gui_env.settle(running_work)
    errors = gui_env.shown()
    assert len(errors) == 1
    assert errors[0][:2] == ("message", "Error")
    assert "broken.png" in errors[0][2]


@pytest.fixture
def home_panel(gui_env, running_work, editor):
    """The editor on a new profile based on Home, hotkey off."""
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    editor.loaded_profile = None
    editor.cb_hotkey.SetValue(False)
    editor.onCheckboxHotkey(None)
    return editor


def test_the_editors_name_field_takes_45_characters(home_panel):
    home_panel.tc_name.SetValue("Home-" + "n" * 40)
    assert len(home_panel.tc_name.GetValue()) == 45


def test_a_long_profile_name_saves(gui_env, running_work, home_panel):
    home_panel.tc_name.SetValue("Home-" + "n" * 40)
    gui_env.shown()
    home_panel.onSave(None)
    gui_env.settle(running_work)
    assert gui_env.profile_file("Home-" + "n" * 40).is_file()
    assert not gui_env.shown()


def choose_span_mode(editor, mode):
    editor.radiobox_spanmode.SetSelection(("single", "advanced", "multi").index(mode))
    editor.onSpanRadio(None)


def apply_offsets(editor, *fields):
    choose_span_mode(editor, "advanced")
    editor.cb_offsets.SetValue(True)
    editor.onCheckboxOffsets(None)
    for tc, text in zip(editor.tc_list_offsets, fields, strict=False):
        tc.SetValue(text)


def test_the_span_mode_follows_the_radio_box(editor):
    modes = []
    for mode in ("advanced", "multi", "single"):
        choose_span_mode(editor, mode)
        modes.append(editor.span_mode)
    assert modes == ["advanced", "multi", "single"]


def test_a_profile_that_corrects_positions_is_opened_as_advanced(gui_env, running_work, editor):
    gui_env.write_profile(
        "Old", f"name=Old\nspanmode=single\nslideshow=false\noffsets=1,2;3,4\ndisplay0paths={gui_env.images}\n"
    )
    gui_env.click(running_work, "Reload Profiles")
    editor.populate_fields(gui_env.saved(running_work, "Old"))
    assert editor.span_mode == "advanced"
    assert editor.radiobox_spanmode.GetSelection() == 1
    assert [tc.GetValue() for tc in editor.tc_list_offsets] == ["1,2", "3,4"]


def test_loading_a_profile_without_offsets_clears_the_offsets_of_the_previous_one(gui_env, running_work, editor):
    gui_env.write_profile(
        "Old", f"name=Old\nspanmode=single\nslideshow=false\noffsets=1,2;3,4\ndisplay0paths={gui_env.images}\n"
    )
    gui_env.click(running_work, "Reload Profiles")
    editor.populate_fields(gui_env.saved(running_work, "Old"))
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    assert not editor.cb_offsets.GetValue()
    assert [tc.GetValue() for tc in editor.tc_list_offsets] == ["0,0", "0,0"]


def test_span_groups_are_tuples_of_displays_and_the_preview_wants_two_groups(editor):
    assert spangroups_of(editor._spangroup_choices()) == ((0, 1),)
    assert editor.preview_spangroups() is None
    editor.ch_list_spangroups[1].SetSelection(1)
    assert spangroups_of(editor._spangroup_choices()) == ((0,), (1,))
    assert editor.preview_spangroups() == ((0,), (1,))


def test_an_unreadable_offset_names_its_display_and_nothing_is_saved(gui_env, editor):
    apply_offsets(editor, "1,2", "x")
    gui_env.shown()
    editor.onSave(None)
    (error,) = gui_env.shown()
    assert error[2] == "Manual offset of display 1: expected whole pixel numbers as x,y, not 'x'."
    assert "offsets=" not in gui_env.profile_file("Work").read_text(encoding="utf-8")


@pytest.mark.parametrize("action", ["onAlignTest", "show_preview_help", "onPerspectives"])
def test_every_use_of_the_offsets_refuses_an_unreadable_one_the_same_way(gui_env, editor, monkeypatch, action):
    def not_reached(*args, **kwargs):
        pytest.fail("went on with an unreadable offset")

    monkeypatch.setattr(gui_env.ui.editor, "show_help_popup", not_reached)
    monkeypatch.setattr(gui_env.ui.editor, "PerspectiveConfig", not_reached)
    monkeypatch.setattr(editor, "refresh_displays", not_reached)
    apply_offsets(editor, "1;2", "")
    gui_env.shown()
    if action == "show_preview_help":
        editor.show_preview_help("help", editor.wpprev_pnl.layout_editor.button_help)
    else:
        getattr(editor, action)(None)
    (error,) = gui_env.shown()
    assert error[:2] == ("editor", "Error")
    assert error[2] == "Manual offset of display 0: expected whole pixel numbers as x,y, not '1;2'."


def test_offsets_that_are_not_applied_are_not_read(editor):
    apply_offsets(editor, "x", "y")
    editor.cb_offsets.SetValue(False)
    editor.onCheckboxOffsets(None)
    assert editor._applied_offsets() == ((0, 0), (0, 0))


def test_the_align_test_uses_typed_offsets_even_when_not_applied(gui_env, editor, monkeypatch):
    drafts_seen = []
    monkeypatch.setattr(editor.session, "apply_draft", lambda profile, images, **kwargs: drafts_seen.append(profile))
    apply_offsets(editor, "5,6", "7,8")
    editor.cb_offsets.SetValue(False)
    editor.onCheckboxOffsets(None)
    editor.onAlignTest(None)
    assert drafts_seen[0].offsets == ((5, 6), (7, 8))
    gui_env.ui.wx.EndBusyCursor()
