import pytest


def test_repeated_timer_arms_and_rearms_before_callback(profile_modules, manual_clock):
    _, wpproc = profile_modules
    events = []
    timer = wpproc.RepeatedTimer(12.5, lambda: events.append("callback"))

    assert timer.is_running is True
    assert len(manual_clock.timers) == 1
    assert manual_clock.timers[0].daemon is True
    assert manual_clock.timers[0].started is True

    manual_clock.timers[0].fire()

    assert len(manual_clock.timers) == 2
    assert manual_clock.timers[1].started is True
    assert events == ["callback"]


def test_repeated_timer_stop_and_restart(profile_modules, manual_clock):
    _, wpproc = profile_modules
    timer = wpproc.RepeatedTimer(10, lambda: None)
    first = manual_clock.timers[0]

    timer.stop()
    timer.start()

    assert first.cancelled is True
    assert timer.is_running is True
    assert len(manual_clock.timers) == 2


@pytest.mark.xfail(
    strict=True,
    reason="U17a: a dispatched tick can rearm a stopped timer; the Phase D session "
    "worker removes the separate timer thread",
)
def test_dispatched_tick_cannot_resurrect_stopped_timer(profile_modules, manual_clock):
    _, wpproc = profile_modules
    callbacks = []
    timer = wpproc.RepeatedTimer(10, lambda: callbacks.append("tick"))
    first = manual_clock.timers[0]

    timer.stop()
    first.fire(even_if_cancelled=True)

    assert timer.is_running is False
    assert len(manual_clock.timers) == 1
    assert callbacks == []


@pytest.mark.parametrize(
    ("slideshow", "startup", "expect_change", "expect_timer"),
    [(False, False, True, False), (False, True, False, False), (True, False, True, True), (True, True, False, True)],
)
def test_run_profile_job_matrix(
    profile_modules,
    manual_clock,
    slideshow_profile,
    slideshow,
    startup,
    expect_change,
    expect_timer,
):
    _, wpproc = profile_modules
    slideshow_profile.slideshow = slideshow
    changes = []
    thread = object()

    def change(profile, **options):
        changes.append((profile, options))
        return thread

    timer, result_thread = wpproc.run_profile_job(slideshow_profile, change, startup=startup)

    assert (result_thread is thread) is expect_change
    assert changes == ([(slideshow_profile, {})] if expect_change else [])
    assert (timer is not None) is expect_timer
    if expect_timer:
        assert manual_clock.timers[0].interval == 12.5
        manual_clock.timers[0].fire()
        assert changes[-1] == (slideshow_profile, {"advance": True, "skip_if_busy": True})
