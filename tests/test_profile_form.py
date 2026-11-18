"""The profile editor's rules, without a UI: what a form means as a profile, when it counts
as changed, and what saving, reverting, deleting and applying it do."""

from types import SimpleNamespace

import pytest

from superpaper.geometry.perspective import Disabled
from superpaper.profiles import form as profile_form
from superpaper.profiles.form import (
    Problems,
    ProfileForm,
    Saved,
    applied_offsets,
    fingerprint,
    form_from,
    parse_form,
    preview_spangroups,
    sources_per_target,
    spangroups_of,
)
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import ProfileId
from superpaper.profiles.profile_store import ProfileStore
from superpaper.user_input import OffsetError


def blank(**changes):
    values = {
        "name": "Work",
        "span_mode": "single",
        "slideshow": False,
        "delay_minutes": "",
        "sort_label": None,
        "hotkey_enabled": False,
        "hotkey": "",
        "offsets_applied": False,
        "offsets": ("0,0", "0,0"),
        "spangroups_enabled": False,
        "spangroup_choices": (0, 0),
        "perspective": Disabled(),
        "zoom_pct": 100,
        "pan_pct": (0, 0),
        "per_target_sources": False,
        "sources": (("", "/pics"),),
    }
    return ProfileForm(**{**values, **changes})


@pytest.fixture
def layout(display_layout):
    return display_layout()


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
    enabled = parse_form(blank(spangroups_enabled=True, spangroup_choices=(1, 0)))[0].spangroups
    disabled = parse_form(blank(spangroup_choices=(1, 0)))[0].spangroups
    assert (enabled, disabled) == (((0,), (1,)), None)


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
        corrections=(("offsets", ((3, 4),)),),
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


def test_an_unknown_sort_mode_selects_nothing(layout):
    assert form_from(Profile(name="Work", sortmode="odd"), layout).sort_label is None


def test_a_single_profile_that_corrects_positions_is_shown_as_advanced(layout):
    legacy = Profile(name="Old", spanmode="single", corrections=(("offsets", ((1, 2), (3, 4))),))
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


class FakeSession:
    def __init__(self, store):
        self.store = store
        self.running = None
        self.updates = []
        self.drafts = []

    def renames_running(self, profile_id, new_name):
        return self.running is not None and profile_id == self.running.profile_id and new_name != profile_id.value

    def update(self, profile_id, stored):
        self.updates.append((profile_id, stored))

    def apply_draft(self, profile, images, *, layout, on_done):
        self.drafts.append((profile, images, layout))
        self.on_done = on_done


@pytest.fixture
def images(tmp_path):
    folder = tmp_path / "images"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        (folder / name).write_bytes(b"")
    return folder


@pytest.fixture
def store(app_paths):
    store = ProfileStore(app_paths)
    store.reload()
    return store


@pytest.fixture
def session(store):
    return FakeSession(store)


def save(store, session, form, *, loaded=None, focused_path=None, rebinds=None):
    return profile_form.save_profile(
        form,
        focused_path=focused_path,
        loaded=loaded,
        store=store,
        session=session,
        rebind_hotkey=lambda before, after: rebinds.append((before, after)) if rebinds is not None else None,
    )


def test_a_valid_form_is_saved_as_a_new_profile_and_its_hotkey_bound(store, session, images):
    rebinds = []
    result = save(store, session, blank(sources=(("", str(images)),)), rebinds=rebinds)
    assert isinstance(result, Saved)
    assert store.get(ProfileId("Work")) is result.stored
    assert result.stored.profile.sources == ((str(images),),)
    assert rebinds == [(None, result.stored)]
    assert session.updates == []


def test_an_invalid_form_is_not_saved_and_says_why(store, session, app_paths):
    result = save(store, session, blank(name=" ", sources=()))
    assert result == Problems(
        ("You must enter a name for the profile.", "At least one path for wallpapers must be given.")
    )
    assert list(app_paths.profiles.iterdir()) == []


def test_a_name_that_cant_be_used_comes_first_among_the_problems(store, session, images):
    result = save(store, session, blank(name="m" * 201, sources=(("", str(images)),)))
    assert isinstance(result, Problems)
    assert "200" in result.messages[0]


def test_saving_over_a_loaded_profile_updates_the_session_and_follows_a_rename(store, session, images):
    first = save(store, session, blank(sources=(("", str(images)),)))
    session.running = first.stored
    rebinds = []
    renamed = save(
        store, session, blank(name="Home", sources=(("", str(images)),)), loaded=first.stored, rebinds=rebinds
    )
    assert isinstance(renamed, Saved)
    assert (session.updates[0][0], session.updates[0][1]) == (ProfileId("Work"), renamed.stored)
    assert rebinds == [(first.stored, renamed.stored)]
    assert store.get(ProfileId("Work")) is None


def test_saving_chooses_the_focused_file_else_the_loaded_selection(store, session, images):
    first = save(store, session, blank(sources=(("", str(images)),)))
    focused = str(images / "b.png")
    second = save(
        store, session, blank(zoom_pct=120, sources=(("", str(images)),)), loaded=first.stored, focused_path=focused
    )
    assert second.stored.selection.images == [focused]


def test_chosen_images_for_one_image_per_display_are_none(store, images):
    loaded = SimpleNamespace(selection=SimpleNamespace(images=["/x.png"]))
    multi = Profile(name="m", spanmode="multi")
    single = Profile(name="s")
    assert profile_form.chosen_images(multi, str(images / "a.png"), loaded) is None
    assert profile_form.chosen_images(single, str(images / "a.png"), loaded) == [str(images / "a.png")]
    assert profile_form.chosen_images(single, str(images), loaded) == ["/x.png"]
    assert profile_form.chosen_images(single, None, None) is None


def test_reverting_loads_the_file_again_and_carries_the_running_profile_on(store, session, images, app_paths):
    saved = save(store, session, blank(sources=(("", str(images)),))).stored
    session.running = saved
    path = app_paths.profiles / "Work.profile"
    path.write_text(path.read_text(encoding="utf-8") + "zoom=1.75\n", encoding="utf-8")
    reverted = profile_form.revert_profile("Work", store=store, session=session)
    assert reverted is store.get(ProfileId("Work"))
    assert reverted.profile.zoom == 1.75
    assert session.updates == [(ProfileId("Work"), reverted)]


def test_reverting_without_a_saved_profile_gives_nothing(store, session):
    assert profile_form.revert_profile("", store=store, session=session) is None
    assert profile_form.revert_profile(profile_form.NEW_PROFILE_LABEL, store=store, session=session) is None
    assert profile_form.revert_profile("Nope", store=store, session=session) is None


def test_deleting_forgets_the_profile_stops_it_and_frees_its_hotkey(store, session, images, app_paths):
    saved = save(store, session, blank(sources=(("", str(images)),))).stored
    rebinds = []
    problem = profile_form.delete_profile(
        saved, store=store, session=session, rebind_hotkey=lambda before, after: rebinds.append((before, after))
    )
    assert problem is None
    assert not (app_paths.profiles / "Work.profile").exists()
    assert session.updates == [(ProfileId("Work"), None)]
    assert rebinds == [(saved, None)]


def test_a_profile_changed_on_disk_is_not_deleted(store, session, images, app_paths):
    saved = save(store, session, blank(sources=(("", str(images)),))).stored
    path = app_paths.profiles / "Work.profile"
    path.write_text(path.read_text(encoding="utf-8") + "zoom=1.75\n", encoding="utf-8")
    problem = profile_form.delete_profile(saved, store=store, session=session, rebind_hotkey=lambda *_: None)
    assert isinstance(problem, Problems)
    assert path.exists()
    assert session.updates == []


def test_saved_profile_finds_by_name_and_not_by_a_name_no_profile_can_have(store, session, images):
    saved = save(store, session, blank(sources=(("", str(images)),))).stored
    assert profile_form.saved_profile(store, "Work") is saved
    assert profile_form.saved_profile(store, "../x") is None


def test_an_invalid_form_cant_be_applied(images):
    result = profile_form.prepare_draft(blank(sources=()), None, None)
    assert result == Problems(("At least one path for wallpapers must be given.",))


def test_applying_shows_the_chosen_image_for_the_staged_layout_and_pins_it_once_shown(store, session, images, layout):
    saved = save(store, session, blank(sources=(("", str(images)),))).stored
    focused = str(images / "b.png")
    draft = profile_form.prepare_draft(blank(sources=(("", str(images)),)), focused, saved)
    posted = []
    shown = []
    profile_form.show_draft(
        draft, loaded=saved, layout=layout, session=session, post=posted.append, on_shown=shown.append
    )
    profile, shown_images, shown_layout = session.drafts[0]
    assert (profile, shown_images, shown_layout) == (draft.profile, [focused], layout)
    session.on_done(None)
    assert saved.selection.images != [focused]
    posted.pop()()
    assert saved.selection.images == [focused]
    assert shown == [None]


def test_a_draft_that_failed_to_show_leaves_the_selection_alone(store, session, images, layout):
    saved = save(store, session, blank(sources=(("", str(images)),))).stored
    before = saved.selection.images
    draft = profile_form.prepare_draft(blank(sources=(("", str(images)),)), str(images / "b.png"), saved)
    posted = []
    shown = []
    profile_form.show_draft(
        draft, loaded=saved, layout=layout, session=session, post=posted.append, on_shown=shown.append
    )
    session.on_done("broken")
    posted.pop()()
    assert saved.selection.images == before
    assert shown == ["broken"]


def test_a_draft_without_a_chosen_image_shows_the_first_of_the_sources(images):
    draft = profile_form.prepare_draft(blank(sources=(("", str(images / "a.png")),)), None, None)
    assert draft.chosen is None
    assert draft.images == [str(images / "a.png")]


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
    assert profile_form.applied_spangroups(blank(spangroups_enabled=True, spangroup_choices=(0, 1))) == ((0,), (1,))
    assert profile_form.applied_spangroups(blank(spangroup_choices=(0, 1))) is None


def test_display_areas_follow_the_span_mode(layout):
    assert profile_form.display_areas(layout, "advanced") == layout.ppi_norm_areas()
    assert profile_form.display_areas(layout, "single") == layout.real_areas()
    assert profile_form.display_areas(layout, "multi") == layout.real_areas()
