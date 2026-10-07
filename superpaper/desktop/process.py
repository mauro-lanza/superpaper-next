"""Run host programs: in the host's environment, with an optional time limit, and with
failures returned as values."""

import os
import subprocess
import sys
from dataclasses import dataclass

# Prefix AppRun uses to stash the host's original value of each environment
# variable it overrides for runtime isolation, plus the sentinel it stores when a
# variable was originally unset. See release-tooling/appimage/AppRun.
_HOSTENV_PREFIX = "SUPERPAPER_HOSTENV_"
_HOSTENV_UNSET = "__SUPERPAPER_UNSET__"

# Variables the AppImage launcher repoints at the bundled copies. Used as a
# fallback for AppImages built before AppRun started saving the originals.
_ISOLATION_VARS = (
    "XDG_DATA_DIRS",
    "GSETTINGS_BACKEND",
    "GSETTINGS_SCHEMA_DIR",
    "GIO_MODULE_DIR",
    "GDK_PIXBUF_MODULEDIR",
    "GDK_PIXBUF_MODULE_FILE",
    "FONTCONFIG_FILE",
)

# Seconds a helper that should return at once (gsettings, xfconf-query, feh) may take.
QUICK = 30


@dataclass(frozen=True, slots=True)
class Result:
    """How handing something to the host went."""

    problem: str | None = None
    """What went wrong, in words fit for the log; None when it worked."""
    output: str = ""
    """What the program printed, when its output was asked for."""

    @property
    def ok(self) -> bool:
        return self.problem is None


def run(command: list[str], *, timeout: float | None = None, capture_output: bool = False) -> Result:
    """Run ``command`` in the host's environment and wait for it to finish.

    Helpers that should return at once get a ``timeout``, so a hung one can't hold up
    later wallpaper changes; the user's own programs run for as long as they need.
    Standard error is kept for the problem report.
    """
    name = os.path.basename(command[0])
    try:
        completed = subprocess.run(
            command,
            env=host_spawn_env(),
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return Result(f"{name} is not installed.")
    except subprocess.TimeoutExpired:
        return Result(f"{name} did not finish within {timeout:g} seconds.")
    except OSError as error:
        return Result(f"{name} could not be run: {error}")
    if completed.returncode != 0:
        message = (completed.stderr or "").strip() or "no message"
        return Result(f"{name} failed with exit status {completed.returncode}: {message}")
    return Result(output=completed.stdout or "")


def host_spawn_env():
    """Return an environment dict for launching external host programs.

    The isolating AppImage launcher (AppRun) repoints XDG_DATA_DIRS, the
    GIO/GSettings backend, gdk-pixbuf and fontconfig at the bundled copies so the
    GUI can't pick up version-mismatched host data. Those overrides must not be
    inherited by host helpers we spawn (xdg-open, gsettings, the file manager,
    custom commands); with them, e.g. xdg-open can't find the host file manager
    or mime associations and fails with exit code 4.

    AppRun saves each original value as ``SUPERPAPER_HOSTENV_<VAR>`` (or the unset
    sentinel), which we restore here. For AppImages built before that change, fall
    back to dropping the bundled isolation variables so spawned tools use the
    host's defaults. Separately, PyInstaller's bootloader repoints
    ``LD_LIBRARY_PATH`` at the bundled libs (saving the original in
    ``LD_LIBRARY_PATH_ORIG``); that is restored too, otherwise a spawned ``/bin/sh``
    loads the bundled libreadline and dies with an undefined-symbol error (so
    xdg-open exits 127). Outside the AppImage this is a plain copy of the current
    environment.
    """
    env = dict(os.environ)

    # PyInstaller points LD_LIBRARY_PATH (and macOS DYLD_LIBRARY_PATH) at the
    # frozen app's bundled libs and stashes the pre-launch value in *_ORIG. Host
    # programs must not load those bundled libs (built against an older glibc /
    # readline), so restore the saved original, or scrub the bundle paths if no
    # original was saved.
    meipass = getattr(sys, "_MEIPASS", None)
    bundle_root = env.get("APPDIR")
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        orig = env.pop(var + "_ORIG", None)
        if orig is not None:
            if orig:
                env[var] = orig
            else:
                env.pop(var, None)
            continue
        current = env.get(var)
        if not current:
            continue
        kept = [
            p
            for p in current.split(os.pathsep)
            if p and p != meipass and not (bundle_root and p.startswith(bundle_root))
        ]
        if kept:
            env[var] = os.pathsep.join(kept)
        else:
            env.pop(var, None)

    saved_keys = [k for k in env if k.startswith(_HOSTENV_PREFIX)]
    if saved_keys:
        for key in saved_keys:
            target = key[len(_HOSTENV_PREFIX) :]
            saved = env.pop(key)
            if saved == _HOSTENV_UNSET:
                env.pop(target, None)
            else:
                env[target] = saved
        return env

    # Fallback: no saved originals, but if our bundled isolation vars are present
    # (XDG_DATA_DIRS points inside $APPDIR), drop them so child host programs fall
    # back to the host defaults instead of the AppDir copies.
    appdir = env.get("APPDIR")
    if appdir and env.get("XDG_DATA_DIRS", "").startswith(appdir):
        for var in _ISOLATION_VARS:
            env.pop(var, None)
    return env
