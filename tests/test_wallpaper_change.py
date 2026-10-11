"""Changing the wallpaper: images are rendered, kept in the cache and shown, what went
wrong is said, and the last wallpaper is shown again at startup."""

import os
from types import SimpleNamespace

import pytest
from PIL import Image

import superpaper.session as session
from superpaper import render
from superpaper.desktop.process import Result
from superpaper.paths import AppPaths
from superpaper.profile_id import ProfileId
from superpaper.profiles import Profile
from tests.conftest import monitor

# Two 2x2 displays with a one-pixel gap between them, the second one pixel lower.
TINY_DISPLAYS = [monitor(0, 0, 2, 2, 10, 10), monitor(3, 1, 2, 2, 10, 10)]


def write_image(path, size=(5, 3), colour=(10, 20, 30), *, modified=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path)
    if modified is not None:
        os.utime(path, ns=(modified, modified))
    return str(path)


def settings(name, *, spanmode="single", legacy_corrections=False):
    """A profile's settings; ``legacy_corrections`` adds an offsets= line from before display layouts."""
    corrections = (("offsets", ((0, 0), (0, 0))),) if legacy_corrections else ()
    return Profile(name=name, spanmode=spanmode, slideshow=False, corrections=corrections)


class FakeDesktop:
    """The desktop: records what it is handed, and takes it unless ``answer`` says otherwise."""

    def __init__(self):
        self.handed = []
        self.answer = Result()
        self.takes_pieces = False

    def set_wallpaper(self, image, pieces, *, set_command, activities):
        self.handed.append((image, pieces))
        self.activities = activities
        return self.answer


@pytest.fixture
def desktop(monkeypatch):
    fake = FakeDesktop()
    monkeypatch.setattr(session.desktop, "set_wallpaper", fake.set_wallpaper)
    monkeypatch.setattr(session.desktop, "takes_pieces", lambda set_command: fake.takes_pieces)
    return fake


def change(name, files, paths, layout):
    """Show the saved profile ``name``'s ``files``, as a change of the running profile does."""
    return session.show(settings(name), files, paths, display_system=layout, profile_id=ProfileId(name), running=name)


def draft(profile, images, paths, layout):
    return session.show(profile, images, paths, display_system=layout)


def cached(paths):
    return sorted(path.relative_to(paths.cache).as_posix() for path in paths.cache.rglob("*") if path.is_file())


def errors(caplog):
    return [record.getMessage() for record in caplog.records if record.levelname == "ERROR"]


def test_a_change_is_rendered_kept_and_shown(tmp_path, app_paths, display_layout, desktop):
    source = [write_image(tmp_path / "source.png")]
    layout = display_layout(TINY_DISPLAYS)

    assert change("simple", source, app_paths, layout) is None
    assert change("simple", source, app_paths, layout) is None

    first, second = app_paths.cache / "simple-a.png", app_paths.cache / "simple-b.png"
    assert desktop.handed == [(str(first), None), (str(second), None)]
    # Once the desktop shows a render, the previous one goes.
    assert cached(app_paths) == ["simple-b.png"]
    with Image.open(second) as image:
        assert image.size == (5, 3)
    # KDE gives it to the activity named after the running profile.
    assert desktop.activities.current_profile == "simple"


def test_the_previous_render_stays_while_the_desktop_refuses_the_new_one(tmp_path, app_paths, display_layout, desktop):
    source = [write_image(tmp_path / "source.png")]
    desktop.answer = Result("Plasma did not take the wallpaper")

    assert change("simple", source, app_paths, display_layout(TINY_DISPLAYS)) == "Plasma did not take the wallpaper"
    change("simple", source, app_paths, display_layout(TINY_DISPLAYS))

    assert cached(app_paths) == ["simple-a.png", "simple-b.png"]


def test_drafts_leave_the_profiles_renders_alone(tmp_path, app_paths, display_layout, desktop):
    write_image(app_paths.cache / "simple-a.png")

    draft(settings("simple"), [write_image(tmp_path / "source.png")], app_paths, display_layout(TINY_DISPLAYS))

    assert desktop.handed == [(str(app_paths.cache / "preview" / "draft-a.png"), None)]
    assert cached(app_paths) == ["preview/draft-a.png", "simple-a.png"]


def test_nothing_is_shown_without_images(app_paths, display_layout, desktop, caplog):
    assert draft(settings("p"), [], app_paths, display_layout()) == "'p' has no images to show."

    assert errors(caplog) == ["Wallpaper change skipped: 'p' has no images to show."]
    assert desktop.handed == []


@pytest.mark.parametrize(
    ("spanmode", "legacy_corrections", "renderer"),
    [
        ("single", False, "simple"),
        # A single-image profile with legacy corrections (offsets=, ppi=, ...) is spanned
        # with the advanced renderer.
        ("single", True, "advanced"),
        ("advanced", False, "advanced"),
        ("multi", False, "multi"),
    ],
)
def test_the_span_mode_picks_the_renderer(
    app_paths, display_layout, desktop, monkeypatch, spanmode, legacy_corrections, renderer
):
    called = []
    for name in ("simple", "advanced", "multi"):
        monkeypatch.setattr(render, name, lambda *args, name=name, **kwargs: called.append(name))
    files = ["one.png", "two.png"] if spanmode == "multi" else ["one.png"]

    draft(settings("p", spanmode=spanmode, legacy_corrections=legacy_corrections), files, app_paths, display_layout())

    assert called == [renderer]


def test_an_image_that_cant_be_used_skips_the_change(tmp_path, app_paths, display_layout, desktop, caplog):
    gone = tmp_path / "gone.png"

    problem = draft(settings("simple"), [str(gone)], app_paths, display_layout(TINY_DISPLAYS))

    assert problem == f"The image {gone} doesn't exist."
    assert errors(caplog) == [f"Wallpaper change skipped: The image {gone} doesn't exist."]
    assert desktop.handed == []
    assert cached(app_paths) == []


@pytest.mark.parametrize("spanmode", ["single", "multi"])
def test_images_that_dont_fit_the_displays_are_not_rendered(
    tmp_path, app_paths, display_layout, desktop, caplog, spanmode
):
    files = [write_image(tmp_path / f"{index}.png") for index in range(2)]
    one_display = display_layout([monitor(0, 0, 2, 2, 10, 10)])

    problem = draft(settings("p", spanmode=spanmode), files, app_paths, one_display)

    assert problem == "No complete wallpaper selection is available for profile 'p'."
    assert errors(caplog) == [f"Wallpaper change skipped: {problem}"]
    assert desktop.handed == []
    assert cached(app_paths) == []


def test_a_render_that_cant_be_kept_isnt_shown(tmp_path, app_paths, display_layout, desktop):
    not_a_directory = tmp_path / "a file"
    not_a_directory.write_text("", encoding="utf-8")
    paths = AppPaths(config=app_paths.config, profiles=app_paths.profiles, cache=not_a_directory)

    problem = draft(settings("p"), [write_image(tmp_path / "source.png")], paths, display_layout(TINY_DISPLAYS))

    assert problem.startswith("The wallpaper could not be saved: ")
    assert desktop.handed == []


def test_a_wallpaper_goes_to_the_desktop_and_then_to_the_hook(app_paths, display_layout, desktop, monkeypatch, caplog):
    hooked = []
    monkeypatch.setattr(session.desktop, "run_hook", lambda *args: hooked.append(args) or Result("python3 is missing"))
    desktop.answer = Result("the setter failed")
    script = app_paths.config / "run-after-wp-change.py"
    script.touch()
    image = app_paths.cache / "p-a.png"

    taken = session.set_wallpaper(
        image, ["/a.png", "/b c.png"], display_system=display_layout(), paths=app_paths, set_command="setter {image}"
    )

    assert taken.problem == "the setter failed"
    assert desktop.handed == [(str(image), None)]
    assert hooked == [(script, str(image), ["/a.png", "/b c.png"])]
    # Failures are logged, not raised.
    assert errors(caplog) == ["the setter failed", "python3 is missing"]


def test_a_desktop_that_takes_pieces_gets_one_per_display(app_paths, display_layout, desktop):
    desktop.takes_pieces = True
    image = app_paths.cache / "p-a.png"
    write_image(image)

    assert session.set_wallpaper(image, [], display_system=display_layout(TINY_DISPLAYS), paths=app_paths).ok

    pieces = [str(app_paths.cache / "p-a-crop-0.png"), str(app_paths.cache / "p-a-crop-1.png")]
    assert desktop.handed == [(str(image), pieces)]
    # KDE finds them again for an activity named after the profile, by its exact name.
    write_image(app_paths.cache / "homework-a.png")
    write_image(app_paths.cache / "homework-a-crop-0.png")
    assert desktop.activities.cached_pieces("p") == pieces
    assert desktop.activities.cached_pieces("home") == []
    assert desktop.activities.cached_pieces("an activity/with a slash") == []


@pytest.fixture
def startup(app_paths, display_layout, desktop):
    """Show the last wallpaper of profile "main" again, as the tray does when it starts."""
    main = SimpleNamespace(profile=settings("main"), profile_id=ProfileId("main"))

    def restore():
        return session.show_again(main, app_paths, display_system=display_layout(TINY_DISPLAYS))

    return restore


def test_startup_shows_the_last_render_again(app_paths, desktop, startup):
    write_image(app_paths.cache / "main-a.png", modified=2_000_000_000)
    write_image(app_paths.cache / "preview" / "draft-a.png", modified=1_000_000_000)

    assert startup() is True
    assert desktop.handed == [(str(app_paths.cache / "main-a.png"), None)]
    assert desktop.activities.current_profile == "main"


def test_startup_shows_a_draft_that_was_shown_after_it(app_paths, desktop, startup):
    write_image(app_paths.cache / "main-a.png", modified=1_000_000_000)
    write_image(app_paths.cache / "preview" / "draft-b.png", modified=2_000_000_000)

    assert startup() is True
    assert desktop.handed == [(str(app_paths.cache / "preview" / "draft-b.png"), None)]


def test_startup_shows_the_pieces_in_display_order_where_the_desktop_takes_them(app_paths, desktop, startup):
    desktop.takes_pieces = True
    for name in ("main-b.png", "main-b-crop-1.png", "main-b-crop-0.png"):
        write_image(app_paths.cache / name)

    assert startup() is True
    pieces = [str(app_paths.cache / "main-b-crop-0.png"), str(app_paths.cache / "main-b-crop-1.png")]
    assert desktop.handed == [(str(app_paths.cache / "main-b.png"), pieces)]


def test_startup_without_a_render_shows_nothing(app_paths, desktop, startup):
    write_image(app_paths.cache / "preview" / "draft-a.png")

    assert startup() is False
    assert desktop.handed == []
