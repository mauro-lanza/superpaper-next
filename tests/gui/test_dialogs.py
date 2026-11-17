import sys

import pytest
from PIL import Image

import superpaper.render as render
import superpaper.sp_logging as sp_logging
from superpaper.settings import read_settings


def test_the_browse_dialog_offers_one_source_per_display(gui_env, running_work, editor):
    browse = gui_env.ui.browse_dialog.BrowsePaths(editor, True, "", running_work.update_settings)
    displays = len(running_work.session.display_system.disp_list)
    count = browse.num_wallpaper_area
    browse.Destroy()
    assert count == displays


def test_the_image_size_hint_names_the_desktop_size(gui_env, running_work, editor):
    popup = gui_env.ui.help.ImageQualityHelpPopup(
        editor.wpprev_pnl, "help", editor=editor, use_perspective=False, persp_name="default"
    )
    display_system = running_work.session.display_system
    desktop = render.compute_canvas(display_system.resolutions(), display_system.digital_offsets())
    hint = popup.string_ideal_image_size()
    popup.Destroy()
    assert f"{desktop[0]}x{desktop[1]}" in hint


@pytest.fixture
def settings_panel(gui_env, superpaper):
    ui = gui_env.ui
    frame = ui.settings_dialog.SettingsFrame(superpaper.settings, save_settings=superpaper.apply_settings)
    yield gui_env.child_of(frame, ui.settings_dialog.SettingsPanel)
    frame.Destroy()


def test_the_settings_dialog_shows_the_saved_command(settings_panel):
    assert settings_panel.tc_setcmd.GetValue() == "true {image}"


def test_the_command_saved_in_the_settings_dialog_is_in_the_file_and_the_next_change_uses_it(
    gui_env, running_work, settings_panel
):
    settings_panel.tc_setcmd.SetValue("true changed {image}")
    settings_panel.onSave(None)
    gui_env.commands.clear()
    running_work.tray.next_wallpaper(None)
    gui_env.settle(running_work)
    assert "set_command=true changed {image}" in gui_env.settings_path.read_text(encoding="utf-8")
    assert any(command[:2] == ["true", "changed"] for command in gui_env.commands)


@pytest.fixture
def help_and_browse_written(gui_env, running_work, editor):
    """The help window's and the browse dialog's one setting each saved, after the command changed."""
    ui = gui_env.ui
    running_work.apply_settings(set_command="true changed {image}")
    for _ in range(2):
        help_frame = ui.help.HelpFrame(lambda: running_work.settings, running_work.update_settings)
        help_panel = gui_env.child_of(help_frame, ui.help.HelpPanel)
        help_panel.cb_show_at_start.SetValue(True)
        help_panel.onClose(None)
    browse = ui.browse_dialog.BrowsePaths(editor, False, "", running_work.update_settings)
    browse.defdir = str(gui_env.images)
    browse._update_settings(browse_default_dir=str(gui_env.images))
    browse.Destroy()
    return read_settings(gui_env.settings_path, sys.platform)


def test_the_apps_own_settings_follow_the_dialogs_writes(gui_env, running_work, help_and_browse_written):
    assert running_work.settings == help_and_browse_written
    assert running_work.settings.browse_default_dir == str(gui_env.images)


def test_help_and_browse_dialogs_save_their_setting_and_keep_the_rest(gui_env, help_and_browse_written):
    assert help_and_browse_written.show_help is True
    assert help_and_browse_written.browse_default_dir == str(gui_env.images)
    assert help_and_browse_written.set_command == "true changed {image}"


def test_opening_dialogs_adds_no_log_handlers(help_and_browse_written):
    assert sp_logging.G_LOGGER.handlers == []


def test_source_icons_for_missing_corrupt_and_very_wide_images(gui_env):
    corrupt = gui_env.images / "corrupt.png"
    corrupt.write_bytes(b"not an image")
    wide = gui_env.images / "wide.png"
    Image.new("RGB", (4000, 10)).save(wide)
    source_icon = gui_env.ui.browse_dialog.source_icon
    sizes = [source_icon(str(path), (32, 32)).GetSize() for path in (gui_env.images / "gone.png", corrupt, wide)]
    assert sizes == [gui_env.ui.wx.Size(32, 32)] * 3


def test_the_browse_dialog_starts_at_the_current_saved_directory(gui_env, running_work, editor, monkeypatch):
    wanted = str(gui_env.root / "newdefdir")
    running_work.update_settings(browse_default_dir=wanted)
    seen = []

    class FakeBrowse:
        def __init__(self, parent, multi, defdir, *args, **kwargs):
            seen.append(defdir)

        def ShowModal(self):
            return gui_env.ui.wx.ID_CANCEL

    monkeypatch.setattr(gui_env.ui.editor, "BrowsePaths", FakeBrowse)
    editor.onBrowsePaths(None)
    assert seen == [wanted]
