"""The runtime: which profile runs, its slideshow, and every wallpaper change.

A Session does all of it on one worker thread, one request at a time, in the order they
were made: starting a profile, the next image, pause, a draft, a new display layout.
Callers only post requests, so the tray, its menus, the hotkeys and the editor never wait
for a render. The slideshow's next change is the deadline of the worker's wait for the
next request, so a slideshow that stopped has no timer left that could fire.

The worker never detects displays: the caller detects them, on the main thread, and hands
the layout over. The X library that display detection uses on Linux (libXrandr) corrupts
memory when two threads use it at once, and GTK uses it on the main thread.

One wallpaper change is show(), which the command line runs directly: it renders images
for the display layout (superpaper.rendering.render), keeps the render (superpaper.rendering.render_cache)
and hands it to the desktop (superpaper.desktop).
"""

import logging
import queue
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

import superpaper.desktop as desktop
import superpaper.rendering.render as render
from superpaper.desktop.kde import Activities
from superpaper.desktop.process import Result
from superpaper.desktop.wallpaper import Pieces, Spanned, Wallpaper
from superpaper.geometry.perspective import Default, Disabled, Named
from superpaper.paths import AppPaths
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId, ProfileIdError
from superpaper.profiles.profile_store import write_active_profile
from superpaper.rendering import render_cache

if TYPE_CHECKING:
    from PIL import Image

    from superpaper.geometry.displays import Layout
    from superpaper.profiles.profile_store import StoredProfile

logger = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT = 5.0
"""How long quitting waits for a wallpaper change under way, in seconds."""


class Session:
    """The running profile and its slideshow, kept by one worker thread.

    ``layout`` is the display layout to render for until use_displays() hands over another.
    A Layout never changes, so the worker and the callers that hand one over can't disturb
    each other: a change under way keeps the layout it began with.
    ``set_command`` gives the user's own wallpaper setter command as currently set, so a
    changed setting applies from the next change on. ``clock`` times the slideshow.

    ``running``, ``paused`` and ``layout`` say how things stand once the requests
    made so far are handled; only the worker changes them.
    """

    def __init__(
        self,
        paths: AppPaths,
        layout: Layout,
        *,
        set_command: Callable[[], str] = lambda: "",
        clock: Callable[[], float] = time.monotonic,
    ):
        self._paths = paths
        self._set_command = set_command
        self._clock = clock
        self._requests: queue.SimpleQueue[Callable[[], None] | None] = queue.SimpleQueue()
        self._closed = False
        self._running: StoredProfile | None = None
        self._paused = False
        self._deadline: float | None = None
        self._layout = layout
        self._worker = threading.Thread(target=self._serve, name="superpaper-session", daemon=True)
        self._worker.start()

    @property
    def running(self) -> StoredProfile | None:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def layout(self) -> Layout:
        return self._layout

    def renames_running(self, profile_id: ProfileId | None, new_name: str) -> bool:
        """Whether saving the profile ``profile_id`` (None for a new one) as ``new_name``
        renames the running profile."""
        running = self._running
        return (
            running is not None
            and profile_id is not None
            and running.profile_id == profile_id
            and new_name != profile_id.value
        )

    def restore(self, stored: StoredProfile) -> None:
        """Carry on with ``stored``, the profile that ran when Superpaper last exited: show
        its last wallpaper again, or render it if there is none, and start its slideshow."""
        self._post(lambda: self._restore(stored))

    def activate(self, stored: StoredProfile) -> None:
        """Run the saved profile ``stored``: render it now and start its slideshow,
        unpaused; it is remembered for the next start. If it runs already, show its next
        image instead."""
        self._post(lambda: self._activate(stored))

    def next(self) -> None:
        """Show the running profile's next image now; its slideshow counts down from here."""
        self._post(lambda: self._change(advance=True))

    def toggle_pause(self) -> None:
        """Pause the running profile's slideshow, or resume it."""
        self._post(self._toggle_pause)

    def update(self, profile_id: ProfileId, stored: StoredProfile | None) -> None:
        """The saved profile ``profile_id`` is now ``stored``: saved again, maybe under a
        new name, or None once deleted.

        If it is running, it carries on with ``stored``: the wallpaper stays, and its
        slideshow counts down from now with the new settings, still paused if it was. A
        deleted profile stops.
        """
        self._post(lambda: self._update(profile_id, stored))

    def use_displays(self, layout: Layout) -> None:
        """Render the changes after this one for ``layout``: the displays as just
        detected, with their saved layout."""
        self._post(lambda: self._use_displays(layout))

    def apply_draft(
        self,
        profile: Profile,
        images: Sequence[str],
        *,
        layout: Layout | None = None,
        on_done: Callable[[str | None], None] | None = None,
    ) -> None:
        """Show ``images`` with ``profile``'s settings, which aren't a running profile's,
        such as the editor's unsaved ones or an align test's. The render is kept as a
        draft, and no slideshow moves on.

        ``layout`` renders for another layout than the session's, such as the
        editor's unsaved one. ``on_done(problem)`` is called on the worker thread when the
        draft has been shown, with what went wrong, or None.
        """
        images = list(images)

        def draft():
            problem = "The wallpaper could not be shown."  # if show() fails unexpectedly
            try:
                problem = show(
                    profile,
                    images,
                    self._paths,
                    layout=layout if layout is not None else self._layout,
                    set_command=self._set_command(),
                    running=self._running.profile.name if self._running is not None else None,
                )
            finally:
                if on_done is not None:
                    on_done(problem)

        if not self._post(draft) and on_done is not None:
            on_done("Superpaper is quitting.")

    def shutdown(self, timeout: float = SHUTDOWN_TIMEOUT) -> None:
        """Stop: requests not handled yet are dropped, and later ones refused. Waits up to
        ``timeout`` seconds for a change under way; one that takes longer is abandoned."""
        self._closed = True
        self._requests.put(None)  # wakes the worker
        self._worker.join(timeout)
        if self._worker.is_alive():
            logger.info("Quitting while a wallpaper change is still under way.")

    def _post(self, request: Callable[[], None]) -> bool:
        if self._closed:
            logger.info("Superpaper is quitting; the request is dropped.")
            return False
        self._requests.put(request)
        return True

    def _serve(self) -> None:
        """Handle requests as they come, and the slideshow's change whenever it is due."""
        while not self._closed:
            try:
                request = self._requests.get(timeout=self._until_due())
            except queue.Empty:
                request = None
            if self._closed:
                return
            if request is not None:
                _handle(request)
            if not self._closed and self._deadline is not None and self._clock() >= self._deadline:
                _handle(lambda: self._change(advance=True))

    def _until_due(self) -> float | None:
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - self._clock())

    def _restore(self, stored: StoredProfile) -> None:
        self._running = stored
        self._paused = False
        logger.info("Running profile: %s", stored.profile.name)
        if show_again(stored, self._paths, layout=self._layout, set_command=self._set_command()):
            self._arm()
        else:
            self._change(advance=False)

    def _activate(self, stored: StoredProfile) -> None:
        running = self._running
        if running is not None and running.profile_id == stored.profile_id:
            self._running = stored
            self._change(advance=True)
            return
        self._running = stored
        self._paused = False
        logger.info("Starting profile: %s", stored.profile.name)
        try:
            write_active_profile(self._paths.cache, stored.profile_id)
        except OSError as error:
            logger.warning("Could not remember the running profile: %s", error)
        self._change(advance=False)

    def _change(self, *, advance: bool) -> None:
        """Show the running profile's current images, or with ``advance`` its next ones;
        its slideshow changes next one delay from now."""
        stored = self._running
        if stored is None:
            logger.info("No profile is running.")
            return
        self._arm()
        selection = stored.selection
        files = selection.advance() if advance or not selection.is_complete() else selection.current()
        if not files:
            logger.error("Wallpaper change skipped: profile '%s' has no complete selection.", stored.profile.name)
            return
        show(
            stored.profile,
            files,
            self._paths,
            layout=self._layout,
            set_command=self._set_command(),
            profile_id=stored.profile_id,
            running=stored.profile.name,
        )

    def _arm(self) -> None:
        """Set when the slideshow changes next: one delay from now, or never while it is
        paused or the running profile isn't a slideshow."""
        stored = self._running
        if stored is None or not stored.profile.slideshow or self._paused:
            self._deadline = None
        else:
            self._deadline = self._clock() + stored.profile.delay

    def _toggle_pause(self) -> None:
        stored = self._running
        if stored is None or not stored.profile.slideshow:
            logger.info("The running profile isn't a slideshow.")
            return
        self._paused = not self._paused
        self._arm()
        logger.info("Slideshow %s.", "paused" if self._paused else "resumed")

    def _update(self, profile_id: ProfileId, stored: StoredProfile | None) -> None:
        running = self._running
        if running is None or running.profile_id != profile_id or stored is running:
            return
        self._running = stored
        if stored is None:
            logger.info("The running profile '%s' was deleted; its slideshow stops.", profile_id.value)
        if stored is None or not stored.profile.slideshow:
            self._paused = False
        self._arm()

    def _use_displays(self, layout: Layout) -> None:
        self._layout = layout


def _handle(request: Callable[[], None]) -> None:
    """Run one request; a bug in it is logged, and the worker carries on."""
    try:
        request()
    except Exception:
        logger.exception("A wallpaper change failed unexpectedly.")


def show(
    profile: Profile,
    files: Sequence[str],
    paths: AppPaths,
    *,
    layout: Layout,
    set_command: str = "",
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
    except render.SourceImageError as error:
        return _skipped(str(error))
    if image is None:
        return _skipped(f"No complete wallpaper selection is available for profile '{profile.name}'.")
    try:
        slot = (
            render_cache.draft_slot(paths.cache)
            if profile_id is None
            else render_cache.slot(paths.cache, profile_id.value)
        )
        output = render_cache.save(slot, image)
    except OSError as error:
        return _skipped(f"The wallpaper could not be saved: {error}")
    result = set_wallpaper(output, files, layout=layout, paths=paths, set_command=set_command, running=running)
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
    result = desktop.set_wallpaper(wallpaper, set_command=set_command, activities=_activities(paths, running))
    _log_problem(result)
    script = paths.config / "run-after-wp-change.py"
    if script.is_file():
        _log_problem(desktop.run_hook(script, str(image), list(source_files)))
    return result


def show_again(stored: StoredProfile, paths: AppPaths, *, layout: Layout, set_command="") -> bool:
    """Show the last wallpaper again at startup, without rendering anything.

    That is the last render of the profile ``stored``, or a draft shown after it: the
    editor's Apply, an align test or the command line. Returns False if the profile has
    no render to show, so that it can be rendered.
    """
    rendered = render_cache.latest(render_cache.slot(paths.cache, stored.profile_id.value))
    if rendered is None:
        logger.info("Profile '%s' has no earlier render to show.", stored.profile.name)
        return False
    draft = render_cache.latest(render_cache.draft_slot(paths.cache))
    if draft is not None and draft.modified > rendered.modified:
        rendered = draft
    image = str(rendered.image)
    running = stored.profile.name
    if desktop.takes_pieces(set_command) and rendered.pieces:
        pieces = tuple(str(piece) for piece in rendered.pieces)
        logger.info("Use wallpaper crop pieces: %s", pieces)
        _log_problem(
            desktop.set_wallpaper(
                Pieces(image, pieces), set_command=set_command, activities=_activities(paths, running)
            )
        )
    elif desktop.keeps_wallpaper() and not _is_perspective_render(stored.profile, layout):
        pass
    else:
        set_wallpaper(image, layout=layout, paths=paths, set_command=set_command, running=running)
    return True


def _is_perspective_render(profile: Profile, layout: Layout) -> bool:
    """Whether the render is a perspective one, which a desktop that keeps its wallpaper
    still gets again at startup."""
    if profile.spanmode != "advanced" or not layout.use_perspective:
        return False
    match profile.perspective:
        case Default():
            return layout.default_perspective is not None
        case Disabled():
            return False
        case Named():
            return True
        case _:
            assert_never(profile.perspective)


def _activities(paths: AppPaths, running: str | None) -> Activities:
    """How KDE finds the wallpapers of the profiles its activities are named after."""
    return Activities(
        current_profile=running,
        cached_pieces=lambda name: _cached_pieces(paths.cache, name),
        state_dir=paths.config,
    )


def _cached_pieces(cache_dir: Path, profile_name: str) -> list[str]:
    """The per-display images last rendered for the profile named ``profile_name``."""
    try:
        profile_id = ProfileId.parse(profile_name)
    except ProfileIdError:  # an activity name no profile can have
        return []
    rendered = render_cache.latest(render_cache.slot(cache_dir, profile_id.value))
    return [str(piece) for piece in rendered.pieces] if rendered else []


def _log_problem(result: Result) -> None:
    if not result.ok:
        logger.error("%s", result.problem)
