"""The runtime: one worker runs every request, in the order they were made, and the
slideshow when it is due; once something stops, nothing makes it change the wallpaper.

A fake clock times the slideshow. Each change is recorded instead of rendered, as the
images it would show: a profile named "A" shows A-1.png, then A-2.png, and so on.
"""

import threading
import time
from types import SimpleNamespace

import pytest

from superpaper import session as session_module
from superpaper.geometry import display_detection
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId
from superpaper.session import Session
from tests.desktop.fake import FakeDesktop

DELAY = 600.0


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Numbered:
    """A selection that moves through images numbered from 1."""

    def __init__(self, name):
        self.name = name
        self.number = 1
        self.pinned = None
        self.vanished = []
        self.drops = {}

    def take_skipped(self):
        skipped, self.vanished = self.vanished, []
        return skipped

    def pin(self, files):
        self.pinned = list(files)

    def is_complete(self):
        return True

    def current(self):
        return [f"{self.name}-{self.number}.png"]

    def advance(self):
        self.number += 1
        self.vanished = self.drops.get(self.number, [])
        return self.current()


def saved(name, *, slideshow=True, delay=DELAY):
    """A saved profile, as the session is handed it."""
    return SimpleNamespace(
        profile_id=ProfileId.parse(name, windows_names=False),
        profile=Profile(name=name, slideshow=slideshow, delay=delay),
        selection=Numbered(name),
    )


class Runtime:
    """A session, the clock that times it, and what it showed."""

    def __init__(self, monkeypatch, paths):
        self.paths = paths
        self.clock = Clock()
        self.changes = []
        self.reported = []
        self.running_changes = []
        self.restored = []
        self.has_render = True
        self.problem = None
        self.skipped = []
        self.set_command = "first {image}"
        self.hold = None
        self.holding = threading.Event()
        monkeypatch.setattr(session_module, "show", self.show)
        monkeypatch.setattr(session_module, "show_again", self.show_again)
        self.session = Session(
            paths,
            FakeDesktop(),
            "layout 0",
            on_change=self.reported.append,
            on_skipped=self.skipped.append,
            on_running_change=lambda: self.running_changes.append(self.session.running),
            set_command=lambda: self.set_command,
            clock=self.clock,
        )

    def show(self, profile, files, paths, *, desktop, layout, set_command="", profile_id=None, running=None):
        if self.hold is not None:
            self.holding.set()
            assert self.hold.wait(10)
        self.changes.append(
            SimpleNamespace(
                image=files[0],
                profile_id=profile_id,
                layout=layout,
                set_command=set_command,
                running=running,
            )
        )
        return self.problem

    def show_again(self, stored, paths, *, desktop, layout, set_command=""):
        self.restored.append(stored.profile.name)
        return self.has_render

    @property
    def shown(self):
        return [change.image for change in self.changes]

    def advance(self, seconds):
        """Let ``seconds`` pass once the requests made so far are handled."""
        self.settle()
        self.clock.now += seconds

    def settle(self):
        """Wait until every request made so far is handled, and the slideshow change that
        came due on the fake clock."""
        assert self.session.wait_until_handled(10)

    def hold_changes(self):
        """Make the next changes wait until release()."""
        self.hold = threading.Event()
        self.holding.clear()

    def release(self):
        hold, self.hold = self.hold, None
        hold.set()


@pytest.fixture
def runtime(monkeypatch, app_paths):
    runtime = Runtime(monkeypatch, app_paths)
    yield runtime
    if runtime.hold is not None:
        runtime.release()
    runtime.session.shutdown(timeout=5)


def test_a_started_profile_is_shown_and_remembered(runtime):
    runtime.session.activate(saved("A"))
    runtime.settle()

    assert runtime.shown == ["A-1.png"]
    assert runtime.changes[0].layout == "layout 0"
    assert runtime.changes[0].profile_id == ProfileId.parse("A", windows_names=False)
    assert runtime.session.running.profile_id == ProfileId.parse("A", windows_names=False)
    assert (runtime.paths.cache / "running_profile").read_text(encoding="utf-8") == "A"


def test_each_change_reports_its_problem_or_none(runtime):
    runtime.problem = "Image missing"
    runtime.session.activate(saved("A"))
    runtime.settle()
    runtime.problem = None
    runtime.session.next()
    runtime.settle()

    assert runtime.reported == ["Image missing", None]


def test_images_the_selection_skipped_are_reported_once_per_change(runtime):
    stored = saved("A")
    stored.selection.drops = {2: ["gone.png"]}
    runtime.session.activate(stored)
    runtime.settle()
    runtime.session.next()
    runtime.settle()

    assert runtime.shown == ["A-1.png", "A-2.png"]
    assert runtime.reported == [None, None]
    assert runtime.skipped == [["gone.png"]]


def test_a_change_stops_when_the_selection_has_no_images_left(runtime):
    class Emptied(Numbered):
        def advance(self):
            return []

    stored = saved("A")
    stored.selection = Emptied("A")
    runtime.session.activate(stored)
    runtime.session.next()
    runtime.settle()

    assert runtime.reported == [None, "profile 'A' has no complete selection."]
    assert runtime.skipped == []


def test_starting_the_running_profile_again_keeps_an_unpaused_countdown_as_it_is(runtime):
    a = saved("A")
    runtime.session.activate(a)
    runtime.advance(DELAY / 2)
    runtime.session.activate(a)
    runtime.advance(DELAY / 2)
    runtime.settle()

    assert runtime.shown == ["A-1.png", "A-2.png"]


def test_starting_the_running_profile_again_changes_nothing_but_unpauses_and_restarts_the_countdown(runtime):
    a = saved("A")
    runtime.session.activate(a)
    runtime.session.toggle_pause()
    runtime.advance(DELAY / 2)
    runtime.session.activate(a)
    runtime.advance(DELAY - 1)
    runtime.settle()

    assert runtime.shown == ["A-1.png"]
    assert runtime.session.paused is False
    assert a.selection.number == 1

    runtime.advance(1)
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-2.png"]


def test_applying_a_profile_shows_the_picked_image_and_remembers_it(runtime):
    a = saved("A")
    runtime.session.apply(a, ["pick.png"])
    runtime.settle()

    assert a.selection.pinned == ["pick.png"]
    assert runtime.shown == ["A-1.png"]
    assert runtime.session.running is a
    assert (runtime.paths.cache / "running_profile").read_text(encoding="utf-8") == "A"


def test_every_change_of_the_running_profile_is_reported(runtime):
    a, b = saved("A"), saved("B")
    runtime.session.restore(a)
    runtime.session.activate(b)
    runtime.session.activate(b)
    runtime.session.apply(a, None)
    runtime.session.update(ProfileId.parse("A", windows_names=False), saved("A"))
    runtime.session.update(ProfileId.parse("A", windows_names=False), None)
    runtime.session.update(ProfileId.parse("Z", windows_names=False), None)
    runtime.settle()

    assert [stored.profile.name if stored else None for stored in runtime.running_changes] == [
        "A",
        "B",
        "B",
        "A",
        "A",
        None,
    ]


def test_applying_without_a_pick_shows_the_current_image(runtime):
    a = saved("A")
    runtime.session.apply(a, None)
    runtime.settle()

    assert a.selection.pinned is None
    assert runtime.shown == ["A-1.png"]


def test_applying_the_running_profile_shows_its_current_image_unpauses_and_restarts_the_countdown(runtime):
    a = saved("A")
    runtime.session.activate(a)
    runtime.session.toggle_pause()
    runtime.advance(DELAY / 2)
    runtime.session.apply(a, None)
    runtime.advance(DELAY - 1)
    runtime.settle()

    assert runtime.shown == ["A-1.png", "A-1.png"]
    assert runtime.session.paused is False

    runtime.advance(1)
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-1.png", "A-2.png"]


def test_requests_are_handled_in_the_order_they_were_made(runtime):
    runtime.session.activate(saved("A"))
    runtime.session.next()
    runtime.session.activate(saved("B"))
    runtime.session.next()
    runtime.settle()

    # A profile started before a request is the one the request acts on.
    assert runtime.shown == ["A-1.png", "A-2.png", "B-1.png", "B-2.png"]


def test_consecutive_nexts_render_once_and_move_on_each_time(runtime):
    a = saved("A")
    runtime.hold_changes()
    runtime.session.activate(a)
    assert runtime.holding.wait(10)
    for _ in range(3):
        runtime.session.next()
    runtime.release()
    runtime.settle()

    assert runtime.shown == ["A-1.png", "A-4.png"]
    assert a.selection.number == 4


def test_a_request_between_nexts_keeps_its_place(runtime):
    runtime.hold_changes()
    runtime.session.activate(saved("A"))
    assert runtime.holding.wait(10)
    runtime.session.next()
    runtime.session.next()
    runtime.session.activate(saved("B"))
    runtime.session.next()
    runtime.release()
    runtime.settle()

    assert runtime.shown == ["A-1.png", "A-3.png", "B-1.png", "B-2.png"]


def test_requests_never_wait_for_a_change_under_way(runtime):
    runtime.hold_changes()
    runtime.session.activate(saved("A"))
    assert runtime.holding.wait(10)

    started = time.monotonic()
    runtime.session.next()
    runtime.session.toggle_pause()
    runtime.session.use_displays("layout 1")
    runtime.session.apply_draft(Profile(name="draft"), ["draft.png"])
    assert time.monotonic() - started < 1

    runtime.release()
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-2.png", "draft.png"]


def test_the_slideshow_changes_each_time_its_delay_has_passed(runtime):
    runtime.session.activate(saved("A"))
    runtime.advance(DELAY - 1)
    runtime.settle()
    assert runtime.shown == ["A-1.png"]

    runtime.advance(1)
    runtime.settle()
    runtime.advance(DELAY)
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-2.png", "A-3.png"]


def test_next_starts_the_countdown_again(runtime):
    runtime.session.activate(saved("A"))
    runtime.advance(DELAY / 2)
    runtime.session.next()
    runtime.advance(DELAY / 2)
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-2.png"]

    runtime.advance(DELAY / 2)
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-2.png", "A-3.png"]


def test_slideshow_changes_never_pile_up_behind_a_slow_one(runtime):
    runtime.session.activate(saved("A"))
    runtime.settle()
    runtime.hold_changes()
    runtime.advance(DELAY)
    runtime.session.use_displays(runtime.session.layout)  # wakes the worker to find the change due
    assert runtime.holding.wait(10)

    # Ten delays pass while that change is under way.
    runtime.clock.now += 10 * DELAY
    runtime.release()
    runtime.settle()

    assert runtime.shown == ["A-1.png", "A-2.png", "A-3.png"]


def test_a_paused_slideshow_changes_only_when_asked_to(runtime):
    runtime.session.activate(saved("A"))
    runtime.session.toggle_pause()
    runtime.advance(100 * DELAY)
    runtime.settle()
    assert runtime.shown == ["A-1.png"]
    assert runtime.session.paused is True

    runtime.session.next()
    runtime.advance(100 * DELAY)
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-2.png"]
    assert runtime.session.paused is True


def test_resuming_counts_down_a_whole_delay(runtime):
    runtime.session.activate(saved("A"))
    runtime.session.toggle_pause()
    runtime.advance(DELAY / 2)
    runtime.session.toggle_pause()
    runtime.advance(DELAY - 1)
    runtime.settle()
    assert runtime.shown == ["A-1.png"]

    runtime.advance(1)
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-2.png"]
    assert runtime.session.paused is False


def test_only_a_slideshow_can_be_paused(runtime):
    runtime.session.activate(saved("A", slideshow=False))
    runtime.session.toggle_pause()
    runtime.advance(100 * DELAY)
    runtime.settle()

    assert runtime.session.paused is False
    assert runtime.shown == ["A-1.png"]


def test_starting_another_profile_runs_it_even_when_paused(runtime):
    runtime.session.activate(saved("A"))
    runtime.session.toggle_pause()
    runtime.session.activate(saved("B"))
    runtime.advance(DELAY)
    runtime.settle()

    assert runtime.session.paused is False
    assert runtime.shown == ["A-1.png", "B-1.png", "B-2.png"]


def test_a_profile_that_stopped_running_never_changes_again(runtime):
    a = saved("A")
    runtime.session.activate(a)
    runtime.advance(DELAY / 2)
    runtime.session.activate(saved("B"))
    runtime.advance(10 * DELAY)
    runtime.settle()

    assert a.selection.number == 1
    assert runtime.shown == ["A-1.png", "B-1.png", "B-2.png"]


def test_saving_the_running_profile_keeps_its_countdown_and_uses_the_new_delay_at_the_next_change(runtime):
    runtime.session.activate(saved("A"))
    runtime.advance(DELAY / 2)
    edited = saved("A", delay=2 * DELAY)
    runtime.session.update(ProfileId.parse("A", windows_names=False), edited)
    runtime.advance(DELAY / 2 - 1)
    runtime.settle()
    assert runtime.shown == ["A-1.png"]
    assert runtime.session.running is edited

    runtime.advance(1)
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-2.png"]

    runtime.advance(2 * DELAY - 1)
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-2.png"]

    runtime.advance(1)
    runtime.settle()
    assert runtime.shown == ["A-1.png", "A-2.png", "A-3.png"]


def test_saving_a_still_profile_as_a_slideshow_starts_its_countdown(runtime):
    runtime.session.activate(saved("A", slideshow=False))
    runtime.session.update(ProfileId.parse("A", windows_names=False), saved("A"))
    runtime.advance(DELAY)
    runtime.settle()

    assert runtime.shown == ["A-1.png", "A-2.png"]


def test_a_paused_slideshow_stays_paused_when_its_profile_is_saved(runtime):
    runtime.session.activate(saved("A"))
    runtime.session.toggle_pause()
    runtime.session.update(ProfileId.parse("A", windows_names=False), saved("A"))
    runtime.advance(100 * DELAY)
    runtime.settle()

    assert runtime.session.paused is True
    assert runtime.shown == ["A-1.png"]


def test_an_unchanged_profile_keeps_its_countdown(runtime):
    a = saved("A")
    runtime.session.activate(a)
    runtime.advance(DELAY / 2)
    runtime.session.update(ProfileId.parse("A", windows_names=False), a)
    runtime.advance(DELAY / 2)
    runtime.settle()

    assert runtime.shown == ["A-1.png", "A-2.png"]


def test_a_renamed_profile_keeps_running_under_its_new_name(runtime):
    runtime.session.activate(saved("A"))
    renamed = saved("B")
    runtime.session.update(ProfileId.parse("A", windows_names=False), renamed)
    # Reloading the profiles then finds no "A": that no longer concerns the running profile.
    runtime.session.update(ProfileId.parse("A", windows_names=False), None)
    runtime.advance(DELAY)
    runtime.settle()

    assert runtime.session.running is renamed
    assert runtime.shown == ["A-1.png", "B-2.png"]


@pytest.mark.parametrize(
    ("saved_as", "new_name", "renames"),
    [("A", "B", True), ("A", "A", False), ("Other", "B", False), (None, "B", False)],
)
def test_only_renaming_the_running_profile_is_a_rename_of_it(runtime, saved_as, new_name, renames):
    runtime.session.activate(saved("A"))
    runtime.settle()

    profile_id = ProfileId.parse(saved_as, windows_names=False) if saved_as else None
    assert runtime.session.renames_running(profile_id, new_name) is renames


def test_nothing_is_renamed_when_no_profile_runs(runtime):
    assert runtime.session.renames_running(ProfileId.parse("A", windows_names=False), "B") is False


def test_a_deleted_profile_stops(runtime):
    runtime.session.activate(saved("A"))
    runtime.session.toggle_pause()
    runtime.session.update(ProfileId.parse("A", windows_names=False), None)
    runtime.session.next()
    runtime.advance(100 * DELAY)
    runtime.settle()

    assert runtime.session.running is None
    assert runtime.session.paused is False
    assert runtime.shown == ["A-1.png"]
    assert not (runtime.paths.cache / "running_profile").exists()


def test_updating_a_profile_that_isnt_running_changes_nothing(runtime):
    a = saved("A")
    runtime.session.activate(a)
    runtime.session.update(ProfileId.parse("B", windows_names=False), None)
    runtime.settle()

    assert runtime.session.running is a


def test_the_last_wallpaper_is_shown_again_at_startup(runtime):
    runtime.session.restore(saved("A"))
    runtime.settle()
    assert runtime.restored == ["A"]
    assert runtime.shown == []
    # The profile isn't remembered again: it is the one remembered.
    assert not (runtime.paths.cache / "running_profile").exists()

    runtime.advance(DELAY)
    runtime.settle()
    assert runtime.shown == ["A-2.png"]


def test_a_profile_without_an_earlier_render_is_rendered_at_startup(runtime):
    runtime.has_render = False
    runtime.session.restore(saved("A"))
    runtime.settle()

    # Its current image, without moving on.
    assert runtime.shown == ["A-1.png"]


def test_a_profile_without_a_complete_selection_is_left_alone(runtime, caplog):
    empty = saved("A")
    empty.selection = SimpleNamespace(is_complete=lambda: False, advance=list, take_skipped=list)
    runtime.session.activate(empty)
    runtime.settle()

    assert runtime.shown == []
    assert runtime.reported == ["profile 'A' has no complete selection."]
    assert "Wallpaper change skipped: profile 'A' has no complete selection." in caplog.text


def test_redrawing_shows_the_current_image_for_the_new_layout_and_leaves_the_countdown_and_pause(runtime):
    runtime.session.activate(saved("A"))
    runtime.advance(DELAY / 2)
    runtime.session.use_displays("layout 1")
    runtime.session.redraw()
    runtime.advance(DELAY / 2)
    runtime.settle()

    assert [(change.image, change.layout) for change in runtime.changes] == [
        ("A-1.png", "layout 0"),
        ("A-1.png", "layout 1"),
        ("A-2.png", "layout 1"),
    ]


def test_redrawing_while_paused_stays_paused(runtime):
    a = saved("A")
    runtime.session.activate(a)
    runtime.session.toggle_pause()
    runtime.session.redraw()
    runtime.advance(10 * DELAY)
    runtime.settle()

    assert runtime.shown == ["A-1.png", "A-1.png"]
    assert runtime.session.paused is True
    assert a.selection.number == 1


def test_redrawing_with_nothing_running_shows_nothing(runtime):
    runtime.session.redraw()
    runtime.settle()

    assert runtime.shown == []


def test_a_draft_pauses_the_running_slideshow_so_no_tick_replaces_it(runtime):
    runtime.session.activate(saved("A"))
    runtime.session.apply_draft(Profile(name="align test"), ["test.png"])
    runtime.advance(10 * DELAY)
    runtime.settle()

    assert runtime.shown == ["A-1.png", "test.png"]
    assert runtime.session.paused is True


@pytest.mark.parametrize(
    ("leave", "after_a_delay", "paused"),
    [
        (lambda session, a: session.toggle_pause(), ["A-1.png", "test.png", "A-2.png"], False),
        (lambda session, a: session.next(), ["A-1.png", "test.png", "A-2.png"], True),
        (lambda session, a: session.apply(a, None), ["A-1.png", "test.png", "A-1.png", "A-2.png"], False),
        (lambda session, a: session.activate(a), ["A-1.png", "test.png", "A-2.png"], False),
    ],
    ids=["unpause", "next", "apply", "tray pick"],
)
def test_a_test_ends_with_unpause_next_apply_or_a_tray_pick(runtime, leave, after_a_delay, paused):
    a = saved("A")
    runtime.session.activate(a)
    runtime.session.apply_draft(Profile(name="align test"), ["test.png"])
    leave(runtime.session, a)
    runtime.advance(DELAY)
    runtime.settle()

    assert runtime.shown == after_a_delay
    assert runtime.session.paused is paused


def test_a_draft_leaves_a_profile_that_isnt_a_slideshow_unpaused(runtime):
    runtime.session.activate(saved("A", slideshow=False))
    runtime.session.apply_draft(Profile(name="align test"), ["test.png"])
    runtime.settle()

    assert runtime.session.paused is False


def test_a_draft_with_nothing_running_pauses_nothing(runtime):
    runtime.session.apply_draft(Profile(name="align test"), ["test.png"])
    runtime.settle()

    assert runtime.session.paused is False


def test_drafts_are_shown_for_the_layout_given(runtime):
    outcomes = []
    runtime.session.activate(saved("A"))
    runtime.session.apply_draft(Profile(name="unsaved"), ["draft.png"], layout="the editor's layout")
    runtime.session.apply_draft(Profile(name="align test"), ["test.png"], on_done=outcomes.append)
    runtime.settle()

    draft, test = runtime.changes[1:]
    assert (draft.image, draft.layout, draft.profile_id) == ("draft.png", "the editor's layout", None)
    # Without a layout, the session's own; the running profile's KDE activity gets it.
    assert (test.image, test.layout, test.running) == ("test.png", "layout 0", "A")
    assert outcomes == [None]
    assert runtime.session.running.selection.number == 1


def test_a_draft_says_what_went_wrong(runtime):
    outcomes = []
    runtime.problem = "The image test.png doesn't exist."
    runtime.session.apply_draft(Profile(name="align test"), ["test.png"], on_done=outcomes.append)
    runtime.settle()

    assert outcomes == ["The image test.png doesn't exist."]


def test_a_draft_that_fails_unexpectedly_still_says_so(runtime, monkeypatch, caplog):
    outcomes = []

    def broken(*args, **kwargs):
        message = "a bug"
        raise RuntimeError(message)

    monkeypatch.setattr(session_module, "show", broken)
    runtime.session.apply_draft(Profile(name="unsaved"), ["draft.png"], on_done=outcomes.append)
    runtime.settle()

    assert outcomes == ["The wallpaper could not be shown."]
    assert "a bug" in caplog.text


def test_an_unexpected_error_doesnt_stop_the_runtime(runtime, monkeypatch, caplog):
    real_show = runtime.show
    calls = []

    def fails_once(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            message = "a bug"
            raise RuntimeError(message)
        return real_show(*args, **kwargs)

    monkeypatch.setattr(session_module, "show", fails_once)
    runtime.session.activate(saved("A"))
    runtime.advance(DELAY)
    runtime.settle()

    assert "a bug" in caplog.text
    # The slideshow carries on.
    assert runtime.shown == ["A-2.png"]


def test_changes_use_the_settings_and_displays_current_at_the_time(runtime):
    runtime.session.activate(saved("A"))
    runtime.settle()
    runtime.set_command = "second {image}"
    runtime.session.use_displays("layout 1")
    runtime.session.next()
    runtime.settle()

    assert [(change.set_command, change.layout) for change in runtime.changes] == [
        ("first {image}", "layout 0"),
        ("second {image}", "layout 1"),
    ]
    assert runtime.session.layout == "layout 1"


def test_the_worker_never_detects_displays(runtime, monkeypatch):
    # Detecting displays off the main thread would corrupt memory (see detect_displays).
    detections = []
    monkeypatch.setattr(display_detection, "detect_displays", lambda **options: detections.append(options) or [])
    runtime.session.restore(saved("A"))
    runtime.session.activate(saved("B"))
    runtime.session.next()
    runtime.session.use_displays("layout 1")
    runtime.session.apply_draft(Profile(name="unsaved"), ["draft.png"])
    runtime.settle()

    assert detections == []
    assert runtime.shown == ["B-1.png", "B-2.png", "draft.png"]


def test_quitting_is_bounded_and_refuses_later_requests(runtime):
    runtime.session.activate(saved("A"))
    runtime.settle()
    runtime.hold_changes()
    runtime.session.next()
    assert runtime.holding.wait(10)
    outcomes = []

    started = time.monotonic()
    runtime.session.shutdown(timeout=0.2)
    assert time.monotonic() - started < 2
    runtime.session.next()
    runtime.session.apply_draft(Profile(name="unsaved"), ["draft.png"], on_done=outcomes.append)
    assert outcomes == ["Superpaper is quitting."]

    runtime.release()
    runtime.session._worker.join(10)
    assert not runtime.session._worker.is_alive()
    assert runtime.shown == ["A-1.png", "A-2.png"]


def test_a_change_that_ends_after_quitting_never_starts_another(runtime):
    runtime.session.activate(saved("A"))
    runtime.settle()
    runtime.hold_changes()
    runtime.advance(DELAY)
    runtime.session.use_displays(runtime.session.layout)
    assert runtime.holding.wait(10)
    runtime.session.next()  # waiting behind the slideshow's change

    runtime.session.shutdown(timeout=0.1)
    runtime.clock.now += 100 * DELAY
    runtime.release()
    runtime.session._worker.join(10)

    assert not runtime.session._worker.is_alive()
    assert runtime.shown == ["A-1.png", "A-2.png"]
