import importlib
import sys
from pathlib import Path

import pytest


def test_frozen_path_uses_executable_directory(monkeypatch, tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows-specific frozen path behavior")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "superpaper.exe"))

    import superpaper.sp_paths as sp_paths
    sp_paths = importlib.reload(sp_paths)

    assert sp_paths.PATH == str(tmp_path)
    assert sp_paths.CONFIG_PATH == str(tmp_path)
    assert sp_paths.TEMP_PATH == str(tmp_path / "temp")
    assert (tmp_path / "temp").is_dir()
