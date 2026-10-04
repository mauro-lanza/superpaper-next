# Development on macOS

> macOS support is source-only and unvalidated. See
> [`ISSUES.md`](../ISSUES.md) (#113, #153) for the open work.

## Requirements

- [Python 3.14+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/) (recommended; the project is managed with it)

## Setup

```sh
git clone https://github.com/mauro-lanza/superpaper-next.git
cd superpaper-next
uv sync --group dev --extra gui
```

Runtime dependencies (Pillow, screeninfo, numpy, wxPython) come from
`pyproject.toml`; there is no separate requirements file. The `gui` extra pulls
in wxPython, which installs from PyPI on macOS.

## Known gaps

- **PyObjC is not declared as a dependency.** `wallpaper_processing.py` imports
  `AppKit` and `Foundation` unconditionally on darwin, so a plain
  `pip install superpaper` produces a package that fails at import. Install it
  manually for now:

  ```sh
  uv pip install pyobjc
  ```

- **Config is written into the installed package directory.** `sp_paths.py`
  falls through to the portable (executable-relative) branch on macOS rather
  than using `~/Library/Application Support`.

Both are tracked under #113.

## Running

```sh
uv run superpaper        # tray applet
uv run superpaper --help # CLI
uv run pytest            # tests
```
