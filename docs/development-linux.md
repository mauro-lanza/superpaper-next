# Development on Linux

## Requirements

- [Python 3.14+](https://www.python.org/downloads/) and [uv](https://docs.astral.sh/uv/)
- Build tools and headers for `dbus-python`, which PyPI ships only as a source
  distribution (needs a C compiler, `pkg-config`, and the D-Bus and GLib headers):

  | Distro family | Packages |
  | --- | --- |
  | Arch / CachyOS | `sudo pacman -S base-devel pkgconf dbus glib2` |
  | Debian / Ubuntu | `sudo apt install build-essential pkg-config libdbus-1-dev libglib2.0-dev` |
  | Fedora | `sudo dnf install gcc pkgconf-pkg-config dbus-devel glib2-devel` |

## Setup

```sh
git clone https://github.com/mauro-lanza/superpaper-next.git
cd superpaper-next
uv sync --inexact --group dev --extra linux
uv pip install https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-24.04/wxpython-4.2.5-cp314-cp314-linux_x86_64.whl
```

wxPython is installed from a prebuilt wheel instead of the `gui` extra because
PyPI has only a source distribution for Linux, which takes very long to build.
This is the same wheel CI uses (`.github/workflows/ci.yml`, `gui` job). It is built
for Ubuntu 24.04 but also runs on newer distros with the GTK 3 runtime (used on
CachyOS).

Always pass `--inexact` to `uv sync`: a plain `uv sync` uninstalls the
wheel-installed wxPython because it is not in the selected extras. `uv run` syncs
inexactly by default.

## Running

```sh
uv run superpaper         # tray applet
uv run superpaper --help  # CLI
```

## Tests and checks

```sh
uv run pytest             # tests
uv run pytest -m gui      # GUI tests
uv run ruff check
uv run ruff format --check
uv run ty check
```

GUI tests need a display; see [development-gui-tests.md](development-gui-tests.md).
The `.pre-commit-config.yaml` hooks run ruff and ty from `.venv`; enable them with
`uv run pre-commit install`.
