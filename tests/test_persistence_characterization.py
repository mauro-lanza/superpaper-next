import os

import pytest

from superpaper.settings import read_settings, write_settings
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


def test_general_settings_round_trip_is_canonical(tmp_path):
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

    settings = read_settings(settings_path, "linux")
    write_settings(settings_path, settings)

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
    assert settings_path.read_bytes() == expected.encode()


def test_profile_read_does_not_modify_bytes(profile_modules, tmp_path):
    data, _ = profile_modules
    image = tmp_path / "wallpaper.png"
    image.touch()
    profile_path = tmp_path / "noise.profile"
    raw = f"name=noise\r\nspanmode=single\r\ndisplay0paths={image}"
    profile_path.write_bytes(raw.encode())

    data.ProfileData(profile_path)

    assert profile_path.read_bytes() == raw.encode()


def test_source_paths_may_contain_equals_signs(profile_modules, tmp_path):
    data, _ = profile_modules
    folder = tmp_path / "a=b"
    folder.mkdir()
    image = folder / "wallpaper.png"
    image.touch()

    profile = data.ProfileData(write_profile(tmp_path / "test.profile", sources=[folder]))

    assert profile.paths_array == [[str(folder)]]
    assert profile.next_wallpaper_files(peek=True) == [str(image)]


def test_identical_sources_are_written_with_their_own_display_numbers(profile_modules):
    data, _ = profile_modules
    profile = data.TempProfileData()
    profile.name = "twins"
    profile.paths_array = ["/images", "/images"]

    assert profile.serialize().splitlines()[-2:] == ["display0paths=/images", "display1paths=/images"]


# Profiles from before display layouts existed corrected positions with ppi=,
# diagonal_inches=, bezels= and offsets=. Parsing turns them into per-display pixel
# offsets for the displays present at the time; for two displays of 1920x1080 and
# 1280x1024 (profile_modules) these are the offsets that reach the renderer.
@pytest.mark.parametrize(
    ("lines", "ppimode", "ppi_array", "manual_offsets"),
    [
        ("", False, [100, 100], [(0, 0), (0, 0)]),
        ("offsets=10,20;30,-40", True, [100, 100], [(10, 20), (30, -40)]),
        ("offsets=10,20", True, [100, 100], [(10, 20), (0, 0)]),
        ("offsets=10,x;3", True, [100, 100], [(0, 0), (0, 0)]),
        ("bezels=5.0", False, [100, 100], [(0, 0), (0, 0)]),
        ("ppi=100;80", True, [100, 80], [(0, 0), (0, 0)]),
        ("ppi=100;80\nbezels=5.0", True, [100, 80], [(0, 0), (20, 0)]),
        ("ppi=100;80\nbezels=5.0\noffsets=10,20;30,-40", True, [100, 80], [(10, 20), (50, -40)]),
        ("ppi=100;80\nbezels=5.0;7.5;2.0", True, [100, 80], [(0, 0), (20, 0)]),
        ("diagonal_inches=24.0;19.0\nbezels=5.0", True, [91.7877987534291, 86.27367393593732], [(0, 0), (18, 0)]),
        ("diagonal_inches=24.0\nbezels=5.0", False, [100, 100], [(0, 0), (0, 0)]),
        ("ppi=0;0\nbezels=5.0", True, [0, 0], [(0, 0), (0, 0)]),
    ],
)
def test_legacy_corrections_become_pixel_offsets(profile_modules, tmp_path, lines, ppimode, ppi_array, manual_offsets):
    data, _ = profile_modules
    path = tmp_path / "legacy.profile"
    path.write_text(f"name=legacy\nspanmode=advanced\n{lines}\ndisplay0paths={tmp_path}\n", encoding="utf-8")

    profile = data.ProfileData(path, persist_selection=False)

    assert profile.ppimode is ppimode
    assert profile.ppi_array == ppi_array
    assert profile.manual_offsets == manual_offsets
