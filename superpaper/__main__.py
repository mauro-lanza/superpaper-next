"""
Superpaper is a cross-platform multi monitor wallpaper manager.

Written by Henri Hänninen.
"""

import os
import sys

from superpaper import cli, desktop
from superpaper.paths import resolve_paths


def main() -> int:
    """Runs the tray applet if no command line arguments are passed, the command line otherwise."""
    current = desktop.current()
    return cli.run(sys.argv[1:], resolve_paths(os.environ, current), current)


if __name__ == "__main__":
    sys.exit(main())
