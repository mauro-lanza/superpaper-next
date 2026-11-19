"""Golden-file snapshots of the files a GUI scenario writes, step by step.

A step's files are normalised (see ``Snapshots.replace``) and compared with the files
committed under ``snapshots/<scenario>/<step>/``. Run with SUPERPAPER_UPDATE_SNAPSHOTS=1 to
rewrite the goldens, then review the diff.
"""

import difflib
import os
import shutil
from pathlib import Path

GOLDEN = Path(__file__).parent / "snapshots"
UPDATE_VARIABLE = "SUPERPAPER_UPDATE_SNAPSHOTS"


class Snapshots:
    def __init__(self, scenario):
        self.directory = GOLDEN / scenario
        self.updating = os.environ.get(UPDATE_VARIABLE) == "1"
        self.replacements = []
        self.steps = []
        if self.updating:
            shutil.rmtree(self.directory, ignore_errors=True)

    def replace(self, text, placeholder):
        """Write ``placeholder`` wherever ``text`` (a tmp path, a layout key) is in a file."""
        self.replacements.append((text, placeholder))

    def take(self, step, files):
        """Compare ``files`` (golden name -> path, missing paths skipped) with the step's goldens."""
        self.steps.append(step)
        name = f"{len(self.steps):02d}-{step}"
        taken = {}
        for golden_name, path in files.items():
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for old, new in self.replacements:
                    text = text.replace(old, new)
                taken[golden_name] = text
        target = self.directory / name
        if self.updating:
            for golden_name, text in taken.items():
                (target / golden_name).parent.mkdir(parents=True, exist_ok=True)
                (target / golden_name).write_text(text, encoding="utf-8")
            target.mkdir(parents=True, exist_ok=True)
            return
        expected = {
            path.relative_to(target).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(target.rglob("*"))
            if path.is_file()
        }
        if taken == expected:
            return
        lines = []
        if taken.keys() != expected.keys():
            lines.append(f"files: golden {sorted(expected)}, actual {sorted(taken)}")
        for golden_name in sorted(taken.keys() | expected.keys()):
            lines.extend(
                difflib.unified_diff(
                    expected.get(golden_name, "").splitlines(),
                    taken.get(golden_name, "").splitlines(),
                    f"golden/{name}/{golden_name}",
                    f"actual/{name}/{golden_name}",
                    lineterm="",
                )
            )
        message = f"step {name} differs from its snapshot ({UPDATE_VARIABLE}=1 rewrites it):\n" + "\n".join(lines)
        raise AssertionError(message)
