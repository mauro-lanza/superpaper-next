"""Build the Superpaper PyInstaller one-file binary.

Usage:
    python release-tooling/make-pyinstaller-build.py [testing|dist]

The build-type argument is required only on Windows:
    testing  keep the console window (shows debug output)
    dist     hide the console window (--noconsole), for release builds

WARNING: The Windows code path has not yet been run on a Windows machine. The
modernization was verified only via command-capture tests on Linux; validate a
real Windows build before relying on it for a release.
"""

import platform
import subprocess
import sys

ENTRY_POINT = "superpaper/__main__.py"
WINDOWS_ICON = r".\superpaper\resources\superpaper.ico"


def run(cmd):
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    print("make-pyinstaller-build: Build finished.")


def main():
    system = platform.system()

    if system == "Linux":
        run(["pyinstaller", "--onefile", "--name", "superpaper", ENTRY_POINT])
        return

    if system == "Windows":
        build_type = sys.argv[1] if len(sys.argv) == 2 else None
        if build_type not in ("testing", "dist"):
            print("A build type must be passed as the only argument: 'testing' or 'dist'.")
            sys.exit(1)
        cmd = ["pyinstaller", "--onefile"]
        if build_type == "dist":
            cmd.append("--noconsole")
        cmd += ["--name", "superpaper", "-i", WINDOWS_ICON, ENTRY_POINT]
        run(cmd)
        return

    print(f"Running on currently unsupported or untested OS: {system}")
    sys.exit(1)


if __name__ == "__main__":
    main()
