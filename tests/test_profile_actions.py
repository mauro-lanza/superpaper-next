"""What the profile editor does with the saved profiles and the session: saving, reverting,
deleting and showing a draft of what a form describes."""

import pytest

from superpaper.geometry.perspective import Disabled, Named
from superpaper.profile_actions import (
    Saved,
    align_test_profile,
    delete_profile,
    revert_profile,
    save_profile,
    saved_profile,
    show_draft,
)
from superpaper.profiles.form import prepare_draft
from superpaper.profiles.profile_file import OffsetsCorrection
from superpaper.profiles.profile_id import NEW_PROFILE_LABEL, ProfileId
from superpaper.profiles.profile_store import ProfileStore
from superpaper.user_input import Problems
from tests.test_profile_form import blank


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
    return save_profile(
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
    result = save(store, session, blank(name="m" * 51, sources=(("", str(images)),)))
    assert isinstance(result, Problems)
    assert "50" in result.messages[0]


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


def test_reverting_loads_the_file_again_and_carries_the_running_profile_on(store, session, images, app_paths):
    saved = save(store, session, blank(sources=(("", str(images)),))).stored
    session.running = saved
    path = app_paths.profiles / "Work.profile"
    path.write_text(path.read_text(encoding="utf-8") + "zoom=1.75\n", encoding="utf-8")
    reverted = revert_profile("Work", store=store, session=session)
    assert reverted is store.get(ProfileId("Work"))
    assert reverted.profile.zoom == 1.75
    assert session.updates == [(ProfileId("Work"), reverted)]


def test_reverting_without_a_saved_profile_gives_nothing(store, session):
    assert revert_profile("", store=store, session=session) is None
    assert revert_profile(NEW_PROFILE_LABEL, store=store, session=session) is None
    assert revert_profile("Nope", store=store, session=session) is None


def test_deleting_forgets_the_profile_stops_it_and_frees_its_hotkey(store, session, images, app_paths):
    saved = save(store, session, blank(sources=(("", str(images)),))).stored
    rebinds = []
    problem = delete_profile(
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
    problem = delete_profile(saved, store=store, session=session, rebind_hotkey=lambda *_: None)
    assert isinstance(problem, Problems)
    assert path.exists()
    assert session.updates == []


def test_saved_profile_finds_by_name_and_not_by_a_name_no_profile_can_have(store, session, images):
    saved = save(store, session, blank(sources=(("", str(images)),))).stored
    assert saved_profile(store, "Work") is saved
    assert saved_profile(store, "../x") is None


def test_applying_shows_the_chosen_image_for_the_staged_layout_and_pins_it_once_shown(store, session, images, layout):
    saved = save(store, session, blank(sources=(("", str(images)),))).stored
    focused = str(images / "b.png")
    draft = prepare_draft(blank(sources=(("", str(images)),)), focused, saved)
    posted = []
    shown = []
    show_draft(draft, loaded=saved, layout=layout, session=session, post=posted.append, on_shown=shown.append)
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
    draft = prepare_draft(blank(sources=(("", str(images)),)), str(images / "b.png"), saved)
    posted = []
    shown = []
    show_draft(draft, loaded=saved, layout=layout, session=session, post=posted.append, on_shown=shown.append)
    session.on_done("broken")
    posted.pop()()
    assert saved.selection.images == before
    assert shown == ["broken"]


def test_the_align_test_shows_one_image_with_the_typed_offsets_and_chosen_perspective():
    profile = align_test_profile("test.png", Named("p"), ((0, 0), (10, 20)))
    assert profile.spanmode == "advanced"
    assert profile.sources == (("test.png",),)
    assert profile.perspective == Named("p")
    assert profile.corrections == (OffsetsCorrection(((0, 0), (10, 20))),)
    assert not profile.slideshow


def test_the_align_test_without_offsets_has_no_correction():
    profile = align_test_profile("test.png", Disabled(), ())
    assert profile.perspective == Disabled()
    assert profile.corrections == ()
