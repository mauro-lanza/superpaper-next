"""The runtime: which profile runs, its slideshow, and every wallpaper change.

A Session does all of it on one worker thread, one request at a time, in the order they
were made: starting a profile, the next image, pause, a draft, a new display layout.
Callers only post requests, so the tray, its menus, the hotkeys and the editor never wait
for a render. The slideshow's next change is the deadline of the worker's wait for the
next request, so a slideshow that stopped has no timer left that could fire.

The worker never detects displays: the caller detects them, on the main thread, and hands
the layout over. The X library that display detection uses on Linux (libXrandr) corrupts
memory when two threads use it at once, and GTK uses it on the main thread.

Each change itself is superpaper.wallpaper_change.show().
"""

import logging
import queue
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from superpaper.paths import AppPaths
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId
from superpaper.profiles.profile_store import write_active_profile
from superpaper.wallpaper_change import show, show_again

if TYPE_CHECKING:
    from superpaper.geometry.displays import Layout
    from superpaper.profiles.profile_store import StoredProfile

logger = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT = 5.0
"""How long quitting waits for a wallpaper change under way, in seconds."""


@dataclass(frozen=True)
class _Next:
    """A request for the next image, which the worker merges with the ones right after it."""


_NEXT = _Next()


class Session:
    """The running profile and its slideshow, kept by one worker thread.

    ``layout`` is the display layout to render for until use_displays() hands over another.
    A Layout never changes, so the worker and the callers that hand one over can't disturb
    each other: a change under way keeps the layout it began with.
    ``set_command`` gives the user's own wallpaper setter command as currently set, so a
    changed setting applies from the next change on. ``clock`` times the slideshow.
    ``on_change(problem)`` is called on the worker thread after each change of the running
    profile (slideshow, next, start), with what went wrong, or None.

    ``running``, ``paused`` and ``layout`` say how things stand once the requests
    made so far are handled; only the worker changes them.
    """

    def __init__(
        self,
        paths: AppPaths,
        layout: Layout,
        *,
        on_change: Callable[[str | None], None],
        set_command: Callable[[], str] = lambda: "",
        clock: Callable[[], float] = time.monotonic,
    ):
        self._paths = paths
        self._on_change = on_change
        self._set_command = set_command
        self._clock = clock
        self._requests: queue.SimpleQueue[Callable[[], None] | _Next | None] = queue.SimpleQueue()
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
        self._post(_NEXT)

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

    def wait_until_handled(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds until every request made so far is handled, and a
        slideshow change that is due has run; whether it was."""
        handled = threading.Event()
        self._post(lambda: None)  # the worker looks for a due change after each request
        self._post(handled.set)
        return handled.wait(timeout)

    def shutdown(self, timeout: float = SHUTDOWN_TIMEOUT) -> None:
        """Stop: requests not handled yet are dropped, and later ones refused. Waits up to
        ``timeout`` seconds for a change under way; one that takes longer is abandoned."""
        self._closed = True
        self._requests.put(None)  # wakes the worker
        self._worker.join(timeout)
        if self._worker.is_alive():
            logger.info("Quitting while a wallpaper change is still under way.")

    def _post(self, request: Callable[[], None] | _Next) -> bool:
        if self._closed:
            logger.info("Superpaper is quitting; the request is dropped.")
            return False
        self._requests.put(request)
        return True

    def _serve(self) -> None:
        """Handle requests as they come, and the slideshow's change whenever it is due."""
        carried: Callable[[], None] | _Next | None = None
        while not self._closed:
            if carried is not None:
                request, carried = carried, None
            else:
                try:
                    request = self._requests.get(timeout=self._until_due())
                except queue.Empty:
                    request = None
            if self._closed:
                return
            if isinstance(request, _Next):
                presses = 1
                # Mashing Next moves the position once per press but renders only the last.
                while True:
                    try:
                        following = self._requests.get_nowait()
                    except queue.Empty:
                        break
                    if not isinstance(following, _Next):
                        carried = following
                        break
                    presses += 1
                _handle(partial(self._change, steps=presses))
            elif request is not None:
                _handle(request)
            if not self._closed and self._deadline is not None and self._clock() >= self._deadline:
                _handle(lambda: self._change(steps=1))

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
            self._change(steps=0)

    def _activate(self, stored: StoredProfile) -> None:
        running = self._running
        if running is not None and running.profile_id == stored.profile_id:
            self._running = stored
            self._change(steps=1)
            return
        self._running = stored
        self._paused = False
        logger.info("Starting profile: %s", stored.profile.name)
        try:
            write_active_profile(self._paths.cache, stored.profile_id)
        except OSError as error:
            logger.warning("Could not remember the running profile: %s", error)
        self._change(steps=0)

    def _change(self, *, steps: int) -> None:
        """Show the running profile's current images, or with ``steps`` its images that many
        positions on, rendering only the last; its slideshow changes next one delay from now."""
        stored = self._running
        if stored is None:
            logger.info("No profile is running.")
            return
        self._arm()
        selection = stored.selection
        for _ in range(steps - 1):
            selection.advance()
        files = selection.advance() if steps or not selection.is_complete() else selection.current()
        if not files:
            problem = f"profile '{stored.profile.name}' has no complete selection."
            logger.error("Wallpaper change skipped: %s", problem)
            self._on_change(problem)
            return
        problem = show(
            stored.profile,
            files,
            self._paths,
            layout=self._layout,
            set_command=self._set_command(),
            profile_id=stored.profile_id,
            running=stored.profile.name,
        )
        self._on_change(problem)

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
