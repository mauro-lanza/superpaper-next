# Superpaper AppImage build

Reproducible, host-isolated AppImage build for Linux. Fixes the launch failures
reported on modern distributions (issues #170, #164, #169).

## TL;DR

```sh
# from the repo root (use sudo if your user isn't in the docker group)
DOCKER="sudo docker" ./release-tooling/appimage/build.sh
# -> releases/Superpaper-<version>-x86_64.AppImage
```

## Why a container

An AppImage bakes in the build machine's glibc and the GTK/GLib/fontconfig
libraries present at build time. Two things then matter:

1. **glibc floor.** Building on a bleeding-edge host (Arch/CachyOS) yields a
   binary that won't start on older systems. Ubuntu 22.04 (glibc 2.35) gives a
   wide compatibility floor.
2. **Internal consistency.** The libraries PyInstaller bundles and the auxiliary
   GTK data we stage (gsettings schemas, gdk-pixbuf loaders, fonts) must match
   each other. Taking them all from the *same* Ubuntu 22.04 image guarantees
   that.

Building on the host where you test (e.g. CachyOS) would *hide* these bugs,
because the bundled libraries would happen to match the host. The container
build reproduces the real shipping conditions.

## Why the AppRun isolates the host

The shipped v2.3.0 AppImage bundled old GTK libs but still let GLib/GTK/
fontconfig reach out to the **host** at runtime. On newer hosts that version
skew broke each layer:

| Issue | Symptom | Cause | Fix in [`AppRun`](AppRun) |
|-------|---------|-------|---------------------------|
| #170 | GUI never appears | host gio module loaded into older bundled glib → `undefined symbol` | `GIO_MODULE_DIR` → empty bundled dir; no host modules loaded |
| #164 | core dump on launch | host gsettings schema missing the `antialiasing` key | `XDG_DATA_DIRS` → bundled tree only + `GSETTINGS_BACKEND=memory` + bundled compiled schemas |
| #169 | text renders as `[]` tofu | bundled libfontconfig too old to parse host's newer `/etc/fonts` | runtime-generated `FONTCONFIG_FILE` pointing at a bundled font |

The gdk-pixbuf loaders are handled by shipping an empty loader cache: Ubuntu's
`libgdk-pixbuf` compiles the png/jpeg loaders in, so the app's PNG icons render
from the built-ins while the empty cache stops the bundled library from scanning
the host's loader cache (which would reintroduce the same version skew).

## Files

- [`Dockerfile`](Dockerfile) — Ubuntu 22.04 build image (Python, wx/GTK runtime
  libs, schema/pixbuf/font tooling, `appimagetool`).
- [`build.sh`](build.sh) — single entry point. Host phase builds the image and
  runs the container; the `--in-container` phase (invoked automatically) does
  the PyInstaller build, AppDir assembly, GTK data staging and packaging.
- [`AppRun`](AppRun) — host-isolating launcher.
- [`io.github.hhannine.Superpaper.metainfo.xml`](io.github.hhannine.Superpaper.metainfo.xml)
  — AppStream metadata, staged into `usr/share/metainfo/`.

## Notes

- The AppDir layout matches Superpaper's frozen resource resolution
  (`PATH = dirname(dirname(exe))` in `superpaper/sp_paths.py`): the executable
  lives at `usr/bin/superpaper`, so resources are staged at
  `usr/superpaper/resources/`.
- **Icons.** The build renders the SVG master
  (`superpaper/resources/superpaper.svg`) into the hicolor theme: the scalable
  icon (`scalable/apps/superpaper.svg`) plus PNG buckets rendered natively with
  `rsvg-convert` (`{16,24,32,48,64,128,256}x.../apps/superpaper.png`). On first
  launch `AppRun` mirrors that set into `~/.local/share/icons/hicolor/` and
  writes a desktop entry with `Icon=superpaper` (a theme *name*, not an absolute
  path). This is what lets the Wayland title-bar/decoration icon resolve: KWin/Qt
  look the icon up by name through the theme and ignore loose
  `~/.local/share/icons/<name>.png` files and absolute paths. Set
  `SUPERPAPER_NO_INTEGRATION=1` to skip the integration.
- Releases must be built via this container (old base), **not** directly on a
  rolling-release host, or the glibc floor and version-skew bugs return.
- wxPython is installed from the prebuilt Ubuntu 22.04 wheel index
  (`extras.wxpython.org`); it has no universal manylinux wheel.
