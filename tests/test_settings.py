"""The general_settings file."""

import pytest

from superpaper import settings as settings_module
from superpaper.settings import (
    Settings,
    first_run_settings,
    read_settings,
    write_settings,
)


def test_a_missing_file_reads_as_none_and_is_not_created(tmp_path):
    path = tmp_path / "general_settings"

    assert read_settings(path) is None
    assert not path.exists()


@pytest.mark.parametrize(
    ("line", "field", "expected"),
    [
        ("use hotkeys=FALSE", "use_hotkeys", False),
        ("show_help_at_start=True", "show_help", True),
        ("use hotkeys=yes", "use_hotkeys", True),
        ("logging=yes", "logging", False),
    ],
)
def test_a_flag_is_true_or_false_in_any_case_and_otherwise_keeps_its_default(tmp_path, line, field, expected):
    path = tmp_path / "general_settings"
    path.write_text(line + "\n", encoding="utf-8")

    settings = read_settings(path)

    assert settings is not None
    assert getattr(settings, field) is expected


@pytest.mark.parametrize("hotkeys_by_default", [True, False])
def test_first_run_settings(hotkeys_by_default):
    settings = first_run_settings(hotkeys_by_default=hotkeys_by_default)

    assert settings.use_hotkeys is hotkeys_by_default
    assert settings.hk_binding_next == ("control", "super", "w")
    assert settings.hk_binding_pause == ("control", "shift", "super", "p")
    assert settings.show_help is True
    assert settings.logging is False


def test_settings_a_file_leaves_out_keep_their_defaults(tmp_path):
    path = tmp_path / "general_settings"
    path.write_text("logging=true\n\nset_command=feh\n", encoding="utf-8")

    assert read_settings(path) == Settings(logging=True, set_command="feh")


def test_an_empty_hotkey_means_no_hotkey(tmp_path):
    path = tmp_path / "general_settings"
    path.write_text("next wallpaper hotkey=\npause wallpaper hotkey= \n", encoding="utf-8")

    settings = read_settings(path)

    assert settings is not None
    assert settings.hk_binding_next is None
    assert settings.hk_binding_pause is None


def test_the_first_run_file_reads_back_unchanged(tmp_path):
    path = tmp_path / "general_settings"

    write_settings(path, first_run_settings(hotkeys_by_default=True))

    assert read_settings(path) == first_run_settings(hotkeys_by_default=True)


def test_the_file_uses_the_encoding_older_versions_wrote(tmp_path, monkeypatch):
    # Python's default text encoding, which older versions used, is a code page on Windows.
    monkeypatch.setattr(settings_module.locale, "getpreferredencoding", lambda do_setlocale=True: "cp1252")
    path = tmp_path / "general_settings"
    path.write_bytes("browse_default_dir=C:\\Users\\J\xf6rg\\Pictures\n".encode("cp1252"))

    settings = read_settings(path)
    assert settings is not None
    write_settings(path, settings)

    assert settings.browse_default_dir == "C:\\Users\\J\xf6rg\\Pictures"
    assert "browse_default_dir=C:\\Users\\J\xf6rg\\Pictures\n".encode("cp1252") in path.read_bytes()


def test_general_settings_round_trip_is_byte_stable(tmp_path):
    settings_path = tmp_path / "general_settings"
    settings_path.write_text(
        "logging=FALSE\n"
        "use hotkeys=TrUe\n"
        "next wallpaper hotkey=control+super+w\n"
        "pause wallpaper hotkey=control+shift+super+p\n"
        "show_help_at_start=false\n"
        "set_command=env FOO=bar setter --arg=a=b {image}\n"
        "browse_default_dir=/tmp/wallpapers\n"
        "warn_large_img=false\n"
        "unknown_setting=retired\n",
        encoding="utf-8",
    )

    settings = read_settings(settings_path)
    assert settings is not None
    write_settings(settings_path, settings)

    assert settings.set_command == "env FOO=bar setter --arg=a=b {image}"
    expected = (
        "logging=false\n"
        "use hotkeys=true\n"
        "next wallpaper hotkey=control+super+w\n"
        "pause wallpaper hotkey=control+shift+super+p\n"
        "show_help_at_start=false\n"
        "set_command=env FOO=bar setter --arg=a=b {image}\n"
        "browse_default_dir=/tmp/wallpapers\n"
        "warn_large_img=false"
    )
    assert settings_path.read_bytes() == expected.encode()
