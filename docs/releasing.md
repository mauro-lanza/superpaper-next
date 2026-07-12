# Releasing

How to build and publish Superpaper Next artifacts. Metadata and dependencies
come from `pyproject.toml` (see the comments there); there is no `setup.py`.

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

## Windows (exe + installer)

> Not currently published by this fork; see the upstream releases page. The
> tooling is kept for reference and has not yet been re-tested on Windows.

Run from the repository root on Windows:

```sh
python release-tooling/make-windows-release.py
```

This builds the PyInstaller one-file exe, assembles the portable zip, and
compiles the Inno Setup installer (`iscc` must be on `PATH`).
