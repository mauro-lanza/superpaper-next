"""Build the Superpaper PyInstaller one-file binary.

Usage:
    python release-tooling/make-pyinstaller-build.py [testing|dist]

On macOS it builds dist/Superpaper.app and releases/Superpaper-<version>-macos-arm64.dmg.
The build-type argument is required only on Windows:
    testing  keep the console window (shows debug output)
    dist     hide the console window (--noconsole), for release builds

WARNING: The Windows code path has not yet been run on a Windows machine. The
modernization was verified only via command-capture tests on Linux; validate a
real Windows build before relying on it for a release.
"""

import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ENTRY_POINT = "superpaper/__main__.py"
WINDOWS_ICON = r".\superpaper\resources\superpaper.ico"
VERSION_FILE = Path("superpaper/__version__.py")
MACOS_ICON_PNG = Path("superpaper/resources/superpaper.png")
MACOS_BUNDLE_ID = "io.github.hhannine.Superpaper"
BUILD_DIR = Path("build")
DIST_DIR = Path("dist")
RELEASES_DIR = Path("releases")


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

    if system == "Darwin":
        build_macos_dmg()
        return

    print(f"Running on currently unsupported or untested OS: {system}")
    sys.exit(1)


def build_macos_dmg():
    """Build the unsigned dist/Superpaper.app and package it as releases/Superpaper-<version>-macos-arm64.dmg."""
    version = re.search(r'^__version__ = "(.*)"', VERSION_FILE.read_text(), re.MULTILINE).group(1)
    iconset = BUILD_DIR / "Superpaper.iconset"
    icns = BUILD_DIR / "Superpaper.icns"
    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir(parents=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            run_quiet(["sips", "-z", str(size * scale), str(size * scale), str(MACOS_ICON_PNG), "--out", str(iconset / name)])
    run_quiet(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)])

    run(
        [
            "pyinstaller", "--noconfirm", "--clean", "--windowed", "--name", "Superpaper",
            "--osx-bundle-identifier", MACOS_BUNDLE_ID, "--icon", str(icns),
            "--add-data", f"superpaper/resources{os.pathsep}superpaper/resources",
            "--exclude-module", "tkinter", "--exclude-module", "_tkinter",
            ENTRY_POINT,
        ]
    )  # fmt: skip

    app = DIST_DIR / "Superpaper.app"
    plist_path = app / "Contents" / "Info.plist"
    plist = plistlib.loads(plist_path.read_bytes())
    plist.update({"LSUIElement": True, "CFBundleShortVersionString": version, "CFBundleVersion": version})
    plist_path.write_bytes(plistlib.dumps(plist))
    # install_dir() resolves resources relative to Contents; PyInstaller puts them in Contents/Resources.
    (app / "Contents" / "superpaper").symlink_to("Resources/superpaper")
    # Editing Info.plist invalidates PyInstaller's ad-hoc signature, which Apple Silicon requires.
    run_quiet(["codesign", "--force", "--deep", "--sign", "-", str(app)])

    staging = BUILD_DIR / "dmg-staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copytree(app, staging / app.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications")
    RELEASES_DIR.mkdir(exist_ok=True)
    dmg = RELEASES_DIR / f"Superpaper-{version}-macos-arm64.dmg"
    dmg.unlink(missing_ok=True)
    run_quiet(["hdiutil", "create", "-volname", "Superpaper", "-srcfolder", str(staging), "-format", "UDZO", str(dmg)])
    print(f"make-pyinstaller-build: Wrote {dmg}")


def run_quiet(cmd):
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
