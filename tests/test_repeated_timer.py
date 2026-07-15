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


@pytest.mark.xfail(strict=True, reason="Known timer race: a dispatched callback can rearm after stop")
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
    monkeypatch,
    slideshow_profile,
    slideshow,
    startup,
    expect_change,
    expect_timer,
):
    _, wpproc = profile_modules
    slideshow_profile.slideshow = slideshow
    calls = []
    thread = object()
    timer = object()
    monkeypatch.setattr(wpproc, "refresh_display_data", lambda: calls.append("refresh"))
    monkeypatch.setattr(wpproc, "change_wallpaper_job", lambda profile: calls.append(("change", profile)) or thread)
    monkeypatch.setattr(
        wpproc,
        "RepeatedTimer",
        lambda *args, **kwargs: calls.append(("timer", args, kwargs)) or timer,
    )

    result_timer, result_thread = wpproc.run_profile_job(slideshow_profile, startup=startup)

    assert calls[0] == "refresh"
    assert (result_thread is thread) is expect_change
    assert (result_timer is timer) is expect_timer
    timer_calls = [call for call in calls if isinstance(call, tuple) and call[0] == "timer"]
    if expect_timer:
        assert timer_calls == [
            (
                "timer",
                (12.5, wpproc.change_wallpaper_job, slideshow_profile),
                {"advance": True, "skip_if_busy": True},
            )
        ]
    else:
        assert timer_calls == []
