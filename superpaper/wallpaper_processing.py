"""
The jobs that change the wallpaper: choose a profile's images, render them for the
display layout (superpaper.render), keep the result (superpaper.render_cache) and show
it (superpaper.desktop); and the slideshow timer.

Written by Henri Hänninen, copyright 2022 under MIT licence.
"""

from pathlib import Path
from threading import Lock, Thread, Timer

import superpaper.desktop as desktop
import superpaper.render as render
import superpaper.render_cache as render_cache
import superpaper.sp_logging as sp_logging
from superpaper.desktop.kde import Activities
from superpaper.desktop.process import Result
from superpaper.displays import DisplaySystem
from superpaper.paths import AppPaths
from superpaper.profile_id import ProfileId, ProfileIdError
from superpaper.sp_platform import IS_WINDOWS

# Global constants

G_ACTIVE_PROFILE = None
G_WALLPAPER_CHANGE_LOCK = Lock()
G_WALLPAPER_CHANGE_PENDING = Lock()
G_SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp")


def is_supported_image(filename: str) -> bool:
    """Whether a file name has an extension Superpaper renders, in any letter case."""
    return filename.lower().endswith(G_SUPPORTED_IMAGE_EXTENSIONS)


class RepeatedTimer:
    """Threaded timer used for slideshow."""

    # Credit:
    # https://stackoverflow.com/questions/3393612/run-certain-code-every-n-seconds/13151299#13151299
    def __init__(self, interval, function, *args, **kwargs):
        self._timer = None
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.is_running = False
        self.start()

    def _run(self):
        self.is_running = False
        self.start()
        self.function(*self.args, **self.kwargs)

    def start(self):
        """Starts timer."""
        if not self.is_running:
            self._timer = Timer(self.interval, self._run)
            self._timer.daemon = True
            self._timer.start()
            self.is_running = True

    def stop(self):
        """Stops timer."""
        if self._timer is not None:
            self._timer.cancel()
        self.is_running = False


def set_wallpaper(image, source_files=None, *, display_system: DisplaySystem, paths: AppPaths, set_command="") -> bool:
    """Hand the rendered wallpaper ``image`` to the desktop, then run the user's
    run-after-wp-change.py. Returns whether the desktop took it.

    Desktops that take one image per display get ``image`` cut for ``display_system``.
    ``set_command`` is the user's own setter command, if any (Linux only).
    """
    pieces = None
    if desktop.takes_pieces(set_command):
        pieces = [str(piece) for piece in render_cache.cut_pieces(Path(image), display_system)]
    result = desktop.set_wallpaper(str(image), pieces, set_command=set_command, activities=_activities(paths))
    _log_problem(result)
    script = paths.config / "run-after-wp-change.py"
    if script.is_file():
        _log_problem(desktop.run_hook(script, str(image), source_files or []))
    return result.ok


def _activities(paths: AppPaths) -> Activities:
    """How KDE finds the wallpapers of the profiles its activities are named after."""
    return Activities(
        current_profile=G_ACTIVE_PROFILE,
        cached_pieces=lambda name: _cached_pieces(paths.cache, name),
        state_dir=paths.config,
    )


def _cached_pieces(cache_dir: Path, profile_name: str) -> list[str]:
    """The per-display images last rendered for the profile named ``profile_name``."""
    try:
        profile_id = ProfileId.parse(profile_name)
    except ProfileIdError:  # an activity name no profile can have
        return []
    rendered = render_cache.latest(render_cache.slot(cache_dir, profile_id))
    return [str(piece) for piece in rendered.pieces] if rendered else []


def _log_problem(result: Result) -> None:
    if not result.ok:
        sp_logging.G_LOGGER.error("%s", result.problem)


def _change_wallpaper(profile, force, advance, display_system: DisplaySystem, paths: AppPaths, set_command):
    """Choose ``profile``'s images, render them for ``display_system``, keep the render in
    the cache and show it.

    Unless ``force``, a profile that is no longer running is left alone: its slideshow can
    tick once more after another profile has started.
    """
    if not force and profile.name != G_ACTIVE_PROFILE:
        sp_logging.G_LOGGER.info("Wallpaper change skipped: profile '%s' is no longer running.", profile.name)
        return
    if (advance or not profile.has_valid_selection()) and not profile.advance_wallpaper():
        sp_logging.G_LOGGER.error("Wallpaper change skipped: profile '%s' has no complete selection.", profile.name)
        return
    files = profile.next_wallpaper_files()
    try:
        image = _render(profile, files, display_system)
    except render.SourceImageError as error:
        sp_logging.G_LOGGER.error("Wallpaper change skipped: %s", error)
        return
    if image is None:
        return
    try:
        output = render_cache.save(render_cache.slot(paths.cache, profile.profile_id), image)
    except OSError as error:
        sp_logging.G_LOGGER.error("Wallpaper change skipped: the wallpaper could not be saved: %s", error)
        return
    if set_wallpaper(output, files, display_system=display_system, paths=paths, set_command=set_command):
        # Until the desktop takes the new render, the previous one may still be on screen.
        render_cache.forget_previous(output)


def _render(profile, files, display_system: DisplaySystem):
    """Compose ``profile``'s desktop image from ``files``; None, with the reason logged, if
    they don't fit its span mode."""
    resolutions = display_system.resolutions()
    if profile.spanmode.startswith("multi"):
        if len(files) != len(resolutions):
            _log_incomplete(profile)
            return None
        return render.multi(files, display_system, zoom=profile.zoom, pan=profile.offsets)
    corrections = profile.display_corrections(resolutions)
    if profile.spanmode.startswith("single") and not corrections.ppimode:
        if len(files) != 1:
            _log_incomplete(profile)
            return None
        return render.simple(files[0], display_system, zoom=profile.zoom, pan=profile.offsets)
    # Advanced spanning, or a single image with legacy corrections (offsets=, ppi=, ...).
    if len(files) != (len(profile.spangroups) if profile.spangroups else 1):
        _log_incomplete(profile)
        return None
    perspective = display_system.get_persp_data(profile.perspective) if display_system.use_perspective else None
    return render.advanced(
        files,
        display_system,
        manual_offsets=corrections.manual_offsets,
        spangroups=profile.spangroups,
        perspective=perspective,
        zoom=profile.zoom,
        pan=profile.offsets,
    )


def _log_incomplete(profile) -> None:
    sp_logging.G_LOGGER.error("No complete wallpaper selection is available for profile '%s'.", profile.name)


def change_wallpaper_job(
    profile,
    paths: AppPaths,
    *,
    display_system: DisplaySystem,
    set_command="",
    force=False,
    advance=False,
    skip_if_busy=False,
):
    """Centralized wallpaper method that calls setter algorithm based on input prof settings.
    When force, skip the profile name check.
    When advance, cycle to the next image before rendering (slideshow / manual next).
    Otherwise the current persistent selection is rendered unchanged; if none has
    been established yet, the first image is picked once and saved as the selection.
    The wallpaper is rendered for ``display_system`` into ``paths.cache``;
    ``set_command`` is the user's own wallpaper setter command, if any.
    """
    if not (
        profile.spanmode.startswith("single")
        or profile.spanmode.startswith("advanced")
        or profile.spanmode.startswith("multi")
    ):
        sp_logging.G_LOGGER.info("Unkown profile spanmode: %s", profile.spanmode)
        return None
    gate_acquired = False
    if skip_if_busy:
        gate_acquired = G_WALLPAPER_CHANGE_PENDING.acquire(blocking=False)
        if not gate_acquired:
            sp_logging.G_LOGGER.info("Wallpaper change skipped because another change is pending.")
            return None

    def run_change():
        if not gate_acquired:
            G_WALLPAPER_CHANGE_PENDING.acquire()
        try:
            with G_WALLPAPER_CHANGE_LOCK:
                _change_wallpaper(profile, force, advance, display_system, paths, set_command)
        finally:
            G_WALLPAPER_CHANGE_PENDING.release()

    thrd = Thread(target=run_change, daemon=True)
    thrd.start()
    return thrd


def run_profile_job(profile, change, startup=False):
    """Start running ``profile``: set its wallpaper now and arm its slideshow.

    ``change(profile, advance=..., skip_if_busy=...)`` starts one wallpaper change; the
    slideshow timer calls it on every tick. When ``startup`` is True the wallpaper is not
    changed immediately: the currently shown wallpaper is kept and, for slideshow
    profiles, only the repeating timer is armed so cycling happens later on its own
    schedule instead of on every app launch.
    """
    repeating_timer = None
    thrd = None
    if sp_logging.DEBUG:
        sp_logging.G_LOGGER.info("running profile job with profile: %s", profile.name)

    if not startup:
        thrd = change(profile)
    if profile.slideshow:
        repeating_timer = RepeatedTimer(
            profile.delay_list[0],
            change,
            profile,
            advance=True,
            skip_if_busy=True,
        )
    return (repeating_timer, thrd)


def quick_profile_job(profile, *, display_system: DisplaySystem, paths: AppPaths, set_command="") -> bool:
    """Show the last wallpaper again at startup, without rendering anything.

    That is the last render of ``profile``, or a draft shown after it: the editor's Apply,
    the align test or the command line. Returns False if ``profile`` has no render to
    show, so that the caller can render it.
    """
    if profile.profile_id is None:
        return False
    rendered = render_cache.latest(render_cache.slot(paths.cache, profile.profile_id))
    if rendered is None:
        sp_logging.G_LOGGER.info("Profile '%s' has no earlier render to show.", profile.name)
        return False
    draft = render_cache.latest(render_cache.slot(paths.cache, None))
    if draft is not None and draft.modified > rendered.modified:
        rendered = draft

    def locked_setter(setter, *args, **kwargs):
        with G_WALLPAPER_CHANGE_PENDING, G_WALLPAPER_CHANGE_LOCK:
            setter(*args, **kwargs)

    # The setter worker takes the render lock, so the UI thread never blocks behind an
    # in-progress render.
    image = str(rendered.image)
    pieces = [str(piece) for piece in rendered.pieces]
    if desktop.takes_pieces(set_command) and pieces:
        sp_logging.G_LOGGER.info("Use wallpaper crop pieces: %s", pieces)
        setter, args, kwargs = _restore_pieces, (image, pieces), {"paths": paths, "set_command": set_command}
    elif IS_WINDOWS and not _windows_restores(profile, display_system):
        return True  # Windows keeps the wallpaper itself
    else:
        setter, args = set_wallpaper, (image,)
        kwargs = {"display_system": display_system, "paths": paths, "set_command": set_command}
    Thread(target=locked_setter, args=(setter, *args), kwargs=kwargs, daemon=True).start()
    return True


def _windows_restores(profile, display_system: DisplaySystem) -> bool:
    """Whether Windows gets the wallpaper again at startup: only a perspective render does."""
    if profile.spanmode != "advanced" or not display_system.use_perspective:
        return False
    if profile.perspective == "default":
        return display_system.default_perspective is not None
    return profile.perspective != "disabled"


def _restore_pieces(image, pieces, *, paths: AppPaths, set_command):
    """Show the per-display images last rendered, on a desktop that takes those."""
    _log_problem(desktop.set_wallpaper(image, pieces, set_command=set_command, activities=_activities(paths)))
