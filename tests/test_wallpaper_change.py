"""Changing the wallpaper: images are rendered, kept in the cache and shown, what went
wrong is said, and the last wallpaper is shown again at startup."""

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PIL import Image

import superpaper.wallpaper_change as wallpaper_change
from superpaper.desktop.process import Result
from superpaper.desktop.wallpaper import Pieces, Spanned
from superpaper.geometry.perspective import (
    Default,
    DegeneratePerspective,
    Disabled,
    Named,
    Perspective,
    Swivel,
    SwivelAxis,
    Tilt,
)
from superpaper.paths import AppPaths
from superpaper.profiles.profile_file import OffsetsCorrection, Profile
from superpaper.profiles.profile_id import ProfileId
from superpaper.rendering import render
from tests.conftest import TINY_DISPLAYS, monitor


def write_image(path, size=(5, 3), colour=(10, 20, 30), *, modified=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path)
    if modified is not None:
        os.utime(path, ns=(modified, modified))
    return str(path)


def settings(name, *, spanmode="single", legacy_corrections=False):
    """A profile's settings; ``legacy_corrections`` adds an offsets= line from before display layouts."""
    corrections = (OffsetsCorrection(((0, 0), (0, 0))),) if legacy_corrections else ()
    return Profile(name=name, spanmode=spanmode, slideshow=False, corrections=corrections)


def change(name, files, paths, layout, desktop):
    """Show the saved profile ``name``'s ``files``, as a change of the running profile does."""
    return wallpaper_change.show(
        settings(name),
        files,
        paths,
        desktop=desktop,
        layout=layout,
        set_command="",
        profile_id=ProfileId.parse(name, windows_names=False),
        running=name,
    )


def draft(profile, images, paths, layout, desktop):
    return wallpaper_change.show(profile, images, paths, desktop=desktop, layout=layout, set_command="")


def cached(paths):
    """The renders in the cache; their signatures are left out."""
    files = (path for path in paths.cache.rglob("*") if path.is_file() and path.suffix != ".sig")
    return sorted(path.relative_to(paths.cache).as_posix() for path in files)


def errors(caplog):
    return [record.getMessage() for record in caplog.records if record.levelname == "ERROR"]


DESK = Perspective(
    "desk", 0, (0.0, 0.0, 1000.0), (Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0),) * 2, (Tilt(0.0, 0.0, 0.0),) * 2
)


def test_a_change_is_rendered_kept_and_shown(tmp_path, app_paths, display_layout, desktop):
    source = [write_image(tmp_path / "source.png")]
    layout = display_layout(TINY_DISPLAYS)

    assert change("simple", source, app_paths, layout, desktop) is None
    assert change("simple", source, app_paths, layout, desktop) is None

    first, second = app_paths.cache / "simple-a.png", app_paths.cache / "simple-b.png"
    assert desktop.handed == [Spanned(str(first)), Spanned(str(second))]
    # Once the desktop shows a render, the previous one goes.
    assert cached(app_paths) == ["simple-b.png"]
    with Image.open(second) as image:
        assert image.size == (5, 3)
    # KDE gives it to the activity named after the running profile.
    assert desktop.profiles.current_profile == "simple"


def test_the_previous_render_stays_while_the_desktop_refuses_the_new_one(tmp_path, app_paths, display_layout, desktop):
    source = [write_image(tmp_path / "source.png")]
    desktop.answer = Result("Plasma did not take the wallpaper")
    layout = display_layout(TINY_DISPLAYS)

    assert change("simple", source, app_paths, layout, desktop) == "Plasma did not take the wallpaper"
    change("simple", source, app_paths, layout, desktop)

    assert cached(app_paths) == ["simple-a.png", "simple-b.png"]


def test_drafts_leave_the_profiles_renders_alone(tmp_path, app_paths, display_layout, desktop):
    write_image(app_paths.cache / "simple-a.png")

    draft(
        settings("simple"),
        [write_image(tmp_path / "source.png")],
        app_paths,
        display_layout(TINY_DISPLAYS),
        desktop,
    )

    assert desktop.handed == [Spanned(str(app_paths.cache / "preview" / "draft-a.png"))]
    assert cached(app_paths) == ["preview/draft-a.png", "simple-a.png"]


def test_nothing_is_shown_without_images(app_paths, display_layout, desktop, caplog):
    assert draft(settings("p"), [], app_paths, display_layout(), desktop) == "'p' has no images to show."

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

    draft(
        settings("p", spanmode=spanmode, legacy_corrections=legacy_corrections),
        files,
        app_paths,
        display_layout(),
        desktop,
    )

    assert called == [renderer]


def test_an_image_that_cant_be_used_skips_the_change(tmp_path, app_paths, display_layout, desktop, caplog):
    gone = tmp_path / "gone.png"

    problem = draft(settings("simple"), [str(gone)], app_paths, display_layout(TINY_DISPLAYS), desktop)

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

    problem = draft(settings("p", spanmode=spanmode), files, app_paths, one_display, desktop)

    assert problem == "No complete wallpaper selection is available for profile 'p'."
    assert errors(caplog) == [f"Wallpaper change skipped: {problem}"]
    assert desktop.handed == []
    assert cached(app_paths) == []


def test_a_render_that_cant_be_kept_isnt_shown(tmp_path, app_paths, display_layout, desktop):
    not_a_directory = tmp_path / "a file"
    not_a_directory.write_text("", encoding="utf-8")
    paths = AppPaths(config=app_paths.config, profiles=app_paths.profiles, cache=not_a_directory)

    problem = draft(
        settings("p"), [write_image(tmp_path / "source.png")], paths, display_layout(TINY_DISPLAYS), desktop
    )

    assert problem.startswith("The wallpaper could not be saved: ")
    assert desktop.handed == []


def test_a_perspective_that_cant_be_solved_skips_the_change(app_paths, display_layout, desktop, monkeypatch, caplog):
    def edge_on(*args, **kwargs):
        message = "a display is edge-on"
        raise DegeneratePerspective(message)

    monkeypatch.setattr(render, "advanced", edge_on)
    profile = replace(settings("p", spanmode="advanced"), perspective=Named("desk"))
    layout = replace(display_layout(TINY_DISPLAYS), use_perspective=True, perspectives=(DESK,))

    problem = draft(profile, ["one.png"], app_paths, layout, desktop)

    assert problem is not None
    assert "'p'" in problem
    assert "desk" in problem
    assert "edge-on" in problem
    assert errors(caplog) == [f"Wallpaper change skipped: {problem}"]
    assert desktop.handed == []


def test_a_render_that_cant_be_cut_for_the_displays_isnt_shown(tmp_path, app_paths, display_layout, desktop):
    desktop.pieces_taken = True
    (app_paths.cache / "simple-a-crop-0.png").mkdir(parents=True)

    problem = change(
        "simple", [write_image(tmp_path / "source.png")], app_paths, display_layout(TINY_DISPLAYS), desktop
    )

    assert problem is not None
    assert problem.startswith("The wallpaper could not be cut for the displays: ")
    assert desktop.handed == []


def test_a_wallpaper_goes_to_the_desktop_and_then_to_the_hook(app_paths, display_layout, desktop, caplog):
    desktop.hook_answer = Result("python3 is missing")
    desktop.answer = Result("the setter failed")
    script = app_paths.config / "run-after-wp-change.py"
    script.touch()
    image = app_paths.cache / "p-a.png"

    taken = wallpaper_change.set_wallpaper(
        desktop,
        image,
        ["/a.png", "/b c.png"],
        layout=display_layout(),
        paths=app_paths,
        set_command="setter {image}",
    )

    assert taken.problem == "the setter failed"
    assert desktop.handed == [Spanned(str(image))]
    assert desktop.hooks == [(script, str(image), ["/a.png", "/b c.png"])]
    # Failures are logged, not raised.
    assert errors(caplog) == ["the setter failed", "python3 is missing"]


def test_a_desktop_that_takes_pieces_gets_one_per_display(app_paths, display_layout, desktop):
    desktop.pieces_taken = True
    image = app_paths.cache / "p-a.png"
    write_image(image)

    assert wallpaper_change.set_wallpaper(desktop, image, [], layout=display_layout(TINY_DISPLAYS), paths=app_paths).ok

    pieces = (str(app_paths.cache / "p-a-crop-0.png"), str(app_paths.cache / "p-a-crop-1.png"))
    assert desktop.handed == [Pieces(str(image), pieces)]
    # KDE finds them again for an activity named after the profile, by its exact name.
    write_image(app_paths.cache / "homework-a.png")
    write_image(app_paths.cache / "homework-a-crop-0.png")
    assert desktop.profiles.cached_pieces("p") == list(pieces)
    assert desktop.profiles.cached_pieces("home") == []
    assert desktop.profiles.cached_pieces("an activity/with a slash") == []


CURRENT = ["/current.png"]


def write_render(cache, name, layout, files=CURRENT, *, profile=None, **kwargs):
    """A render in ``cache`` made for ``layout``, ``files`` and ``profile`` (profile "main" by default), with its signature."""
    path = cache / name
    write_image(path, **kwargs)
    signature = wallpaper_change.render_signature(layout, profile or settings("main"), files)
    (cache / f"{name}.sig").write_text(signature, encoding="utf-8")


def selection_showing(*files):
    return SimpleNamespace(current=lambda: list(files))


@pytest.fixture
def startup(app_paths, display_layout, desktop):
    """Show the last wallpaper of profile "main" again, as the tray does when it starts."""
    main = SimpleNamespace(
        profile=settings("main"),
        profile_id=ProfileId.parse("main", windows_names=False),
        selection=selection_showing(*CURRENT),
    )

    def restore(layout=None):
        return wallpaper_change.show_again(
            main, app_paths, desktop=desktop, layout=layout or display_layout(TINY_DISPLAYS), set_command=""
        )

    return restore


def test_startup_shows_the_last_render_again(app_paths, display_layout, desktop, startup):
    write_render(app_paths.cache, "main-a.png", display_layout(TINY_DISPLAYS), modified=2_000_000_000)

    assert startup() is True
    assert desktop.handed == [Spanned(str(app_paths.cache / "main-a.png"))]
    assert desktop.profiles.current_profile == "main"


def test_startup_ignores_a_draft_that_was_shown_after_it(app_paths, display_layout, desktop, startup):
    write_render(app_paths.cache, "main-a.png", display_layout(TINY_DISPLAYS), modified=1_000_000_000)
    write_render(app_paths.cache, "preview/draft-b.png", display_layout(TINY_DISPLAYS), modified=2_000_000_000)

    assert startup() is True
    assert desktop.handed == [Spanned(str(app_paths.cache / "main-a.png"))]


def test_startup_renders_again_what_was_made_for_other_images(app_paths, display_layout, desktop, startup):
    write_render(app_paths.cache, "main-a.png", display_layout(TINY_DISPLAYS), files=["/earlier.png"])

    assert startup() is False
    assert desktop.handed == []


def test_startup_renders_again_what_was_made_for_another_layout(app_paths, display_layout, desktop, startup):
    write_render(app_paths.cache, "main-a.png", display_layout(TINY_DISPLAYS))
    other = replace(display_layout(TINY_DISPLAYS), bezels_mm=((1.0, 1.0), (1.0, 1.0)))

    assert startup(other) is False
    assert desktop.handed == []


def test_startup_renders_again_what_was_made_with_other_render_settings(app_paths, display_layout, desktop):
    layout = display_layout(TINY_DISPLAYS)
    write_render(app_paths.cache, "main-a.png", layout)

    def restore(profile):
        main = SimpleNamespace(
            profile=profile,
            profile_id=ProfileId.parse("main", windows_names=False),
            selection=selection_showing(*CURRENT),
        )
        return wallpaper_change.show_again(main, app_paths, desktop=desktop, layout=layout, set_command="")

    assert restore(replace(settings("main"), zoom=1.5)) is False
    assert restore(replace(settings("main"), pan=(0.5, 0.0))) is False
    assert restore(replace(settings("main"), spanmode="advanced")) is False
    assert restore(replace(settings("main"), delay=5.0)) is True


def test_startup_renders_again_what_has_no_signature(app_paths, desktop, startup):
    write_image(app_paths.cache / "main-a.png")

    assert startup() is False
    assert desktop.handed == []


def test_startup_renders_when_the_profile_has_no_images(app_paths, display_layout, desktop):
    write_render(app_paths.cache, "main-a.png", display_layout(TINY_DISPLAYS))
    main = SimpleNamespace(
        profile=settings("main"), profile_id=ProfileId.parse("main", windows_names=False), selection=selection_showing()
    )

    layout = display_layout(TINY_DISPLAYS)
    assert wallpaper_change.show_again(main, app_paths, desktop=desktop, layout=layout, set_command="") is False


def test_a_change_keeps_what_it_was_made_from_for_the_next_start(tmp_path, app_paths, display_layout, desktop):
    source = [write_image(tmp_path / "source.png")]
    layout = display_layout(TINY_DISPLAYS)
    assert change("main", source, app_paths, layout, desktop) is None
    desktop.handed.clear()
    main = SimpleNamespace(
        profile=settings("main"),
        profile_id=ProfileId.parse("main", windows_names=False),
        selection=selection_showing(*source),
    )

    assert wallpaper_change.show_again(main, app_paths, desktop=desktop, layout=layout, set_command="") is True
    assert desktop.handed == [Spanned(str(app_paths.cache / "main-a.png"))]


def test_startup_shows_the_pieces_in_display_order_where_the_desktop_takes_them(
    app_paths, display_layout, desktop, startup
):
    desktop.pieces_taken = True
    write_render(app_paths.cache, "main-b.png", display_layout(TINY_DISPLAYS))
    for name in ("main-b-crop-1.png", "main-b-crop-0.png"):
        write_image(app_paths.cache / name)

    assert startup() is True
    pieces = (str(app_paths.cache / "main-b-crop-0.png"), str(app_paths.cache / "main-b-crop-1.png"))
    assert desktop.handed == [Pieces(str(app_paths.cache / "main-b.png"), pieces)]


def test_a_desktop_that_keeps_its_wallpaper_isnt_given_it_again_at_startup(app_paths, display_layout, desktop, startup):
    desktop.wallpaper_kept = True
    write_render(app_paths.cache, "main-a.png", display_layout(TINY_DISPLAYS))

    assert startup() is True
    assert desktop.handed == []


@pytest.mark.parametrize(
    ("perspective", "default", "rendered_again"),
    [
        (Default(), "desk", True),
        (Default(), "gone", False),
        (Default(), None, False),
        (Named("desk"), None, True),
        (Named("gone"), None, False),
        (Disabled(), "desk", False),
    ],
)
def test_a_perspective_that_no_longer_exists_isnt_rendered_again_at_startup(
    app_paths, display_layout, desktop, perspective, default, rendered_again
):
    desktop.wallpaper_kept = True
    layout = replace(
        display_layout(TINY_DISPLAYS), use_perspective=True, default_perspective=default, perspectives=(DESK,)
    )
    profile = replace(settings("main", spanmode="advanced"), perspective=perspective)
    write_render(app_paths.cache, "main-a.png", layout, profile=profile)
    main = SimpleNamespace(
        profile=profile,
        profile_id=ProfileId.parse("main", windows_names=False),
        selection=selection_showing(*CURRENT),
    )

    assert wallpaper_change.show_again(main, app_paths, desktop=desktop, layout=layout, set_command="") is True
    assert bool(desktop.handed) is rendered_again


def test_startup_without_a_render_shows_nothing(app_paths, display_layout, desktop, startup):
    write_render(app_paths.cache, "preview/draft-a.png", display_layout(TINY_DISPLAYS))

    assert startup() is False
    assert desktop.handed == []
