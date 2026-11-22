"""One wallpaper change: render images for the display layout (superpaper.rendering.render),
keep the render (superpaper.rendering.render_cache) and hand it to the desktop
(superpaper.desktop).

The command line runs show() directly; the Session's worker runs it for the tray.
"""

import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import superpaper.rendering.render as render
from superpaper.desktop.backend import Desktop
from superpaper.desktop.process import Result
from superpaper.desktop.wallpaper import Pieces, ProfileWallpapers, Spanned, Wallpaper
from superpaper.paths import AppPaths
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId, ProfileIdError
from superpaper.rendering import render_cache
from superpaper.rendering.source_image import SourceImageError

if TYPE_CHECKING:
    from PIL import Image

    from superpaper.geometry.displays import Layout
    from superpaper.profiles.profile_store import StoredProfile

logger = logging.getLogger(__name__)


def show(
    profile: Profile,
    files: Sequence[str],
    paths: AppPaths,
    *,
    desktop: Desktop,
    layout: Layout,
    set_command: str,
    profile_id: ProfileId | None = None,
    running: str | None = None,
) -> str | None:
    """Render ``files`` with ``profile``'s settings for ``layout``, keep the render
    in the cache and hand it to the desktop. Returns what went wrong, which is also
    logged, or None.

    The render is kept as the saved profile ``profile_id``'s, or without one as a draft.
    ``set_command`` is the user's own wallpaper setter command, if any; ``running`` names
    the running profile, whose KDE activity gets the wallpaper.
    """
    if not files:
        return _skipped(f"'{profile.name}' has no images to show.")
    try:
        image = _render(profile, files, layout)
    except SourceImageError as error:
        return _skipped(str(error))
    if image is None:
        return _skipped(f"No complete wallpaper selection is available for profile '{profile.name}'.")
    try:
        slot = (
            render_cache.draft_slot(paths.cache)
            if profile_id is None
            else render_cache.slot(paths.cache, profile_id.value)
        )
        output = render_cache.save(
            slot, image, extension=desktop.render_extension(), signature=render_signature(layout, files)
        )
    except OSError as error:
        return _skipped(f"The wallpaper could not be saved: {error}")
    result = set_wallpaper(desktop, output, files, layout=layout, paths=paths, set_command=set_command, running=running)
    if not result.ok:
        return result.problem
    # Until the desktop takes the new render, the previous one may still be on screen.
    render_cache.forget_previous(output)
    return None


def _skipped(problem: str) -> str:
    logger.error("Wallpaper change skipped: %s", problem)
    return problem


def _render(profile: Profile, files: Sequence[str], layout: Layout) -> Image.Image | None:
    """Compose ``profile``'s desktop image from ``files``; None if they don't fit its span
    mode and the displays."""
    resolutions = layout.resolutions()
    if profile.spanmode == "multi":
        if len(files) != len(resolutions):
            return None
        return render.multi(files, layout, zoom=profile.zoom, pan=profile.pan)
    corrections = profile.display_corrections(resolutions)
    if profile.spanmode == "single" and not corrections.ppimode:
        if len(files) != 1:
            return None
        return render.simple(files[0], layout, zoom=profile.zoom, pan=profile.pan)
    # Advanced spanning, or a single image with legacy corrections (offsets=, ppi=, ...).
    if len(files) != (len(profile.spangroups) if profile.spangroups else 1):
        return None
    perspective = layout.perspective_for(profile.perspective) if layout.use_perspective else None
    return render.advanced(
        files,
        layout,
        manual_offsets=corrections.manual_offsets,
        spangroups=profile.spangroups,
        perspective=perspective,
        zoom=profile.zoom,
        pan=profile.pan,
    )


def set_wallpaper(
    desktop: Desktop,
    image: Path | str,
    source_files: Sequence[str] = (),
    *,
    layout: Layout,
    paths: AppPaths,
    set_command: str = "",
    running: str | None = None,
) -> Result:
    """Hand the rendered wallpaper ``image`` to the desktop, then run the user's
    run-after-wp-change.py with it and its ``source_files``. Returns the desktop's answer;
    problems are logged.

    Desktops that take one image per display get ``image`` cut for ``layout``.
    """
    wallpaper: Wallpaper
    if desktop.takes_pieces(set_command):
        pieces = tuple(str(piece) for piece in render_cache.cut_pieces(Path(image), layout))
        wallpaper = Pieces(str(image), pieces)
    else:
        wallpaper = Spanned(str(image))
    result = desktop.set_wallpaper(
        wallpaper, set_command=set_command, profiles=_profile_wallpapers(paths, running, desktop)
    )
    _log_problem(result)
    script = paths.config / "run-after-wp-change.py"
    if script.is_file():
        _log_problem(desktop.run_hook(script, str(image), list(source_files)))
    return result


def render_signature(layout: Layout, files: Sequence[str]) -> str:
    """What a render is made from: the display layout and the images, as a stable digest."""
    return hashlib.sha256(repr((layout, list(files))).encode()).hexdigest()


def show_again(stored: StoredProfile, paths: AppPaths, *, desktop: Desktop, layout: Layout, set_command: str) -> bool:
    """Show the last wallpaper of the profile ``stored`` again at startup, without rendering
    anything. Returns False unless that render was made for ``layout`` and the profile's
    current images, so that it can be rendered; drafts shown since are ignored.
    """
    rendered = render_cache.latest(render_cache.slot(paths.cache, stored.profile_id.value))
    if rendered is None:
        logger.info("Profile '%s' has no earlier render to show.", stored.profile.name)
        return False
    current = stored.selection.current()
    if not current or rendered.signature != render_signature(layout, current):
        logger.info("The last render of profile '%s' is not for its current images and displays.", stored.profile.name)
        return False
    image = str(rendered.image)
    running = stored.profile.name
    if desktop.takes_pieces(set_command) and rendered.pieces:
        pieces = tuple(str(piece) for piece in rendered.pieces)
        logger.info("Use wallpaper crop pieces: %s", pieces)
        _log_problem(
            desktop.set_wallpaper(
                Pieces(image, pieces), set_command=set_command, profiles=_profile_wallpapers(paths, running, desktop)
            )
        )
    elif desktop.keeps_wallpaper() and not _is_perspective_render(stored.profile, layout):
        pass
    else:
        set_wallpaper(desktop, image, layout=layout, paths=paths, set_command=set_command, running=running)
    return True


def _is_perspective_render(profile: Profile, layout: Layout) -> bool:
    """Whether the render is a perspective one, which a desktop that keeps its wallpaper
    still gets again at startup."""
    if profile.spanmode != "advanced" or not layout.use_perspective:
        return False
    return layout.perspective_for(profile.perspective) is not None


def _profile_wallpapers(paths: AppPaths, running: str | None, desktop: Desktop) -> ProfileWallpapers:
    """How the desktop finds the wallpapers of the profiles other than the running one."""
    windows_names = desktop.strict_profile_names()
    return ProfileWallpapers(
        current_profile=running,
        cached_pieces=lambda name: _cached_pieces(paths.cache, name, windows_names=windows_names),
        state_dir=paths.config,
    )


def _cached_pieces(cache_dir: Path, profile_name: str, *, windows_names: bool) -> list[str]:
    """The per-display images last rendered for the profile named ``profile_name``."""
    try:
        profile_id = ProfileId.parse(profile_name, windows_names=windows_names)
    except ProfileIdError:  # an activity name no profile can have
        return []
    rendered = render_cache.latest(render_cache.slot(cache_dir, profile_id.value))
    return [str(piece) for piece in rendered.pieces] if rendered else []


def _log_problem(result: Result) -> None:
    if not result.ok:
        logger.error("%s", result.problem)
