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

Runtime dependencies (Pillow, screeninfo, numpy, system_hotkey310) come from
`pyproject.toml`; there is no separate requirements file. The `gui` extra pulls
in wxPython, which installs from PyPI on macOS.

## Known gaps

- **PyObjC is not declared as a dependency.** `superpaper/desktop/macos.py` imports
  `AppKit` and `Foundation` unconditionally on darwin, so a plain
  `pip install superpaper` produces a package that fails at import. Install it
  manually:

  ```sh
  uv pip install pyobjc
  ```

The PyObjC gap is tracked under #113 in [`ISSUES.md`](../ISSUES.md).

## Where files live

On macOS settings and profiles live in `~/Library/Application Support/Superpaper`
and the cache in `~/Library/Caches/Superpaper`. Files an earlier version wrote
beside the program are not moved; copy them over by hand. `SUPERPAPER_CONFIG_HOME`
and `SUPERPAPER_CACHE_HOME` name other directories.

## Running

```sh
uv run superpaper        # tray applet
uv run superpaper --help # CLI
uv run pytest            # tests
```
