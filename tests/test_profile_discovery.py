import os
import sys
import unicodedata

import pytest

from superpaper.profile_id import ProfileId, ProfileIdError


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


@pytest.mark.parametrize("stem", ["back\\slash", "bell\x07", "cli", "Create a new profile"])
def test_unsafe_filenames_are_ignored_without_prompt(profile_modules, monkeypatch, tmp_path, stem):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / f"{stem}.profile"
    original = profile_bytes(stem)
    path.write_bytes(original)
    prompts = []
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: prompts.append(args) or True)

    inventory = data.discover_profile_inventory()

    assert inventory.entries == ()
    assert [diagnostic.kind.name for diagnostic in inventory.diagnostics] == ["INVALID_FILENAME"]
    assert data.list_profiles() == []
    assert prompts == []
    assert path.read_bytes() == original


@pytest.mark.skipif(sys.platform == "win32", reason="these filenames cannot exist on Windows")
@pytest.mark.parametrize(
    ("stem", "name_line"),
    [
        ("bad=name", "bad=name"),
        ("Work: dual", "Work: dual"),
        ("saved", "renamed by hand"),
        ("Work", "work"),
    ],
)
def test_profiles_saved_by_older_versions_keep_loading(profile_modules, monkeypatch, tmp_path, stem, name_line):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / f"{stem}.profile"
    original = profile_bytes(name_line)
    path.write_bytes(original)

    (profile,) = data.list_profiles()

    assert profile.profile_id == ProfileId(stem)
    assert profile.name == stem
    assert path.read_bytes() == original


def test_case_variant_profiles_both_load(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    (profiles / "Work.profile").write_bytes(profile_bytes("Work"))
    (profiles / "work.profile").write_bytes(profile_bytes("work"))
    if len(list(profiles.iterdir())) == 1:
        pytest.skip("the filesystem is case-insensitive")

    inventory = data.discover_profile_inventory()

    assert [entry.profile_id.value for entry in inventory.entries] == ["Work", "work"]
    assert data.open_profile("Work").name == "Work"
    assert data.open_profile("work").name == "work"


@pytest.mark.parametrize("outside", [False, True])
def test_symlinked_profiles_load(profile_modules, monkeypatch, tmp_path, outside):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    target = (tmp_path if outside else profiles) / "target"
    target.write_bytes(profile_bytes("linked"))
    (profiles / "linked.profile").symlink_to(target)

    inventory = data.discover_profile_inventory()

    assert [entry.profile_id.value for entry in inventory.entries] == ["linked"]
    assert data.open_profile("linked").profile_id == ProfileId("linked")


def test_broken_symlink_is_a_diagnostic(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    (profiles / "gone.profile").symlink_to(tmp_path / "missing")

    inventory = data.discover_profile_inventory()

    assert inventory.entries == ()
    assert [diagnostic.kind for diagnostic in inventory.diagnostics] == [data.ProfileDiagnosticKind.NOT_REGULAR_FILE]


def test_open_rejects_paths_and_accepts_unicode_names(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    composed = unicodedata.normalize("NFC", "Työ")
    path = profiles / f"{composed}.profile"
    path.write_bytes(profile_bytes(composed))

    assert data.open_profile("../outside") is None
    assert data.open_profile(str(path)) is None
    assert data.open_profile(composed).profile_id == ProfileId(composed)
    assert data.open_profile(ProfileId(composed)).profile_id == ProfileId(composed)


def test_decomposed_unicode_filename_loads(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    decomposed = unicodedata.normalize("NFD", "Työ")
    (profiles / f"{decomposed}.profile").write_bytes(profile_bytes(decomposed))

    assert [profile.name for profile in data.list_profiles()] == [decomposed]


def test_rename_source_lookup_uses_original_id(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    (profiles / "Original.profile").write_bytes(profile_bytes("Original", b"hotkey=control+x\n"))

    source = data.open_profile(ProfileId("Original"))

    assert source.hk_binding == ("control", "x")
    assert data.open_profile(ProfileId("Renamed")) is None


def test_delete_uses_loaded_content_and_rejects_replacement(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "Work.profile"
    original = profile_bytes("Work", b"hotkey=control+x\n")
    replacement = profile_bytes("Work", b"hotkey=control+y\n")
    path.write_bytes(original)
    original_stat = path.stat()
    loaded = data.open_profile(ProfileId("Work"))
    path.write_bytes(replacement)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    with pytest.raises(data.ManagedPathError):
        data.delete_managed_profile(loaded)

    assert path.read_bytes() == replacement


def test_deleting_a_symlinked_profile_removes_only_the_link(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    dotfile = tmp_path / "dotfiles" / "Work.profile"
    dotfile.parent.mkdir()
    dotfile.write_bytes(profile_bytes("Work"))
    link = profiles / "Work.profile"
    link.symlink_to(dotfile)
    loaded = data.open_profile(ProfileId("Work"))

    data.delete_managed_profile(loaded)

    assert not link.is_symlink()
    assert dotfile.read_bytes() == profile_bytes("Work")


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

    # The editable name field can hold anything; it never becomes an identity.
    with pytest.raises(ProfileIdError):
        ProfileId.parse("../outside")
    selected = data.managed_profile_for_selection(loaded, ProfileId("Work"))
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


def test_malformed_profile_is_deleted_when_confirmed(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "broken.profile"
    path.write_bytes(profile_bytes("broken", b"delay=not-a-number\n"))
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: True)

    assert data.list_profiles() == []
    assert not path.exists()


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


def test_loading_a_read_only_profile_never_writes(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "saved.profile"
    original = profile_bytes("other")
    path.write_bytes(original)
    path.chmod(0o444)
    prompts = []
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: prompts.append(args) or True)

    assert [profile.name for profile in data.list_profiles()] == ["saved"]
    assert data.open_profile("saved").name == "saved"
    assert prompts == []
    assert path.read_bytes() == original


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions, not root")
def test_unreadable_profile_is_diagnostic_without_deletion_prompt(profile_modules, monkeypatch, tmp_path):
    data, _ = profile_modules
    profiles = prepare(data, monkeypatch, tmp_path)
    path = profiles / "saved.profile"
    path.write_bytes(profile_bytes("saved"))
    path.chmod(0)
    prompts = []
    monkeypatch.setattr(data, "show_message_dialog", lambda *args, **kwargs: prompts.append(args) or True)

    inventory = data.discover_profile_inventory()
    profiles_listed = data.list_profiles()
    path.chmod(0o644)

    assert inventory.entries == ()
    assert inventory.diagnostics[0].kind is data.ProfileDiagnosticKind.IO_ERROR
    assert profiles_listed == []
    assert prompts == []
    assert path.read_bytes() == profile_bytes("saved")


@pytest.mark.parametrize(
    "setting",
    [b"diagonal_inches=0;24\n", b"zoom=\n", b"align=\n"],
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
