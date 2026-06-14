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
