# Running GUI tests

The tests in `tests/gui` drive the real wx windows (tray application, editor, dialogs) on a display. They carry the `gui` marker and are deselected by default, so
`uv run pytest` doesn't need wxPython. CI runs them in a separate `gui` job under `xvfb-run`
with the wxPython wheel from the wxPython extras index.

```sh
uv run pytest -m gui
```

They need wxPython importable and a display (`DISPLAY` or `WAYLAND_DISPLAY`); without
either, every GUI test is skipped with the reason. Windows open briefly on the current
desktop. Nothing touches your configuration or wallpaper: each test uses scratch
directories, a fixed pair of monitors and a
`true {image}` wallpaper command.

To keep the windows off your desktop, run under a virtual display:

```sh
xvfb-run -a uv run pytest -m gui
```

## Writing tests

GUI tests cover wiring (widget, handler, session, store, files), dialog flows, field limits
and the preview. Rules that don't need a window belong in the headless tests. Open dialogs
through the editor's own handler with `gui_env.open_perspectives(editor)` or
`gui_env.open_browse(editor)`, which return the dialog instead of blocking, so a changed
constructor doesn't break the tests. Handlers such as `onSave` return nothing: assert on the
resulting files, store and session.

## Scenario snapshot tests

`tests/gui/test_scenario_*.py` click through the editor, the display band, the perspectives
dialog and the tray in order, and after each step compare the files that were written
(`display_systems.dat`, the `.persp` file, profiles, selections, the running-profile pointer)
with the goldens in `tests/gui/snapshots/<scenario>/<step>/`. Temporary paths and the layout
key are replaced by `<tmp>` and `<key>`; numbers are compared as written. Each scenario is
one test, since every step starts from the files the previous one left.

After a deliberate behaviour change, rewrite the goldens and review the diff:

```sh
SUPERPAPER_UPDATE_SNAPSHOTS=1 uv run pytest -m gui tests/gui/test_scenario_*.py
git diff tests/gui/snapshots
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
