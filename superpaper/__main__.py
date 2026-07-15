#!/usr/bin/env python3
"""
Superpaper is a cross-platform multi monitor wallpaper manager.

Written by Henri Hänninen.
"""

# __all__ to be set at some point. Defines the APIs of the module(s).
__author__ = "Henri Hänninen"

import sys

from superpaper.spanmode import set_spanmode


def main():
    """Runs tray applet if no command line arguments are passed, CLI parsing otherwise."""
    set_spanmode()
    if len(sys.argv) <= 1:
        from superpaper.tray import tray_loop

        tray_loop()
    else:
        from superpaper.cli import cli_logic

        cli_logic()


if __name__ == "__main__":
    main()
