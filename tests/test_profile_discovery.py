import os

import pytest

from superpaper.profile_id import ProfileId


def profile_bytes(name, extra=b""):
    return f"name={name}\nspanmode=single\nslideshow=false\n".encode() + extra


def prepare(data, monkeypatch, tmp_path):
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    monkeypatch.setattr(data.sp_paths, "PROFILES_PATH", str(profiles))
    return profiles


def test_discovery_returns_valid_profiles_in_filename_order(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    (profiles / "Zulu.profile").write_bytes(profile_bytes("Zulu"))
    (profiles / "Alpha.profile").write_bytes(profile_bytes("Alpha"))
    (profiles / "nested").mkdir()
    (profiles / "nested" / "Hidden.profile").write_bytes(profile_bytes("Hidden"))

    inventory = data.discover_profile_inventory()

    assert [entry.profile_id.value for entry in inventory.entries] == ["Alpha", "Zulu"]
    assert [profile.profile_id for profile in data.list_profiles()] == [ProfileId("Alpha"), ProfileId("Zulu")]


@pytest.mark.parametrize(
    ("filename", "internal_name", "kind"),
    [
        ("bad=name.profile", "bad=name", "INVALID_FILENAME"),
        ("saved.profile", "other", "NAME_MISMATCH"),
    ],
)
def test_identity_failures_are_quarantined_without_prompt(
    profile_modules, monkeypatch, tmp_path, filename, internal_name, kind
):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / filename
    original = profile_bytes(internal_name)
    path.write_bytes(original)
    prompts = []
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: prompts.append(args) or True)

    inventory = data.discover_profile_inventory()

    assert inventory.entries == ()
    assert [diagnostic.kind.name for diagnostic in inventory.diagnostics] == [kind]
    assert data.list_profiles() == []
    assert prompts == []
    assert path.read_bytes() == original


def test_portable_collision_quarantines_every_entry(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    upper = profiles / "Work.profile"
    lower = profiles / "work.profile"
    upper.write_bytes(profile_bytes("Work"))
    lower.write_bytes(profile_bytes("work"))

    inventory = data.discover_profile_inventory()

    assert inventory.entries == ()
    assert [item.kind for item in inventory.diagnostics] == [
        data.ProfileDiagnosticKind.PORTABLE_COLLISION,
        data.ProfileDiagnosticKind.PORTABLE_COLLISION,
    ]
    assert data.open_profile("Work") is None
    assert upper.read_bytes() == profile_bytes("Work")
    assert lower.read_bytes() == profile_bytes("work")


@pytest.mark.parametrize("outside", [False, True])
def test_symlink_profiles_are_never_discovered(profile_modules, monkeypatch, tmp_path, outside):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    target = (tmp_path if outside else profiles) / "target"
    target.write_bytes(profile_bytes("linked"))
    link = profiles / "linked.profile"
    link.symlink_to(target)
    original = target.read_bytes()

    inventory = data.discover_profile_inventory()

    assert inventory.entries == ()
    assert inventory.diagnostics[0].kind is data.ProfileDiagnosticKind.SYMLINK
    assert data.open_profile("linked") is None
    assert target.read_bytes() == original


def test_safe_open_rejects_paths_and_accepts_unicode_id(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "Työ.profile"
    path.write_bytes(profile_bytes("Työ"))
    unicode_path = profiles / "Työ.profile"
    unicode_path.write_bytes(profile_bytes("Työ"))

    assert data.open_profile("../outside") is None
    assert data.open_profile(str(unicode_path)) is None
    assert data.open_profile("Työ") is None
    assert data.open_profile(ProfileId("Työ")).profile_id == ProfileId("Työ")


def test_rename_source_lookup_uses_original_id(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    (profiles / "Original.profile").write_bytes(profile_bytes("Original", b"hotkey=control+x\n"))

    source = data.open_profile(ProfileId("Original"))

    assert source.hk_binding == ("control", "x")
    assert data.open_profile(ProfileId("Renamed")) is None


def test_delete_uses_loaded_identity_and_rejects_replacement(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "Work.profile"
    path.write_bytes(profile_bytes("Work"))
    loaded = data.open_profile(ProfileId("Work"))
    path.unlink()
    path.write_bytes(profile_bytes("Work", b"hotkey=control+x\n"))

    with pytest.raises(data.ManagedPathError):
        data.delete_managed_profile(loaded)

    assert path.exists()


def test_delete_rejects_symlink_replacement_without_touching_target(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "Work.profile"
    path.write_bytes(profile_bytes("Work"))
    loaded = data.open_profile(ProfileId("Work"))
    path.unlink()
    sentinel = tmp_path / "sentinel.profile"
    sentinel.write_bytes(profile_bytes("Work"))
    path.symlink_to(sentinel)

    with pytest.raises((data.ManagedPathError, OSError)):
        data.delete_managed_profile(loaded)

    assert sentinel.read_bytes() == profile_bytes("Work")


def test_delete_selection_ignores_editable_traversal_and_deletes_selected_profile(
    profile_modules, monkeypatch, tmp_path
):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    selected_path = profiles / "Work.profile"
    other_path = profiles / "Other.profile"
    outside = tmp_path / "outside.profile"
    selected_path.write_bytes(profile_bytes("Work"))
    other_path.write_bytes(profile_bytes("Other"))
    outside.write_bytes(b"sentinel")
    loaded = data.list_profiles()
    editable_name = "../outside"

    selected = data.managed_profile_for_selection(loaded, ProfileId("Work"))
    assert editable_name == "../outside"
    data.delete_managed_profile(selected)

    assert not selected_path.exists()
    assert other_path.exists()
    assert outside.read_bytes() == b"sentinel"


def test_malformed_content_keeps_legacy_deletion_prompt(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "broken.profile"
    path.write_bytes(profile_bytes("broken", b"delay=not-a-number\n"))
    prompts = []
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: prompts.append(args) or False)

    assert data.list_profiles() == []
    assert len(prompts) == 1
    assert path.exists()


def test_malformed_prompt_retains_replacement_made_during_confirmation(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "broken.profile"
    path.write_bytes(profile_bytes("broken", b"delay=not-a-number\n"))
    replacement = profile_bytes("broken", b"hotkey=control+x\n")

    def replace_then_confirm(*_args, **_kwargs):
        path.unlink()
        path.write_bytes(replacement)
        return True

    monkeypatch.setattr(data, "show_message_dialog", replace_then_confirm)

    assert data.list_profiles() == []
    assert path.read_bytes() == replacement


def test_read_only_identity_failure_is_byte_for_byte_untouched(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "saved.profile"
    original = profile_bytes("other")
    path.write_bytes(original)
    path.chmod(0o444)
    prompts = []
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: prompts.append(args) or True)

    assert data.list_profiles() == []
    assert data.open_profile("saved") is None
    assert prompts == []
    assert path.read_bytes() == original


def test_io_failure_is_diagnostic_without_deletion_prompt(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "saved.profile"
    path.write_bytes(profile_bytes("saved"))
    prompts = []
    real_open = data.os.open

    def fail_open(candidate, flags):
        if candidate == path:
            message = "denied"
            raise PermissionError(message)
        return real_open(candidate, flags)

    monkeypatch.setattr(data.os, "open", fail_open)
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: prompts.append(args) or True)

    inventory = data.discover_profile_inventory()

    assert inventory.entries == ()
    assert inventory.diagnostics[0].kind is data.ProfileDiagnosticKind.IO_ERROR
    assert data.list_profiles() == []
    assert prompts == []
    assert path.read_bytes() == profile_bytes("saved")


@pytest.mark.parametrize(
    "setting",
    [b"ppi=0;0\n", b"diagonal_inches=0;24\n", b"zoom=\n", b"align=\n"],
)
def test_construction_failure_is_malformed_and_prompted(profile_modules, monkeypatch, tmp_path, setting):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "broken.profile"
    original = profile_bytes("broken", setting)
    path.write_bytes(original)
    prompts = []
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: prompts.append(args) or False)

    assert data.list_profiles() == []
    assert len(prompts) == 1
    assert path.read_bytes() == original


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_fifo_profile_is_diagnostic_without_blocking_or_prompt(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    os.mkfifo(profiles / "pipe.profile")
    prompts = []
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: prompts.append(args) or True)

    inventory = data.discover_profile_inventory()

    assert inventory.entries == ()
    assert inventory.diagnostics[0].kind is data.ProfileDiagnosticKind.NOT_REGULAR_FILE
    assert prompts == []


@pytest.mark.parametrize("invalid_kind", ["malformed", "symlink", "fifo"])
def test_invalid_entry_reserves_collision_key(profile_modules, monkeypatch, tmp_path, invalid_kind):
    if invalid_kind == "fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("FIFOs are unavailable")
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    prompts = []
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: prompts.append(args) or True)
    valid = profiles / "Work.profile"
    invalid = profiles / "work.profile"
    valid.write_bytes(profile_bytes("Work"))
    if invalid_kind == "malformed":
        invalid.write_bytes(profile_bytes("work", b"delay=not-a-number\n"))
    elif invalid_kind == "symlink":
        target = tmp_path / "target.profile"
        target.write_bytes(profile_bytes("work"))
        invalid.symlink_to(target)
    else:
        os.mkfifo(invalid)

    inventory = data.discover_profile_inventory()

    assert inventory.entries == ()
    collision_paths = {
        diagnostic.path
        for diagnostic in inventory.diagnostics
        if diagnostic.kind is data.ProfileDiagnosticKind.PORTABLE_COLLISION
    }
    assert collision_paths == {valid, invalid}
    assert any(
        diagnostic.path == invalid
        and diagnostic.kind
        in {
            data.ProfileDiagnosticKind.MALFORMED_CONTENT,
            data.ProfileDiagnosticKind.SYMLINK,
            data.ProfileDiagnosticKind.NOT_REGULAR_FILE,
        }
        for diagnostic in inventory.diagnostics
    )
    assert data.list_profiles() == []
    assert prompts == []
