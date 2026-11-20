# Releasing

How to build and publish Superpaper Next artifacts. Metadata and dependencies
come from `pyproject.toml`.

## PyPI (wheel + sdist)

The project is managed with [uv](https://docs.astral.sh/uv/):

```sh
# Build the wheel and sdist into dist/
uv build

# Sanity-check the built artifacts before uploading
uvx twine check dist/*

# Upload to PyPI (needs credentials / a PyPI token)
uv publish
```

Classic equivalents without uv:

```sh
python3 -m build
twine check dist/*
python3 -m twine upload dist/*
```

## Linux AppImage

The AppImage is the primary published Linux artifact. It has its own
reproducible, host-isolating build under
[`release-tooling/appimage/`](../release-tooling/appimage/README.md).

## macOS (Apple Silicon dmg)

Run from the repository root on an Apple Silicon Mac:

```sh
uv run --group build --extra gui python release-tooling/make-pyinstaller-build.py
```

This builds `dist/Superpaper.app` (a menu-bar-only app, no Dock icon) and packages it as
`releases/Superpaper-<version>-macos-arm64.dmg`. The `.icns` icon is generated from
`superpaper/resources/superpaper.png` at build time.

The app is only ad-hoc signed, not signed with an Apple Developer ID or notarized. Users
open it with right-click → Open, or run `xattr -dr com.apple.quarantine /Applications/Superpaper.app`.

The `macOS` workflow builds the dmg on pushes to master, `v*` tags, pull requests touching
the desktop/build paths and manual runs, and uploads it as a workflow artifact. Attach it to the GitHub release by hand.

## Windows (exe + installer)

> Not currently published by this fork; see the upstream releases page. The
> build script has not been run on Windows.

Run from the repository root on Windows:

```sh
python release-tooling/make-windows-release.py
```

This builds the PyInstaller one-file exe, assembles the portable zip, and
compiles the Inno Setup installer (`iscc` must be on `PATH`).
