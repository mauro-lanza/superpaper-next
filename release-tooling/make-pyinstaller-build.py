"""Build the Superpaper PyInstaller one-file binary.

Usage:
    python release-tooling/make-pyinstaller-build.py [testing|dist]

The build-type argument is required only on Windows:
    testing  keep the console window (shows debug output)
    dist     hide the console window (--noconsole), for release builds
"""

import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = REPO_ROOT / "superpaper" / "__main__.py"
WINDOWS_ICON = REPO_ROOT / "superpaper" / "resources" / "superpaper.ico"
DIST_DIR = REPO_ROOT / "dist"
WORK_DIR = REPO_ROOT / "build" / "pyinstaller" / "work"
SPEC_DIR = REPO_ROOT / "build" / "pyinstaller" / "spec"


def run(cmd):
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)
    print("make-pyinstaller-build: Build finished.")


def ensure_windows_gui_dependencies():
    try:
        import wx  # noqa: F401
    except ImportError:
        print(
            "ERROR: wxPython is not installed in this Python environment."
            " Install it before building Windows releases with:\n"
            "    python -m pip install wxPython>=4.2.5\n"
            "or\n"
            "    python -m pip install -e .[gui]"
        )
        sys.exit(1)


def main():
    system = platform.system()

    if system == "Linux":
        cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--name", "superpaper"]
        cmd.extend(["--distpath", str(DIST_DIR), "--workpath", str(WORK_DIR), "--specpath", str(SPEC_DIR)])
        cmd.append(str(ENTRY_POINT))
        run(cmd)
        return

    if system == "Windows":
        ensure_windows_gui_dependencies()
        build_type = sys.argv[1] if len(sys.argv) == 2 else None
        if build_type not in ("testing", "dist"):
            print("A build type must be passed as the only argument: 'testing' or 'dist'.")
            sys.exit(1)
        cmd = [sys.executable, "-m", "PyInstaller", "--onefile"]
        if build_type == "dist":
            cmd.append("--noconsole")
        cmd.extend(["--distpath", str(DIST_DIR), "--workpath", str(WORK_DIR), "--specpath", str(SPEC_DIR)])
        cmd += [
            "--name",
            "superpaper",
            "-i",
            str(WINDOWS_ICON),
            "--hidden-import",
            "wx",
            "--hidden-import",
            "wx.adv",
            str(ENTRY_POINT),
        ]
        run(cmd)
        return

    print(f"Running on currently unsupported or untested OS: {system}")
    sys.exit(1)


if __name__ == "__main__":
    main()
