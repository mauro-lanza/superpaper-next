"""The .profile format as earlier versions wrote and read it, and general_settings."""

import pytest

from superpaper import profiles
from superpaper.profiles import Profile
from superpaper.settings import read_settings, write_settings
from tests.conftest import load_profile, write_profile


def test_minimal_profile_uses_legacy_defaults(tmp_path):
    image = tmp_path / "wallpaper.png"

    profile = profiles.parse(f"name=minimal\ndisplay0paths={image}\n")

    assert profile == Profile(name="minimal", sources=((str(image),),))
    assert (profile.spanmode, profile.slideshow, profile.delay, profile.sortmode) == ("single", True, 600.0, "shuffle")
    assert (profile.perspective, profile.zoom, profile.pan) == ("default", 1.0, (0.0, 0.0))


def test_a_profile_is_written_as_the_editor_always_wrote_it():
    profile = Profile(
        name="canonical",
        spanmode="advanced",
        spangroups=((0, 1), (2,)),
        slideshow=True,
        delay=60.0,
        sortmode="alphabetical",
        corrections=(("offsets", ((1, -2), (3, 4))),),
        hotkey=("control", "super", "w"),
        perspective="desk",
        zoom=1.25,
        pan=(-0.5, 1.0),
        selected=("/images/a.png",),
        sources=(("/images/a.png",), ("/images/b.png", "/more")),
    )

    # The selection is remembered beside the profile, not in it.
    assert profiles.serialize(profile) == (
        "name=canonical\n"
        "spanmode=advanced\n"
        "spangroups=01,2\n"
        "slideshow=True\n"
        "delay=60.0\n"
        "sortmode=alphabetical\n"
        "offsets=1,-2;3,4\n"
        "hotkey=control+super+w\n"
        "perspective=desk\n"
        "zoom=1.25\n"
        "align=-0.5,1.0\n"
        "display0paths=/images/a.png\n"
        "display1paths=/images/b.png;/more\n"
    )


def test_a_written_profile_reads_back_the_same(tmp_path):
    profile = Profile(
        name="round trip",
        spanmode="multi",
        slideshow=False,
        hotkey=("alt", "1"),
        perspective="disabled",
        zoom=1.5,
        pan=(0.25, -1.0),
        corrections=(("offsets", ((0, 0), (12, -3))),),
        sources=((str(tmp_path / "a=b"),), ("/one", "/two")),
    )

    assert profiles.parse(profiles.serialize(profile)) == profile


def test_a_slideshow_profile_reads_back_the_same():
    profile = Profile(name="slides", delay=1230.0, sortmode="date_seeded_shuffle", sources=(("/images",),))

    assert profiles.parse(profiles.serialize(profile)) == profile


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


def test_loading_a_profile_leaves_its_file_alone(app_paths, tmp_path):
    image = tmp_path / "wallpaper.png"
    image.touch()
    profile_path = app_paths.profiles / "noise.profile"
    raw = f"name=noise\r\nspanmode=single\r\ndisplay0paths={image}"
    profile_path.write_bytes(raw.encode())

    stored = load_profile(app_paths, "noise")
    stored.selection.advance()

    assert stored.profile.sources == ((str(image),),)
    assert profile_path.read_bytes() == raw.encode()


def test_source_paths_may_contain_equals_signs(app_paths, tmp_path):
    folder = tmp_path / "a=b"
    folder.mkdir()
    image = folder / "wallpaper.png"
    image.touch()

    write_profile(app_paths.profiles / "test.profile", sources=[folder])
    stored = load_profile(app_paths, "test")

    assert stored.profile.sources == ((str(folder),),)
    assert stored.selection.current() == [str(image)]


def test_identical_sources_are_written_with_their_own_display_numbers():
    profile = Profile(name="twins", sources=(("/images",), ("/images",)))

    assert profiles.serialize(profile).splitlines()[-2:] == ["display0paths=/images", "display1paths=/images"]


@pytest.mark.parametrize(
    ("line", "value"),
    [
        # Earlier versions loaded these with the defaults, so they still load.
        ("zoom=", ("zoom", 1.0)),
        ("zoom=big", ("zoom", 1.0)),
        ("zoom=0.5", ("zoom", 1.0)),
        ("align=", ("pan", (0.0, 0.0))),
        ("align=0.5", ("pan", (0.0, 0.0))),
        ("align=0.5,-2,9", ("pan", (0.5, -1.0))),
        ("spanmode=diagonal", ("spanmode", "single")),
        ("sortmode=random", ("sortmode", "shuffle")),
        ("spangroups=0,x", ("spangroups", None)),
        ("hotkey=", ("hotkey", None)),
        ("a line without a setting", ("name", "lenient")),
        ("unknown=setting", ("name", "lenient")),
    ],
)
def test_values_earlier_versions_tolerated_still_load(line, value):
    key, expected = value

    assert getattr(profiles.parse(f"name=lenient\n{line}\n"), key) == expected


@pytest.mark.parametrize(
    "line", ["delay=", "delay=soon", "bezels=thin", "ppi=96.5", "diagonal_inches=24;big", "diagonal_inches=0;24"]
)
def test_values_that_cant_be_used_make_a_profile_unusable(line):
    with pytest.raises(profiles.ProfileFormatError):
        profiles.parse(f"name=broken\n{line}\n")


# Profiles from before display layouts existed corrected positions with ppi=,
# diagonal_inches=, bezels= and offsets=. Earlier versions turned them into per-display
# pixel offsets while parsing, for the displays present then; display_corrections does it
# for the layout being rendered. For displays of 1920x1080 and 1280x1024 these are the
# offsets that reach the renderer.
TWO_RESOLUTIONS = [(1920, 1080), (1280, 1024)]


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
def test_legacy_corrections_become_pixel_offsets(lines, ppimode, ppi_array, manual_offsets):
    profile = profiles.parse(f"name=legacy\nspanmode=advanced\n{lines}\ndisplay0paths=/images\n")

    corrections = profile.display_corrections(TWO_RESOLUTIONS)

    assert corrections.ppimode is ppimode
    assert corrections.ppi_array == ppi_array
    assert corrections.manual_offsets == manual_offsets


def test_corrections_follow_the_displays_present():
    profile = profiles.parse("name=legacy\nppi=100;80\nbezels=5.0\ndisplay0paths=/images\n")

    # A third display plugged in later is shifted by the bezels to its left too.
    three = profile.display_corrections([*TWO_RESOLUTIONS, (1920, 1080)])

    assert three.manual_offsets == [(0, 0), (20, 0), (20, 0)]
    assert profile.display_corrections(TWO_RESOLUTIONS).manual_offsets == [(0, 0), (20, 0)]


@pytest.mark.parametrize(
    ("displays", "manual_offsets"),
    [(1, [(1, 2)]), (2, [(1, 2), (3, -4)]), (3, [(1, 2), (3, -4), (0, 0)])],
)
def test_command_line_offsets_apply_to_the_displays_present(displays, manual_offsets):
    advanced = profiles.draft(["/image.png"], spanmode="advanced", offsets=[(1, 2), (3, -4)])

    corrections = advanced.display_corrections(displays * [(1920, 1080)])

    # The renderer takes one offset per display present.
    assert corrections.manual_offsets[:displays] == manual_offsets


def test_command_line_offsets_only_apply_to_advanced_spanning():
    simple = profiles.draft(["/image.png"], spanmode="single", offsets=[(1, 2)])

    assert simple.display_corrections([(1920, 1080)]).ppimode is False
    assert simple.corrections == ()
