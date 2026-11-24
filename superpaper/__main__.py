"""
Superpaper is a cross-platform multi monitor wallpaper manager.

Written by Henri Hänninen.
"""

import os
import sys

from superpaper import cli, desktop
from superpaper.paths import install_dir, resolve_paths


def main() -> int:
    """Runs the tray applet if no command line arguments are passed, the command line otherwise."""
    current = desktop.current()
    paths = resolve_paths(os.environ, current.default_dirs(os.environ, install_dir()))
    return cli.run(sys.argv[1:], paths, current)


if __name__ == "__main__":
    sys.exit(main())
