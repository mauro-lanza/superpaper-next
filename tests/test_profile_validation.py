"""What keeps a profile from being saved or shown: profiles.validate, which the editor
shows the user instead of saving or applying."""

import pytest

from superpaper import profiles
from superpaper.profiles import Profile


@pytest.fixture
def images(tmp_path):
    folder = tmp_path / "images"
    folder.mkdir()
    (folder / "a.png").touch()
    return str(folder)


def test_a_complete_profile_has_no_problems(images):
    assert profiles.validate(Profile(name="work", delay=600.0, sources=((images,),))) == []


def test_a_draft_may_use_a_name_saved_profiles_may_not(images):
    # Only saving checks the name against the profiles directory.
    assert profiles.validate(Profile(name="cli", slideshow=False, sources=((images,),))) == []


def test_upper_case_image_extensions_are_images(tmp_path):
    camera = tmp_path / "camera"
    camera.mkdir()
    (camera / "IMG_0001.JPG").touch()

    assert profiles.validate(Profile(name="camera", slideshow=False, sources=((str(camera),),))) == []


@pytest.mark.parametrize(
    ("settings", "problem"),
    [
        ({"name": "  "}, "You must enter a name for the profile."),
        ({"spanmode": "single", "sources": (("a",), ("b",))}, "only one paths field is needed"),
        ({"spanmode": "multi"}, "each display needs its own paths field"),
        ({"slideshow": True, "delay": 19.0}, "at least 20 seconds"),
        ({"sources": ()}, "You must enter at least one path for images."),
        ({"sources": ((),)}, "At least one path for wallpapers must be given."),
        ({"spanmode": "multi", "sources": (("a",), ())}, "Add an image source for every display present."),
        ({"spanmode": "advanced", "spangroups": ((0,), (1,))}, "Add an image source for every span group."),
    ],
)
def test_settings_that_cant_be_used_are_explained(images, settings, problem):
    profile = Profile(**{"name": "work", "slideshow": False, "sources": ((images,),), **settings})

    assert any(problem in reported for reported in profiles.validate(profile))


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

    assert profiles.validate(Profile(name="work", slideshow=False, sources=((path,),))) == [message.format(path)]


def test_every_problem_is_reported_at_once():
    profile = Profile(name="", spanmode="multi", slideshow=True, delay=5.0, sources=((),))

    assert len(profiles.validate(profile)) == 4
