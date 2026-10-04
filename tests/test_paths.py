import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="XDG base directories are a Linux convention")
def test_first_run_creates_missing_xdg_base_directories(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"XDG_CONFIG_HOME", "XDG_CACHE_HOME", "SNAP_USER_DATA", "SNAP_USER_COMMON"}
    }
    env["HOME"] = str(home)

    result = subprocess.run(
        [sys.executable, "-c", "import superpaper.sp_paths"], env=env, capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert (home / ".config" / "superpaper" / "profiles").is_dir()
    assert (home / ".cache" / "superpaper" / "temp").is_dir()
