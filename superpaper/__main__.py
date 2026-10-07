#!/usr/bin/env python3
"""
Superpaper is a cross-platform multi monitor wallpaper manager.

Written by Henri Hänninen.
"""

# __all__ to be set at some point. Defines the APIs of the module(s).
__author__ = "Henri Hänninen"

import os
import sys

from superpaper.paths import ensure_dirs, resolve_paths
from superpaper.spanmode import set_spanmode


def main():
    """Runs tray applet if no command line arguments are passed, CLI parsing otherwise.

    Desktop span mode is configured, and Superpaper's directories created, only on the
    way to setting a wallpaper, so that `--help` or a mistyped option changes nothing.
    """
    paths = resolve_paths(os.environ, sys.platform)
    if len(sys.argv) <= 1:
        from superpaper.cli import start_tray

        ensure_dirs(paths)
        set_spanmode()
        start_tray(paths)
    else:
        from superpaper.cli import cli_logic

        cli_logic(paths)


if __name__ == "__main__":
    main()
