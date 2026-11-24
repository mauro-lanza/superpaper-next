"""The .profile format as earlier versions wrote and read it, and what keeps a profile from being
saved or shown: profile_file.validate, which the editor shows the user instead of saving or
applying."""

import pytest

from superpaper.geometry.perspective import Default, Disabled, Named, parse_choice
from superpaper.profiles import profile_file
from superpaper.profiles.profile_file import OffsetsCorrection, Profile


@pytest.fixture
def images(tmp_path):
    folder = tmp_path / "images"
    folder.mkdir()
    (folder / "a.png").touch()
    return str(folder)


def test_a_complete_profile_has_no_problems(images):
    assert profile_file.validate(Profile(name="work", delay=600.0, sources=((images,),))) == []


def test_a_draft_may_use_a_name_saved_profiles_may_not(images):
    # Only saving checks the name against the profiles directory.
    assert profile_file.validate(Profile(name="cli", slideshow=False, sources=((images,),))) == []


def test_upper_case_image_extensions_are_images(tmp_path):
    camera = tmp_path / "camera"
    camera.mkdir()
    (camera / "IMG_0001.JPG").touch()

    assert profile_file.validate(Profile(name="camera", slideshow=False, sources=((str(camera),),))) == []


@pytest.mark.parametrize(
    ("settings", "problem"),
    [
        ({"name": "  "}, "You must enter a name for the profile."),
        ({"spanmode": "single", "sources": (("a",), ("b",))}, "only one paths field is needed"),
        ({"slideshow": True, "delay": 4.0}, "at least 5 seconds"),
        ({"slideshow": True, "delay": 0.5}, "at least 5 seconds"),
        ({"sources": ()}, "You must enter at least one path for images."),
        ({"sources": ((),)}, "At least one path for wallpapers must be given."),
        ({"spanmode": "multi", "sources": (("a",), ())}, "Add an image source for every display present."),
        ({"spanmode": "advanced", "spangroups": ((0,), (1,))}, "Add an image source for every span group."),
    ],
)
def test_settings_that_cant_be_used_are_explained(images, settings, problem):
    profile = Profile(**{"name": "work", "slideshow": False, "sources": ((images,),), **settings})

    assert any(problem in reported for reported in profile_file.validate(profile))


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("gone", "Path '{}' was not recognized as a directory."),
        ("empty", "Path '{}' does not contain supported image files."),
        ("notes.txt", "Image '{}' is not a supported image file."),
    ],
)
def test_sources_without_images_are_explained(tmp_path, source, message):
    (tmp_path / "empty").mkdir()
    (tmp_path / "notes.txt").touch()
    path = str(tmp_path / source)

    assert profile_file.validate(Profile(name="work", slideshow=False, sources=((path,),))) == [message.format(path)]


def test_every_problem_is_reported_at_once():
    profile = Profile(name="", spanmode="multi", slideshow=True, delay=4.0, sources=((),))

    assert len(profile_file.validate(profile)) == 3


def test_one_image_per_display_is_valid_with_a_single_display(images):
    profile = Profile(name="work", spanmode="multi", slideshow=False, sources=((images,),))

    assert profile_file.validate(profile) == []


def test_minimal_profile_uses_legacy_defaults(tmp_path):
    image = tmp_path / "wallpaper.png"

    profile = profile_file.parse(f"name=minimal\ndisplay0paths={image}\n")

    assert profile == Profile(name="minimal", sources=((str(image),),))
    assert (profile.spanmode, profile.slideshow, profile.delay, profile.sortmode) == ("single", True, 600.0, "shuffle")
    assert (profile.perspective, profile.zoom, profile.pan) == (Default(), 1.0, (0.0, 0.0))


def test_a_profile_is_serialized_byte_stable():
    profile = Profile(
        name="canonical",
        spanmode="advanced",
        spangroups=((0, 1), (2,)),
        slideshow=True,
        delay=60.0,
        sortmode="alphabetical",
        corrections=(OffsetsCorrection(((1, -2), (3, 4))),),
        hotkey=("control", "super", "w"),
        perspective=Named("desk"),
        zoom=1.25,
        pan=(-0.5, 1.0),
        selected=("/images/a.png",),
        sources=(("/images/a.png",), ("/images/b.png", "/more")),
    )

    # The selection is remembered beside the profile, not in it.
    assert profile_file.serialize(profile) == (
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


@pytest.mark.parametrize(
    "profile",
    [
        Profile(
            name="round trip",
            spanmode="multi",
            slideshow=False,
            hotkey=("alt", "1"),
            perspective=Disabled(),
            zoom=1.5,
            pan=(0.25, -1.0),
            corrections=(OffsetsCorrection(((0, 0), (12, -3))),),
            sources=(("/a=b",), ("/one", "/two")),
        ),
        Profile(name="slides", delay=1230.0, sortmode="date_seeded_shuffle", sources=(("/images",),)),
    ],
    ids=["fixed image", "slideshow"],
)
def test_a_written_profile_reads_back_the_same(profile):
    assert profile_file.parse(profile_file.serialize(profile)) == profile


def test_a_selected_line_of_an_older_version_is_read():
    profile = profile_file.parse("name=old\nselected=/a.png;/b.png\ndisplay0paths=/images\n")

    assert profile.selected == ("/a.png", "/b.png")


@pytest.mark.parametrize("text", ["default", "disabled", "desk"])
def test_a_profile_file_keeps_its_perspective_choice(text):
    profile = profile_file.parse(f"name=p\nperspective={text}\ndisplay0paths=/a.png\n")

    assert profile.perspective == parse_choice(text)
    assert f"perspective={text}\n" in profile_file.serialize(profile)


def test_identical_sources_are_written_with_their_own_display_numbers():
    profile = Profile(name="twins", sources=(("/images",), ("/images",)))

    assert profile_file.serialize(profile).splitlines()[-2:] == ["display0paths=/images", "display1paths=/images"]


@pytest.mark.parametrize(
    ("line", "value"),
    [
        # Earlier versions loaded these with the defaults, so they still load.
        ("zoom=", ("zoom", 1.0)),
        ("zoom=big", ("zoom", 1.0)),
        ("zoom=0.5", ("zoom", 1.0)),
        ("zoom=inf", ("zoom", 1.0)),
        ("zoom=nan", ("zoom", 1.0)),
        ("align=", ("pan", (0.0, 0.0))),
        ("align=0.5", ("pan", (0.0, 0.0))),
        ("align=0.5,-2,9", ("pan", (0.5, -1.0))),
        ("align=nan,0.5", ("pan", (0.0, 0.0))),
        ("align=0.5,inf", ("pan", (0.0, 0.0))),
        ("align=-inf,nan", ("pan", (0.0, 0.0))),
        ("spanmode=diagonal", ("spanmode", "single")),
        ("sortmode=random", ("sortmode", "shuffle")),
        ("spangroups=0,x", ("spangroups", None)),
        ("spangroups=", ("spangroups", None)),
        ("spangroups=0,,1", ("spangroups", None)),
        ("hotkey=", ("hotkey", None)),
        ("a line without a setting", ("name", "lenient")),
        ("name", ("name", "lenient")),
        ("unknown=setting", ("name", "lenient")),
    ],
)
def test_values_earlier_versions_tolerated_still_load(line, value):
    key, expected = value

    assert getattr(profile_file.parse(f"name=lenient\n{line}\n"), key) == expected


@pytest.mark.parametrize(
    "line",
    [
        "delay=",
        "delay=soon",
        "delay=inf",
        "delay=nan",
        "delay=0",
        "delay=-5",
        "bezels=thin",
        "ppi=96.5",
        "diagonal_inches=24;big",
        "diagonal_inches=0;24",
    ],
)
def test_values_that_cant_be_used_make_a_profile_unusable(line):
    with pytest.raises(profile_file.ProfileFormatError):
        profile_file.parse(f"name=broken\n{line}\n")


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
        ("offsets=10,20;30,-40;50,60", True, [100, 100], [(10, 20), (30, -40)]),
        ("offsets=10,x;3", True, [100, 100], [(0, 0), (0, 0)]),
        ("bezels=5.0", False, [100, 100], [(0, 0), (0, 0)]),
        ("ppi=100;80", True, [100, 80], [(0, 0), (0, 0)]),
        ("ppi=100;80\nbezels=5.0", True, [100, 80], [(0, 0), (20, 0)]),
        ("ppi=100;80\nbezels=5.0\noffsets=10,20;30,-40", True, [100, 80], [(10, 20), (50, -40)]),
        ("ppi=100;80\nbezels=5.0;7.5;2.0", True, [100, 80], [(0, 0), (20, 0)]),
        ("diagonal_inches=24.0;19.0\nbezels=5.0", True, [91.7877987534291, 86.27367393593732], [(0, 0), (18, 0)]),
        (
            "diagonal_inches=24.0;19.0;27.0\nbezels=5.0",
            True,
            [91.7877987534291, 86.27367393593732],
            [(0, 0), (18, 0)],
        ),
        ("diagonal_inches=24.0\nbezels=5.0", False, [100, 100], [(0, 0), (0, 0)]),
        ("ppi=0;0\nbezels=5.0", True, [0, 0], [(0, 0), (0, 0)]),
    ],
)
def test_legacy_corrections_become_pixel_offsets(lines, ppimode, ppi_array, manual_offsets):
    profile = profile_file.parse(f"name=legacy\nspanmode=advanced\n{lines}\ndisplay0paths=/images\n")

    corrections = profile.display_corrections(TWO_RESOLUTIONS)

    assert corrections.ppimode is ppimode
    assert corrections.ppi_array == ppi_array
    assert corrections.manual_offsets == manual_offsets


def test_corrections_follow_the_displays_present():
    profile = profile_file.parse("name=legacy\nppi=100;80\nbezels=5.0\ndisplay0paths=/images\n")

    # A third display plugged in later is shifted by the bezels to its left too.
    three = profile.display_corrections([*TWO_RESOLUTIONS, (1920, 1080)])

    assert three.manual_offsets == [(0, 0), (20, 0), (20, 0)]
    assert profile.display_corrections(TWO_RESOLUTIONS).manual_offsets == [(0, 0), (20, 0)]


@pytest.mark.parametrize(
    ("displays", "manual_offsets"),
    [(1, [(1, 2)]), (2, [(1, 2), (3, -4)]), (3, [(1, 2), (3, -4), (0, 0)])],
)
def test_command_line_offsets_apply_to_the_displays_present(displays, manual_offsets):
    advanced = profile_file.draft(["/image.png"], spanmode="advanced", offsets=[(1, 2), (3, -4)])

    corrections = advanced.display_corrections(displays * [(1920, 1080)])

    # The renderer takes one offset per display present.
    assert corrections.manual_offsets[:displays] == manual_offsets


def test_command_line_offsets_only_apply_to_advanced_spanning():
    simple = profile_file.draft(["/image.png"], spanmode="single", offsets=[(1, 2)])

    assert simple.display_corrections([(1920, 1080)]).ppimode is False
    assert simple.corrections == ()
