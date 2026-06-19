"""Centralized operating-system detection for Superpaper.

Define the host OS as module-level constants so the rest of the codebase shares
a single source of truth instead of repeating ``platform.system()`` string
comparisons.

Note: these constants are intended for *runtime* branching. Conditional
``import`` statements for platform-native modules (e.g. ``dbus``, ``winreg``,
``AppKit``) must keep using a literal ``sys.platform == "..."`` comparison,
because static type checkers (pyright/mypy) only treat a branch as
platform-dead-code when they see that exact form. A derived boolean constant is
opaque to them and would re-trigger missing-import / possibly-unbound warnings.
"""

import sys

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform == "linux"


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
    host's defaults. Outside the AppImage this is a plain copy of the current
    environment.
    """
    import os

    env = dict(os.environ)

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
