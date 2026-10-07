"""The saved display layouts: written in one step, in the encoding older versions read."""

import pytest

from superpaper import display_store, files

LAYOUT = display_store.SavedLayout(
    ppi_norm_offsets=[(0, 0), (1920, 0)],
    bezel_mms=[(4.5, 0.0), (0.0, 0.0)],
    user_diagonal_inches=None,
    use_perspective=True,
    default_perspective="desk",
)
DESK = {
    "central_disp": 0,
    "viewer_pos": [0.0, 0.0, 2000.0],
    "swivels": [(0, 0.0, 0.0, 0.0)],
    "tilts": [(0.0, 0.0, 0.0)],
}


def test_nothing_saved_reads_as_nothing(tmp_path):
    assert display_store.read_layout(tmp_path, "123") is None
    assert display_store.read_perspectives(tmp_path, "123") == {}


def test_a_layout_reads_back_as_it_was_saved(tmp_path):
    display_store.write_layout(tmp_path, "123", LAYOUT)
    display_store.write_layout(tmp_path, "456", LAYOUT)

    assert display_store.read_layout(tmp_path, "123") == LAYOUT
    assert display_store.read_layout(tmp_path, "456") == LAYOUT


def test_a_failed_save_leaves_the_saved_layouts_as_they_were(tmp_path, monkeypatch):
    display_store.write_layout(tmp_path, "123", LAYOUT)
    saved = (tmp_path / display_store.LAYOUTS_FILE).read_bytes()

    def fail(source, target):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(files.os, "replace", fail)
    with pytest.raises(OSError, match="No space left"):
        display_store.write_layout(tmp_path, "456", LAYOUT)

    assert (tmp_path / display_store.LAYOUTS_FILE).read_bytes() == saved
    assert sorted(path.name for path in tmp_path.iterdir()) == [display_store.LAYOUTS_FILE]


def test_the_files_use_the_encoding_older_versions_read(tmp_path, monkeypatch):
    # Python's default text encoding, which is the ANSI code page on Windows.
    monkeypatch.setattr(display_store.locale, "getpreferredencoding", lambda do_setlocale=True: "cp1252")

    display_store.write_perspectives(tmp_path, "123", {"café": DESK})

    assert (tmp_path / "123.persp").read_bytes().startswith(b"[caf\xe9]\n")
    assert display_store.read_perspectives(tmp_path, "123") == {"café": DESK}
