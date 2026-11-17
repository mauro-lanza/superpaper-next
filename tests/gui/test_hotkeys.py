import pytest

from superpaper.profile_id import ProfileId

HOME_KEYS = ("control", "super", "h")
TEMP_KEYS = ("control", "super", "t")


def bind_hotkey(editor, keys):
    editor.cb_hotkey.SetValue(True)
    editor.onCheckboxHotkey(None)
    editor.tc_hotkey_bind.SetValue("+".join(keys))


@pytest.fixture
def home_saved_with_hotkey(gui_env, running_work, editor):
    """Work running, hotkeys on, and Home (not running) saved in the editor with a hotkey."""
    gui_env.enable_hotkeys(running_work)
    deadline = running_work.session._deadline
    editor.populate_fields(gui_env.saved(running_work, "Home"))
    bind_hotkey(editor, HOME_KEYS)
    gui_env.shown()
    saved = editor.onSave(None)
    gui_env.settle(running_work)
    return saved, gui_env.shown(), deadline


def test_saving_a_profile_that_isnt_running_shows_no_error(home_saved_with_hotkey):
    saved, errors, _ = home_saved_with_hotkey
    assert saved is not None
    assert not errors


def test_saving_another_profile_leaves_the_running_one_running(running_work, home_saved_with_hotkey):
    assert running_work.session.running.profile.name == "Work"


def test_saving_another_profile_leaves_the_slideshow_countdown_alone(running_work, home_saved_with_hotkey):
    deadline = home_saved_with_hotkey[2]
    assert deadline is not None
    assert running_work.session._deadline == deadline


def test_the_hotkey_binds_the_profiles_identity_not_an_object(running_work, home_saved_with_hotkey):
    assert running_work.hotkeys._profiles.bound == {HOME_KEYS: (ProfileId("Home"),)}


def test_the_hotkey_starts_the_profile_with_its_latest_settings(gui_env, running_work, editor, home_saved_with_hotkey):
    editor.sld_zoom.SetValue(150)
    editor.onZoomOffsetChange(None)
    editor.onSave(None)
    running_work.hotkeys._profiles.press(HOME_KEYS)
    gui_env.flush()
    gui_env.settle(running_work)
    assert running_work.session.running.profile.name == "Home"
    assert running_work.session.running.profile.zoom == 1.5


def test_deleting_a_profile_frees_its_hotkey(gui_env, running_work, editor):
    gui_env.write_profile(
        "Temp",
        f"name=Temp\nspanmode=single\nslideshow=true\ndelay=600\nsortmode=alphabetical\ndisplay0paths={gui_env.images}\n",
    )
    running_work.tray.reload_profiles(None)
    gui_env.start_profile(running_work, "Temp")
    gui_env.enable_hotkeys(running_work)
    editor.update_choiceprofile()
    editor.choice_profiles.SetSelection(editor.choice_profiles.FindString("Temp"))
    editor.populate_fields(gui_env.saved(running_work, "Temp"))
    bind_hotkey(editor, TEMP_KEYS)
    editor.onSave(None)
    gui_env.settle(running_work)
    hotkeys = running_work.hotkeys
    assert hotkeys._owners.get(TEMP_KEYS) == ProfileId("Temp")

    gui_env.yes_to_message_dialogs()
    editor.onDeleteProfile(None)
    gui_env.settle(running_work)
    assert TEMP_KEYS not in hotkeys._owners
    assert TEMP_KEYS not in hotkeys._profiles.bound
