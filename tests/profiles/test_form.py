"""The profile editor's rules, without a UI: what a form means as a profile and when it counts
as changed."""

from types import SimpleNamespace

import pytest

from superpaper.profiles import form as profile_form
from superpaper.profiles.form import (
    applied_offsets,
    fingerprint,
    form_from,
    parse_form,
    parse_offsets,
    preview_spangroups,
    sources_per_target,
    spangroups_of,
)
from superpaper.profiles.profile_file import OffsetsCorrection, Profile
from superpaper.user_input import OffsetError
from tests.profiles.conftest import blank


def test_offsets_are_read_from_x_comma_y_fields():
    assert parse_offsets(["10,-20", " 3 , 4 ", "0,0"]) == ((10, -20), (3, 4), (0, 0))


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_offset_field_means_no_offset(empty):
    assert parse_offsets(["1,2", empty]) == ((1, 2), (0, 0))


def test_no_fields_give_no_offsets():
    assert parse_offsets([]) == ()


@pytest.mark.parametrize("text", ["1", "1,2,3", "1;2", "1,x", "1.5,2", ",2", "1,"])
def test_a_field_that_is_not_a_pair_of_whole_numbers_is_an_error_naming_the_display(text):
    with pytest.raises(OffsetError, match=rf"display 1: .*'{text}'"):
        parse_offsets(["0,0", text])


def test_every_unreadable_field_is_named():
    with pytest.raises(OffsetError) as error:
        parse_offsets(["a,b", "1,2", "3"])

    assert str(error.value).splitlines() == [
        "Manual offset of display 0: expected whole pixel numbers as x,y, not 'a,b'.",
        "Manual offset of display 2: expected whole pixel numbers as x,y, not '3'.",
    ]


def test_a_slideshow_delay_in_minutes_is_seconds_in_the_profile():
    profile, problems = parse_form(blank(slideshow=True, delay_minutes="1.5", sort_label="Alphabetical"))
    assert (profile.delay, profile.sortmode, problems) == (90.0, "alphabetical", [])


@pytest.mark.parametrize(
    ("label", "mode"),
    [
        ("Shuffle", "shuffle"),
        ("Alphabetical", "alphabetical"),
        ("Date seeded shuffle", "date_seeded_shuffle"),
        (None, "shuffle"),
    ],
)
def test_the_sort_label_is_the_sort_mode(label, mode):
    assert parse_form(blank(slideshow=True, delay_minutes="5", sort_label=label))[0].sortmode == mode


def test_a_slideshow_needs_a_delay_that_is_a_number():
    _, missing = parse_form(blank(slideshow=True, delay_minutes="  "))
    _, wrong = parse_form(blank(slideshow=True, delay_minutes="soon"))
    assert missing == ["When using slideshow you need to enter a delay."]
    assert wrong == ["The slideshow delay must be a number of minutes, not 'soon'."]


@pytest.mark.parametrize("text", ["0", "-1"])
def test_a_slideshow_delay_must_be_positive(text):
    _, problems = parse_form(blank(slideshow=True, delay_minutes=text))
    assert problems == [f"The slideshow delay must be a number of minutes, not '{text}'."]


def test_the_delay_and_sort_are_ignored_without_a_slideshow():
    profile, problems = parse_form(blank(delay_minutes="soon", sort_label="Alphabetical"))
    assert (profile.delay, profile.sortmode, problems) == (600.0, "shuffle", [])


def test_the_hotkey_is_split_at_pluses_only_when_enabled():
    enabled = parse_form(blank(hotkey_enabled=True, hotkey=" control+super+x "))[0].hotkey
    blanked = parse_form(blank(hotkey_enabled=True, hotkey="  "))[0].hotkey
    disabled = parse_form(blank(hotkey_enabled=False, hotkey="control+x"))[0].hotkey
    assert (enabled, blanked, disabled) == (("control", "super", "x"), None, None)


def test_a_slideshow_renders_at_default_zoom_and_pan_whatever_the_sliders_say():
    slideshow = parse_form(blank(slideshow=True, delay_minutes="5", zoom_pct=150, pan_pct=(10, -20)))[0]
    fixed = parse_form(blank(zoom_pct=150, pan_pct=(10, -20)))[0]
    assert (slideshow.zoom, slideshow.pan) == (1.0, (0.0, 0.0))
    assert (fixed.zoom, fixed.pan) == (1.5, (0.1, -0.2))


def test_one_list_of_sources_is_one_group_and_per_target_sources_group_by_display():
    one = parse_form(blank(sources=(("", "/a"), ("", "/b"))))[0]
    several = parse_form(
        blank(span_mode="multi", per_target_sources=True, sources=(("1", "/c"), ("0", "/a"), ("1", "/d"), ("0", "/b")))
    )[0]
    assert one.sources == (("/a", "/b"),)
    assert several.sources == (("/a", "/b"), ("/c", "/d"))


def test_no_sources_listed_is_one_empty_group_for_one_list_and_none_per_target():
    assert parse_form(blank(sources=()))[0].sources == ((),)
    assert parse_form(blank(per_target_sources=True, sources=()))[0].sources == ()


def test_offsets_are_only_read_when_applied_and_an_unreadable_one_is_a_problem():
    unapplied = parse_form(blank(offsets=("x", "y")))
    applied = parse_form(blank(offsets_applied=True, offsets=("1,2", "")))
    broken = parse_form(blank(offsets_applied=True, offsets=("1,2", "x")))
    assert (unapplied[0].offsets, unapplied[1]) == ((), [])
    assert applied[0].offsets == ((1, 2), (0, 0))
    assert broken[0].offsets == ((0, 0), (0, 0))
    assert broken[1] == ["Manual offset of display 1: expected whole pixel numbers as x,y, not 'x'."]


def test_applied_offsets_are_zero_unless_applied_and_then_must_be_readable():
    assert applied_offsets(False, ["x", "y"]) == ((0, 0), (0, 0))
    assert applied_offsets(True, ["1,2", "3,4"]) == ((1, 2), (3, 4))
    with pytest.raises(OffsetError):
        applied_offsets(True, ["1;2", ""])


def test_span_groups_follow_the_choices_only_when_enabled():
    enabled = parse_form(blank(span_mode="advanced", spangroups_enabled=True, spangroup_choices=(1, 0)))[0].spangroups
    disabled = parse_form(blank(span_mode="advanced", spangroup_choices=(1, 0)))[0].spangroups
    assert (enabled, disabled) == (((0,), (1,)), None)


def test_span_groups_are_dropped_outside_advanced_mode():
    form = blank(span_mode="multi", spangroups_enabled=True, spangroup_choices=(1, 0))
    assert profile_form.applied_spangroups(form) is None


def test_a_display_without_sources_keeps_the_later_sources_on_their_display(layout):
    profile = Profile(name="Gap", slideshow=False, spanmode="multi", sources=((), ("/b",)))
    assert parse_form(form_from(profile, layout))[0].sources == ((), ("/b",))


def test_a_trailing_display_without_sources_survives_the_round_trip(layout):
    profile = Profile(name="Gap", slideshow=False, spanmode="multi", sources=(("/a",), ()))
    form = form_from(profile, layout)
    assert parse_form(form)[0].sources == (("/a",), ())
    assert fingerprint(form) == fingerprint(form_from(parse_form(form)[0], layout))


def test_per_target_sources_are_ordered_by_display_number_not_text():
    rows = tuple((str(target), f"/{target}") for target in (10, 2))
    sources = parse_form(blank(span_mode="multi", per_target_sources=True, sources=rows))[0].sources
    assert sources[2] == ("/2",)
    assert sources[10] == ("/10",)


def test_groups_are_listed_in_the_order_they_first_appear_and_the_preview_wants_two():
    assert spangroups_of((1, 0, 1)) == ((0, 2), (1,))
    assert preview_spangroups((0, 0)) is None
    assert preview_spangroups((0, 1)) == ((0,), (1,))


def test_sources_are_per_target_for_multi_or_advanced_with_span_groups():
    assert sources_per_target("multi", False)
    assert sources_per_target("advanced", True)
    assert not sources_per_target("advanced", False)
    assert not sources_per_target("single", True)


def test_a_saved_profile_is_shown_in_the_form_as_typed(layout):
    profile = Profile(
        name="Work",
        spanmode="advanced",
        spangroups=((1,), (0,)),
        slideshow=True,
        delay=900.0,
        sortmode="date_seeded_shuffle",
        sources=(("/a",), ("/b", "/c")),
        hotkey=("control", "x"),
        zoom=1.5,
        pan=(0.25, -0.5),
        corrections=(OffsetsCorrection(((3, 4),)),),
    )
    shown = form_from(profile, layout)
    assert shown.delay_minutes == "15.0"
    assert shown.sort_label == "Date seeded shuffle"
    assert (shown.hotkey_enabled, shown.hotkey) == (True, "control+x")
    assert (shown.offsets_applied, shown.offsets) == (True, ("3,4", "0,0"))
    assert (shown.spangroups_enabled, shown.spangroup_choices) == (True, (1, 0))
    assert (shown.zoom_pct, shown.pan_pct) == (150, (25, -50))
    assert (shown.per_target_sources, shown.sources) == (True, (("0", "/a"), ("1", "/b"), ("1", "/c")))


def test_a_profile_without_a_slideshow_shows_no_delay_or_sort(layout):
    shown = form_from(Profile(name="Work", slideshow=False, delay=900.0, sortmode="alphabetical"), layout)
    assert (shown.delay_minutes, shown.sort_label) == ("", None)


def test_a_single_profile_that_corrects_positions_is_shown_as_advanced(layout):
    legacy = Profile(name="Old", spanmode="single", corrections=(OffsetsCorrection(((1, 2), (3, 4))),))
    plain = Profile(name="New", spanmode="single")
    assert form_from(legacy, layout).span_mode == "advanced"
    assert form_from(plain, layout).span_mode == "single"


def test_a_form_shown_from_a_profile_gives_the_profile_back(layout):
    profile = Profile(
        name="Work",
        spanmode="multi",
        slideshow=False,
        sources=(("/a",), ("/b",)),
        hotkey=("alt", "z"),
        zoom=1.25,
        pan=(0.5, 0.0),
    )
    assert parse_form(form_from(profile, layout)) == (profile, [])


def test_the_fingerprint_changes_with_what_would_be_saved_and_with_unreadable_fields():
    base = blank(slideshow=True, delay_minutes="5")
    assert fingerprint(base) == fingerprint(blank(slideshow=True, delay_minutes="5"))
    assert fingerprint(base) != fingerprint(blank(slideshow=True, delay_minutes="6"))
    assert fingerprint(base) != fingerprint(blank(slideshow=True, delay_minutes="6x"))
    assert fingerprint(blank(slideshow=True, delay_minutes="6x")) != fingerprint(
        blank(slideshow=True, delay_minutes="6y")
    )


def test_the_fingerprint_ignores_what_is_not_saved():
    base = blank(slideshow=True, delay_minutes="5", zoom_pct=100)
    assert fingerprint(base) == fingerprint(blank(slideshow=True, delay_minutes="5", zoom_pct=170, pan_pct=(5, 5)))
    assert fingerprint(blank()) == fingerprint(blank(delay_minutes="9", sort_label="Alphabetical"))


@pytest.fixture
def images(tmp_path):
    folder = tmp_path / "images"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        (folder / name).write_bytes(b"")
    return folder


def test_chosen_images_for_one_image_per_display_are_none_without_a_click(images):
    loaded = SimpleNamespace(selection=SimpleNamespace(images=["/x.png"]))
    multi = Profile(name="m", spanmode="multi")
    single = Profile(name="s")
    both = [str(images / "a.png"), str(images / "b.png")]
    assert profile_form.chosen_images(multi, None, loaded) is None
    assert profile_form.chosen_images(multi, both, loaded) == both
    assert profile_form.chosen_images(single, [str(images / "a.png")], loaded) == [str(images / "a.png")]
    assert profile_form.chosen_images(single, [str(images)], loaded) == ["/x.png"]
    assert profile_form.chosen_images(single, None, None) is None


def test_a_new_profile_starts_blank_with_a_field_for_every_display(layout):
    blank_profile = profile_form.blank_form(layout)
    assert blank_profile.offsets == ("0,0", "0,0")
    assert blank_profile.spangroup_choices == (0, 0)
    assert parse_form(blank_profile)[0].sources == ((),)
    assert (blank_profile.name, blank_profile.span_mode, blank_profile.slideshow) == ("", "single", False)
    assert (blank_profile.zoom_pct, blank_profile.pan_pct) == (100, (0, 0))


def test_a_profile_without_offsets_or_span_groups_shows_neutral_fields(layout):
    shown = form_from(Profile(name="Plain"), layout)
    assert (shown.offsets_applied, shown.offsets) == (False, ("0,0", "0,0"))
    assert (shown.spangroups_enabled, shown.spangroup_choices) == (False, (0, 0))


def test_applied_span_groups_are_none_unless_enabled():
    form = blank(span_mode="advanced", spangroups_enabled=True, spangroup_choices=(0, 1))
    assert profile_form.applied_spangroups(form) == ((0,), (1,))
    assert profile_form.applied_spangroups(blank(spangroup_choices=(0, 1))) is None


def test_display_areas_follow_the_span_mode(layout):
    assert profile_form.display_areas(layout, "advanced") == layout.ppi_norm_areas()
    assert profile_form.display_areas(layout, "single") == layout.real_areas()
    assert profile_form.display_areas(layout, "multi") == layout.real_areas()
