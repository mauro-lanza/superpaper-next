import logging
from dataclasses import replace

import pytest
from PIL import Image

from superpaper.settings import read_settings


def test_the_browse_dialog_offers_one_source_per_display(gui_env, running_work, editor):
    browse = gui_env.open_browse(editor)
    assert browse.num_wallpaper_area == len(running_work.session.layout.displays)


def test_the_image_size_hint_names_the_desktop_size(gui_env, running_work, editor, monkeypatch):
    hints = []
    monkeypatch.setattr(
        gui_env.ui.editor, "show_help_popup", lambda parent, text, button, quality_text=None: hints.append(quality_text)
    )
    editor.show_preview_help("help", editor.wpprev_pnl.layout_editor.button_help)
    desktop = running_work.session.layout.desktop_size()
    assert f"{desktop[0]}x{desktop[1]}" in hints[0]


@pytest.fixture
def settings_panel(gui_env, superpaper):
    ui = gui_env.ui
    frame = ui.settings_dialog.SettingsFrame(lambda: superpaper.settings, save_settings=superpaper.apply_settings)
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
    gui_env.click(running_work, "Next Wallpaper")
    gui_env.settle(running_work)
    assert "set_command=true changed {image}" in gui_env.settings_path.read_text(encoding="utf-8")
    assert any(command[:2] == ["true", "changed"] for command in gui_env.commands)


@pytest.fixture
def help_and_browse_written(gui_env, running_work, editor):
    """The help window's and the browse dialog's one setting each saved, after the command changed."""
    ui = gui_env.ui
    running_work.apply_settings(replace(running_work.settings, set_command="true changed {image}"))
    for _ in range(2):
        help_frame = ui.help.HelpFrame(lambda: running_work.settings, running_work.update_settings)
        help_panel = gui_env.child_of(help_frame, ui.help.HelpPanel)
        help_panel.cb_show_at_start.SetValue(True)
        help_panel.onClose(None)
    browse = gui_env.open_browse(editor)
    browse.defdir = str(gui_env.images)
    browse._remember_default_dir(str(gui_env.images))
    return read_settings(gui_env.settings_path, hotkeys_by_default=True)


def test_the_apps_own_settings_follow_the_dialogs_writes(gui_env, running_work, help_and_browse_written):
    assert running_work.settings == help_and_browse_written
    assert running_work.settings.browse_default_dir == str(gui_env.images)


def test_help_and_browse_dialogs_save_their_setting_and_keep_the_rest(gui_env, help_and_browse_written):
    assert help_and_browse_written.show_help is True
    assert help_and_browse_written.browse_default_dir == str(gui_env.images)
    assert help_and_browse_written.set_command == "true changed {image}"


def test_opening_dialogs_adds_no_log_handlers(help_and_browse_written, capsys):
    logging.getLogger("superpaper.test").warning("probe")

    assert capsys.readouterr().err == ""


def test_source_icons_for_missing_corrupt_and_very_wide_images(gui_env):
    corrupt = gui_env.images / "corrupt.png"
    corrupt.write_bytes(b"not an image")
    wide = gui_env.images / "wide.png"
    Image.new("RGB", (4000, 10)).save(wide)
    source_icon = gui_env.ui.browse_dialog.source_icon
    sizes = [source_icon(str(path), (32, 32)).GetSize() for path in (gui_env.images / "gone.png", corrupt, wide)]
    assert sizes == [gui_env.ui.wx.Size(32, 32)] * 3


def test_the_browse_dialog_starts_at_the_current_saved_directory(gui_env, running_work, editor):
    wanted = str(gui_env.root / "newdefdir")
    running_work.update_settings(replace(running_work.settings, browse_default_dir=wanted))
    assert gui_env.open_browse(editor).defdir == wanted
