"""Run host programs: in the host's environment, with an optional time limit, and with
failures returned as values."""

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

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


def run_hook(script: Path, image: str, sources: Sequence[str]) -> Result:
    """Run the user's script after a wallpaper change, with the image and then each source
    image as its own argument."""
    return run(["python3", str(script), image, *sources])


def host_spawn_env() -> dict[str, str]:
    """Return the environment for host programs, undoing the AppImage and PyInstaller overrides.

    Outside a bundle this is a plain copy of the current environment.
    """
    return _restore_saved_vars(_restore_library_paths(os.environ))


def _restore_library_paths(environ: Mapping[str, str]) -> dict[str, str]:
    """``environ`` with the library paths the host expects: the saved originals, else without the bundle's.

    A spawned /bin/sh would otherwise load the bundled libreadline and die (xdg-open exit 127).
    """
    env = dict(environ)
    meipass = getattr(sys, "_MEIPASS", None)
    bundle_root = env.get("APPDIR")
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        original = env.pop(var + "_ORIG", None)
        current = env.get(var)
        if original is not None:
            value = original
        elif current:
            host_paths = [
                path
                for path in current.split(os.pathsep)
                if path and path != meipass and not (bundle_root and Path(path).is_relative_to(bundle_root))
            ]
            value = os.pathsep.join(host_paths)
        else:
            continue
        if value:
            env[var] = value
        else:
            env.pop(var, None)
    return env


def _restore_saved_vars(environ: Mapping[str, str]) -> dict[str, str]:
    """``environ`` with the variables AppRun saved put back, or unset where the host had none."""
    env = {key: value for key, value in environ.items() if not key.startswith(_HOSTENV_PREFIX)}
    for key, saved in environ.items():
        if not key.startswith(_HOSTENV_PREFIX):
            continue
        target = key.removeprefix(_HOSTENV_PREFIX)
        if saved == _HOSTENV_UNSET:
            env.pop(target, None)
        else:
            env[target] = saved
    return env
