"""Everything outside the wx UI must import without optional or platform-native packages,
and importing must not touch the filesystem.

This is the one structural test. It runs in a fresh interpreter so that nothing an
earlier test imported can mask a failure, and it pretends to be a KDE session because
that is where an environment-dependent import once crashed every entry point.
"""

import os
import subprocess
import sys

HEADLESS_MODULES = (
    "superpaper.__main__",
    "superpaper.cli",
    "superpaper.data",
    "superpaper.desktop",
    "superpaper.desktop.kde",
    "superpaper.desktop.linux",
    "superpaper.desktop.process",
    "superpaper.desktop.spanmode",
    "superpaper.files",
    "superpaper.message_dialog",
    "superpaper.paths",
    "superpaper.perspective",
    "superpaper.profile_id",
    "superpaper.render",
    "superpaper.render_cache",
    "superpaper.settings",
    "superpaper.sni_tray",
    "superpaper.sp_logging",
    "superpaper.sp_platform",
    "superpaper.wallpaper_processing",
)


def test_headless_modules_import_on_kde_without_optional_packages_and_create_nothing(tmp_path):
    env = dict(os.environ)
    env.update(
        HOME=str(tmp_path),
        XDG_CONFIG_HOME=str(tmp_path / "config"),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        DESKTOP_SESSION="plasma",
        KDE_FULL_SESSION="true",
        XDG_SESSION_DESKTOP="KDE",
    )
    # A None entry in sys.modules makes the import fail exactly as if the package
    # were not installed, even on machines where it is.
    script = "\n".join(
        [
            "import sys",
            "sys.modules['wx'] = None",
            "sys.modules['dbus'] = None",
            *(f"import {module}" for module in HEADLESS_MODULES),
        ]
    )

    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
