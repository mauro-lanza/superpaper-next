import os
import sys

import pytest

from superpaper.files import write_atomically


@pytest.fixture
def directory(tmp_path):
    path = tmp_path / "files"
    path.mkdir()
    return path


def test_creates_and_replaces_content(directory):
    path = directory / "settings"

    write_atomically(path, b"first")
    write_atomically(path, b"second")

    assert path.read_bytes() == b"second"
    assert os.listdir(directory) == ["settings"]


def test_writes_through_a_symlink_and_keeps_it(directory):
    target = directory / "dotfiles" / "work.profile"
    target.parent.mkdir()
    target.write_bytes(b"old")
    link = directory / "work.profile"
    link.symlink_to(target)

    write_atomically(link, b"new")

    assert link.is_symlink()
    assert target.read_bytes() == b"new"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_keeps_the_permissions_of_the_file_it_replaces(directory):
    path = directory / "work.profile"
    path.write_bytes(b"old")
    path.chmod(0o640)

    write_atomically(path, b"new")

    assert path.stat().st_mode & 0o777 == 0o640


def test_failed_replacement_leaves_no_temporary_file(directory):
    (directory / "running_profile").mkdir()

    with pytest.raises(OSError):
        write_atomically(directory / "running_profile", b"work")

    assert os.listdir(directory) == ["running_profile"]
