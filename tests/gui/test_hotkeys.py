import pytest

from superpaper.profiles.profile_id import ProfileId

HOME_KEYS = ("control", "super", "h")


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
    editor.onSave(None)
    gui_env.settle(running_work)
    return gui_env.shown(), deadline


def test_saving_a_profile_that_isnt_running_shows_no_error(home_saved_with_hotkey):
    assert not home_saved_with_hotkey[0]


def test_saving_another_profile_leaves_the_running_one_running(running_work, home_saved_with_hotkey):
    assert running_work.session.running.profile.name == "Work"


def test_saving_another_profile_leaves_the_slideshow_countdown_alone(running_work, home_saved_with_hotkey):
    deadline = home_saved_with_hotkey[1]
    assert deadline is not None
    assert running_work.session._deadline == deadline


def test_the_hotkey_binds_the_profiles_identity_not_an_object(running_work, home_saved_with_hotkey):
    assert running_work.hotkeys._profiles.bound == {HOME_KEYS: (ProfileId.parse("Home", windows_names=False),)}


def test_the_hotkey_starts_the_profile_with_its_latest_settings(gui_env, running_work, editor, home_saved_with_hotkey):
    editor.sld_zoom.SetValue(150)
    editor.onZoomOffsetChange(None)
    editor.onSave(None)
    running_work.hotkeys._profiles.press(HOME_KEYS)
    gui_env.flush()
    gui_env.settle(running_work)
    assert running_work.session.running.profile.name == "Home"
    assert running_work.session.running.profile.zoom == 1.5
