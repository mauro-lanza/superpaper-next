"""Build the Windows release artifacts: PyInstaller exe, portable zip and Inno installer.

Run from the repository root:
    python release-tooling/make-windows-release.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRCPATH = REPO_ROOT / "superpaper"
DISTPATH = REPO_ROOT / "releases"
INNO_STUB = DISTPATH / "innostub"
DIST_EXE = REPO_ROOT / "dist" / "superpaper.exe"


def read_version():
    with (REPO_ROOT / "superpaper" / "__version__.py").open(encoding="utf-8") as verfile:
        for line in verfile:
            if "__version__" in line:
                ver_str = line.split("=")[1].strip().replace('"', "")
                print(f"Found version: {ver_str}")
                return ver_str
    print("Version not found, exiting build.")
    sys.exit(1)


def make_portable(dst_path):
    dst_path = Path(dst_path)
    portpath = dst_path / "superpaper-portable"
    portres = portpath / "superpaper" / "resources"
    portprof = portpath / "profiles"
    portexec = portpath / "superpaper.exe"

    portpath.mkdir(parents=True, exist_ok=True)
    portres.mkdir(parents=True, exist_ok=True)
    portprof.mkdir(parents=True, exist_ok=True)

    shutil.copytree(SRCPATH / "resources", portres, dirs_exist_ok=True)
    shutil.copytree(SRCPATH / "profiles-win", portprof, dirs_exist_ok=True)

    shutil.rmtree(INNO_STUB, ignore_errors=True)
    shutil.copytree(portpath, INNO_STUB)

    shutil.copy2(DIST_EXE, portexec)
    shutil.make_archive(str(portpath), "zip", str(dst_path), "superpaper-portable")


def run_inno_script(version_str):
    iscc = shutil.which("iscc")
    if iscc is None:
        print("Inno Setup Compiler (iscc) was not found on PATH.")
        sys.exit(1)
    subprocess.run(
        [iscc, str(REPO_ROOT / "release-tooling" / "inno-setup-script.iss"), f"/DMyAppVersion={version_str}"],
        check=True,
        cwd=REPO_ROOT,
    )


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
    ensure_windows_gui_dependencies()
    DISTPATH.mkdir(parents=True, exist_ok=True)
    version = read_version()
    dist_path = DISTPATH / version
    dist_path.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run([sys.executable, str(REPO_ROOT / "release-tooling" / "make-pyinstaller-build.py"), "dist"], check=True, cwd=REPO_ROOT)
    except subprocess.CalledProcessError:
        print("\nPyInstaller build FAILED.\n")
        sys.exit(1)
    print("\nPyInstaller build done.\n")

    make_portable(dist_path)
    print("Portable package build done.")

    run_inno_script(version)

    print("Release built and packaged.")


if __name__ == "__main__":
    main()
