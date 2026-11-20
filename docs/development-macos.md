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

Runtime dependencies (Pillow, screeninfo, numpy, and PyObjC's Cocoa and Quartz
frameworks on macOS) come from `pyproject.toml`; there is no separate requirements
file. The `gui` extra pulls in wxPython, which installs from PyPI on macOS.

## Known gaps

- **Hotkeys are unsupported.** system_hotkey has no macOS backend, so it is not
  installed on macOS and hotkeys stay off.

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
