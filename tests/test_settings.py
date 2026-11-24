"""The general_settings file."""

import pytest

from superpaper import settings as settings_module
from superpaper.settings import (
    Settings,
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
        ("show_help_at_start=True", "show_help", True),
        ("warn_large_img=FALSE", "warn_large_img", False),
        ("logging=yes", "logging", False),
    ],
)
def test_a_flag_is_true_or_false_in_any_case_and_otherwise_keeps_its_default(tmp_path, line, field, expected):
    path = tmp_path / "general_settings"
    path.write_text(line + "\n", encoding="utf-8")

    settings = read_settings(path)

    assert settings is not None
    assert getattr(settings, field) is expected


def test_settings_a_file_leaves_out_keep_their_defaults(tmp_path):
    path = tmp_path / "general_settings"
    path.write_text("logging=true\n\nset_command=feh\n", encoding="utf-8")

    assert read_settings(path) == Settings(logging=True, set_command="feh")


def test_hotkey_lines_of_earlier_versions_are_ignored(tmp_path):
    path = tmp_path / "general_settings"
    path.write_text(
        "use hotkeys=true\nnext wallpaper hotkey=control+super+w\npause wallpaper hotkey=\nlogging=true\n",
        encoding="utf-8",
    )

    assert read_settings(path) == Settings(logging=True)


def test_the_default_settings_read_back_unchanged(tmp_path):
    path = tmp_path / "general_settings"

    write_settings(path, Settings())

    assert read_settings(path) == Settings()


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
        "show_help_at_start=false\n"
        "set_command=env FOO=bar setter --arg=a=b {image}\n"
        "browse_default_dir=/tmp/wallpapers\n"
        "warn_large_img=false"
    )
    assert settings_path.read_bytes() == expected.encode()
