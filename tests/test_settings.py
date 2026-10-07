"""The general_settings file."""

from dataclasses import replace

import pytest

from superpaper import settings as settings_module
from superpaper.settings import Settings, first_run_settings, read_settings, write_settings


def test_a_missing_file_reads_as_the_first_run_settings_without_creating_it(tmp_path):
    path = tmp_path / "general_settings"

    assert read_settings(path, "linux") == first_run_settings("linux")
    assert not path.exists()


@pytest.mark.parametrize(("platform", "use_hotkeys"), [("linux", True), ("win32", True), ("darwin", False)])
def test_first_run_settings(platform, use_hotkeys):
    settings = first_run_settings(platform)

    assert settings.use_hotkeys is use_hotkeys
    assert settings.hk_binding_next == ("control", "super", "w")
    assert settings.hk_binding_pause == ("control", "super", "shift", "p")
    assert settings.show_help is True
    assert settings.logging is False


def test_settings_a_file_leaves_out_keep_their_defaults(tmp_path):
    path = tmp_path / "general_settings"
    path.write_text("logging=true\n\nset_command=feh\n", encoding="utf-8")

    assert read_settings(path, "darwin") == Settings(logging=True, set_command="feh")


def test_settings_command_preserves_equals(tmp_path):
    settings_file = tmp_path / "general_settings"
    settings_file.write_text("set_command=env FOO=bar setter {image}\n", encoding="utf-8")

    assert read_settings(settings_file, "linux").set_command == "env FOO=bar setter {image}"


def test_settings_without_a_command_have_none(tmp_path):
    settings_file = tmp_path / "general_settings"
    settings_file.write_text("logging=false\n", encoding="utf-8")

    assert read_settings(settings_file, "linux").set_command == ""


def test_an_empty_hotkey_means_no_hotkey(tmp_path):
    path = tmp_path / "general_settings"
    path.write_text("next wallpaper hotkey=\npause wallpaper hotkey= \n", encoding="utf-8")

    settings = read_settings(path, "linux")

    assert settings.hk_binding_next is None
    assert settings.hk_binding_pause is None


def test_the_first_run_file_reads_back_unchanged(tmp_path):
    path = tmp_path / "general_settings"

    write_settings(path, first_run_settings("linux"))

    assert read_settings(path, "linux") == first_run_settings("linux")


def test_a_symlinked_settings_file_stays_a_link(tmp_path):
    target = tmp_path / "dotfiles" / "general_settings"
    target.parent.mkdir()
    target.write_text("logging=false\n", encoding="utf-8")
    link = tmp_path / "general_settings"
    link.symlink_to(target)

    write_settings(link, replace(read_settings(link, "linux"), browse_default_dir="/pictures"))

    assert link.is_symlink()
    assert read_settings(target, "linux").browse_default_dir == "/pictures"


def test_the_file_uses_the_encoding_older_versions_wrote(tmp_path, monkeypatch):
    # Python's default text encoding, which older versions used, is a code page on Windows.
    monkeypatch.setattr(settings_module.locale, "getpreferredencoding", lambda do_setlocale=True: "cp1252")
    path = tmp_path / "general_settings"
    path.write_bytes("browse_default_dir=C:\\Users\\J\xf6rg\\Pictures\n".encode("cp1252"))

    settings = read_settings(path, "win32")
    write_settings(path, settings)

    assert settings.browse_default_dir == "C:\\Users\\J\xf6rg\\Pictures"
    assert "browse_default_dir=C:\\Users\\J\xf6rg\\Pictures\n".encode("cp1252") in path.read_bytes()
