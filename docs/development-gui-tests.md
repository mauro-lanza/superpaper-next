# Running GUI tests

The tests in `tests/gui` drive the real wx windows (tray application, editor, dialogs,
hotkey bindings) on a display. They carry the `gui` marker and are deselected by default, so
`uv run pytest` and CI don't need wxPython.

```sh
uv run pytest -m gui
```

They need wxPython importable and a display (`DISPLAY` or `WAYLAND_DISPLAY`); without
either, every GUI test is skipped with the reason. Windows open briefly on the current
desktop. Nothing touches your configuration or wallpaper: each test uses scratch
directories, a fixed pair of monitors, a recording stand-in for the system hotkeys and a
`true {image}` wallpaper command.

To keep the windows off your desktop, run under a virtual display:

```sh
xvfb-run -a uv run pytest -m gui
```

## Getting wxPython

wxPython has no PyPI wheel for Linux, and `uv sync --extra gui` builds it from source,
which takes a long time. Instead:

- install your distribution's package (see [installation-linux](./installation-linux.md))
  and run the tests with a venv that sees it, or
- install a prebuilt wheel from the extras index for your distribution:
  `uv pip install -f https://extras.wxpython.org/wxPython4/extras/linux/gtk3/<distro> wxPython`
  (for example `ubuntu-24.04`), or
- point `PYTHONPATH` at an existing wxPython build.
