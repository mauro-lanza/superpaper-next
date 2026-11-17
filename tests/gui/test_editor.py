import threading

import pytest

import superpaper.profile_store as profile_store
from superpaper.profile_id import ProfileId


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
    displays = len(running_work.session.display_system.disp_list)
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
    editor.onApply(None)
    gui_env.settle(running_work)
    cache = gui_env.paths.cache
    stored = profile_store._read_stored_selection(profile_store._selection_path(cache, ProfileId("Work")))
    editor.tc_sshow_delay.SetValue("15")
    saved = editor.onSave(None)
    gui_env.settle(running_work)
    work_text = gui_env.profile_file("Work").read_text(encoding="utf-8")
    return stored, saved, gui_env.shown(), work_text


def test_apply_then_save_shows_no_error(applied_then_saved):
    _, saved, errors, _ = applied_then_saved
    assert saved is not None
    assert not errors


def test_apply_keeps_the_selection_out_of_the_profile_file(applied_then_saved):
    stored, _, _, work_text = applied_then_saved
    assert stored
    assert "selected=" not in work_text


def test_apply_then_save_writes_the_edit_to_disk(applied_then_saved):
    assert "delay=900.0" in applied_then_saved[3]


def test_after_save_the_editor_and_the_slideshow_hold_the_stores_one_record(
    gui_env, running_work, editor, applied_then_saved
):
    assert editor.loaded_profile is gui_env.saved(running_work, "Work") is running_work.session.running
    assert running_work.session.running.profile.delay == 900.0


def test_a_slideshow_tick_while_the_editor_is_open_doesnt_break_save(gui_env, running_work, editor):
    running_work.tray.next_wallpaper(None)
    gui_env.settle(running_work)
    gui_env.shown()
    editor.tc_sshow_delay.SetValue("20")
    saved = editor.onSave(None)
    gui_env.settle(running_work)
    assert saved is not None
    assert not gui_env.shown()


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
    refused = editor.onSave(None)
    errors = gui_env.shown()
    assert refused is None
    assert len(errors) == 1
    assert "Revert" in errors[0][2]
    assert "zoom=1.75" in home_edited_outside.read_text(encoding="utf-8")


def test_revert_loads_the_change_made_outside_the_editor(gui_env, running_work, home_edited_outside, editor):
    editor.onRevert(None)
    assert editor.loaded_profile is gui_env.saved(running_work, "Home")
    assert editor.loaded_profile.profile.zoom == 1.75
    assert editor.sld_zoom.GetValue() == 175


def test_after_revert_the_profile_saves(gui_env, home_edited_outside, editor):
    editor.onRevert(None)
    saved = editor.onSave(None)
    assert saved is not None
    assert not gui_env.shown()
    assert "zoom=1.75" in home_edited_outside.read_text(encoding="utf-8")


def test_deleting_the_running_profile_stops_its_slideshow_and_forgets_its_selection(gui_env, running_work, editor):
    gui_env.write_profile(
        "Temp",
        f"name=Temp\nspanmode=single\nslideshow=true\ndelay=600\nsortmode=alphabetical\ndisplay0paths={gui_env.images}\n",
    )
    running_work.tray.reload_profiles(None)
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
    assert not gui_env.shown()


def test_save_doesnt_ask_about_a_broken_profile_but_reload_profiles_does(gui_env, running_work, editor):
    gui_env.write_profile("Broken2", "name=Broken2\ndelay=soon\n")
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    editor.choice_profiles.SetSelection(editor.choice_profiles.FindString("Home"))
    gui_env.shown()
    saved = editor.onSave(None)
    gui_env.settle(running_work)
    asked_on_save = [dialog for dialog in gui_env.shown() if "Broken2.profile" in dialog[2]]
    gui_env.answer_yes = False
    running_work.tray.reload_profiles(None)
    asked_on_reload = [dialog for dialog in gui_env.shown() if "Broken2.profile" in dialog[2]]
    assert saved is not None
    assert asked_on_save == []
    assert len(asked_on_reload) == 1


def test_pause_survives_saving_the_running_profile(gui_env, running_work, editor):
    running_work.tray.pause_timer(None)
    gui_env.settle(running_work)
    editor.populate_fields(running_work.session.running)
    editor.tc_sshow_delay.SetValue("25")
    gui_env.shown()
    saved = editor.onSave(None)
    gui_env.settle(running_work)
    assert saved is not None
    assert running_work.tray.is_paused
    assert not slideshow_armed(running_work)
    assert not gui_env.shown()


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
    running_work.tray.reload_profiles(None)
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
    saved = home_panel.onSave(None)
    gui_env.settle(running_work)
    assert saved is not None
    assert not gui_env.shown()


def test_a_201_unit_name_is_refused_with_a_readable_message(gui_env, home_panel):
    home_panel.tc_name.SetValue("m" * 201)
    gui_env.shown()
    refused = home_panel.onSave(None)
    messages = gui_env.shown()
    assert refused is None
    assert messages
    assert "200" in " ".join(message[2] for message in messages)
