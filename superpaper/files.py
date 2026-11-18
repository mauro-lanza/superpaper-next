"""Durable replacement of the files Superpaper owns: profiles, settings, pointers.

A reader must only ever see the old content or the new content, never a mix. New
content therefore goes to a temporary file beside the target, is flushed to disk, and
is renamed over the target in one step.
"""

import contextlib
import os
import secrets
import shutil
from pathlib import Path


def write_atomically(path: Path, content: bytes) -> None:
    """Replace the content of ``path`` in one step.

    A symlinked ``path`` is written through to its target, so a file kept in a dotfile
    repository and linked into place stays linked. An existing target keeps its
    permissions; a new one gets the mode the user's umask implies.
    """
    target = path.resolve() if path.is_symlink() else path
    temporary = target.with_name(f".superpaper-{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(temporary, flags, 0o666)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        with contextlib.suppress(FileNotFoundError):
            shutil.copymode(target, temporary)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
