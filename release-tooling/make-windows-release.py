"""Build the Windows release artifacts: PyInstaller exe, portable zip and Inno installer.

Run from the repository root:
    python release-tooling/make-windows-release.py

WARNING: This script has not yet been run on a Windows machine. The
modernization was verified only via command-capture tests on Linux; validate a
real Windows build (PyInstaller exe + Inno installer) before relying on it for
a release.
"""

import os
import shutil
import subprocess
import sys

SRCPATH = os.path.realpath("./superpaper")
DISTPATH = os.path.realpath("./releases/")
INNO_STUB = os.path.realpath("./releases/innostub")


def read_version():
    with open("superpaper/__version__.py") as verfile:
        for line in verfile:
            if "__version__" in line:
                ver_str = line.split("=")[1].strip().replace('"', "")
                print(f"Found version: {ver_str}")
                return ver_str
    print("Version not found, exiting build.")
    sys.exit(1)


def make_portable(dst_path):
    portpath = os.path.join(dst_path, "superpaper-portable")
    portres = os.path.join(portpath, "superpaper/resources")
    portprof = os.path.join(portpath, "profiles")
    portexec = os.path.join(portpath, "superpaper")
    # copy resources
    shutil.copytree(os.path.join(SRCPATH, "resources"), portres, dirs_exist_ok=True)
    # copy profiles
    shutil.copytree(os.path.join(SRCPATH, "profiles-win"), portprof, dirs_exist_ok=True)
    # copy exe-less structure to be used by innosetup
    shutil.copytree(portpath, INNO_STUB, dirs_exist_ok=True)
    # copy executable
    shutil.copy2("./dist/superpaper.exe", portexec)
    # zip it
    shutil.make_archive(portpath, "zip", dst_path, "superpaper-portable")


def run_inno_script(version_str):
    subprocess.run(
        ["iscc", "./release-tooling/inno-setup-script.iss", f"/DMyAppVersion={version_str}"],
        check=True,
    )


def main():
    os.makedirs(DISTPATH, exist_ok=True)
    version = read_version()
    dist_path = os.path.join(DISTPATH, version)
    os.makedirs(dist_path, exist_ok=True)

    # run pyinstaller build
    try:
        subprocess.run([sys.executable, "./release-tooling/make-pyinstaller-build.py", "dist"], check=True)
    except subprocess.CalledProcessError:
        print("\nPyInstaller build FAILED.\n")
        sys.exit(1)
    print("\nPyInstaller build done.\n")

    # copy binary, resources and examples into package structure
    make_portable(dist_path)
    print("Portable package build done.")

    # run inno installer compilation
    run_inno_script(version)

    print("Release built and packaged.")


if __name__ == "__main__":
    main()
