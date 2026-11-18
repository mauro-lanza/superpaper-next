"""Run host programs: in the host's environment, with an optional time limit, and with
failures returned as values."""

import os
import subprocess
import sys
from dataclasses import dataclass

# How AppRun saves the host's original environment values; see release-tooling/appimage/AppRun.
_HOSTENV_PREFIX = "SUPERPAPER_HOSTENV_"
_HOSTENV_UNSET = "__SUPERPAPER_UNSET__"

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


def host_spawn_env() -> dict[str, str]:
    """Return the environment for host programs, undoing the AppImage and PyInstaller overrides.

    Outside a bundle this is a plain copy of the current environment.
    """
    env = dict(os.environ)

    # A spawned /bin/sh would otherwise load the bundled libreadline and die (xdg-open exit 127).
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

    for key in [k for k in env if k.startswith(_HOSTENV_PREFIX)]:
        target = key[len(_HOSTENV_PREFIX) :]
        saved = env.pop(key)
        if saved == _HOSTENV_UNSET:
            env.pop(target, None)
        else:
            env[target] = saved
    return env
