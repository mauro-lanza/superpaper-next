import os

from tests.conftest import write_profile


def platform_bytes(text):
    return text.replace("\n", os.linesep).encode("utf-8")


def test_minimal_profile_uses_legacy_defaults(profile_modules, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "wallpaper.png"
    image.touch()
    profile_path = tmp_path / "minimal.profile"
    profile_path.write_text(f"name=minimal\ndisplay0paths={image}\n", encoding="utf-8")

    profile = data.ProfileData(profile_path)

    assert profile.name == "minimal"
    assert profile.spanmode == "single"
    assert profile.slideshow is True
    assert profile.delay_list == [600]
    assert profile.sortmode == "shuffle"
    assert profile.perspective == "default"
    assert profile.zoom == 1.0
    assert profile.offsets == (0.0, 0.0)
    assert profile.paths_array == [[str(image)]]


def test_temp_profile_save_bytes_are_canonical(profile_modules, tmp_path):
    data, _ = profile_modules
    profile = data.TempProfileData()
    profile.name = "canonical"
    profile.spanmode = "advanced"
    profile.spangroups = "01,2"
    profile.slideshow = True
    profile.delay = "60"
    profile.sortmode = "alphabetical"
    profile.manual_offsets = "1,-2;3,4"
    profile.hk_binding = "control+super+w"
    profile.perspective = "desk"
    profile.zoom = 1.25
    profile.align = (-0.5, 1.0)
    profile.selected = ["/images/a.png", "/images/b.png"]
    profile.paths_array = ["/images/a.png", "/images/b.png"]

    expected = (
        "name=canonical\n"
        "spanmode=advanced\n"
        "spangroups=01,2\n"
        "slideshow=True\n"
        "delay=60\n"
        "sortmode=alphabetical\n"
        "offsets=1,-2;3,4\n"
        "hotkey=control+super+w\n"
        "perspective=desk\n"
        "zoom=1.25\n"
        "align=-0.5,1.0\n"
        "selected=/images/a.png;/images/b.png\n"
        "display0paths=/images/a.png\n"
        "display1paths=/images/b.png\n"
    )
    output = tmp_path / "canonical.profile"

    assert profile.save(filename=output) == output
    assert output.read_bytes() == platform_bytes(expected)


def test_selection_rewrite_preserves_other_profile_lines(profile_modules, tmp_path):
    data, _ = profile_modules
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.touch()
    second.touch()
    profile_path = write_profile(tmp_path / "test.profile", sources=[first], selected=[first])
    original = profile_path.read_text(encoding="utf-8").replace(
        "sortmode=alphabetical\n", "unknown legacy=value\nsortmode=alphabetical\n"
    )
    profile_path.write_text(original, encoding="utf-8")
    profile = data.ProfileData(profile_path)

    profile.set_selected_wallpaper([str(second)])

    assert profile_path.read_text(encoding="utf-8") == (
        "name=test\n"
        "spanmode=single\n"
        "slideshow=false\n"
        "unknown legacy=value\n"
        "sortmode=alphabetical\n"
        f"display0paths={first}\n"
        f"selected={second}\n"
    )


def test_general_settings_round_trip_is_canonical(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    settings_path = tmp_path / "general_settings"
    settings_path.write_text(
        "logging=FALSE\n"
        "use hotkeys=TrUe\n"
        "next wallpaper hotkey=control+super+w\n"
        "pause wallpaper hotkey=control+super+shift+p\n"
        "show_help_at_start=false\n"
        "set_command=env FOO=bar setter --arg=a=b {image}\n"
        "browse_default_dir=/tmp/wallpapers\n"
        "warn_large_img=false\n"
        "unknown_setting=retired\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(data, "CONFIG_PATH", str(tmp_path))

    settings = data.GeneralSettingsData()
    settings.save_settings()

    assert settings.set_command == "env FOO=bar setter --arg=a=b {image}"
    expected = (
        "logging=false\n"
        "use hotkeys=true\n"
        "next wallpaper hotkey=control+super+w\n"
        "pause wallpaper hotkey=control+super+shift+p\n"
        "show_help_at_start=false\n"
        "set_command=env FOO=bar setter --arg=a=b {image}\n"
        "browse_default_dir=/tmp/wallpapers\n"
        "warn_large_img=false"
    )
    assert settings_path.read_bytes() == platform_bytes(expected)


def test_profile_read_does_not_modify_bytes(profile_modules, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "wallpaper.png"
    image.touch()
    profile_path = tmp_path / "noise.profile"
    raw = f"name=noise\r\nspanmode=single\r\ndisplay0paths={image}"
    profile_path.write_bytes(raw.encode())

    data.ProfileData(profile_path)

    assert profile_path.read_bytes() == raw.encode()
