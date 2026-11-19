# Upstream Issues

Status of open issues from [hhannine/superpaper](https://github.com/hhannine/superpaper/issues) in this fork.

## Resolved In This Fork

- #140: starting with `--profile` applies the profile at once.
- #154: the tray icon is titled "Superpaper" instead of `__main__.py`.
- #158, #163: preview and apply share one planned batch, so the preview shows the image that is applied, and a source without images no longer crashes it.
- #168: Zorin OS is recognised, NumPy 2 is supported, and CLI errors are reported without GUI dialogs.
- #164, #169, #170: AppImage launch failures, fixed by the host-isolated build in `release-tooling/appimage/`. The builder compiles the Python 3.14 floor on Ubuntu 22.04 to keep its glibc compatibility.
- #162: the missing `setuptools` failure no longer applies to the packaging; Python 3.13 is outside the support policy below.
- #135: a missing wallpaper file does not retry forever. Persisted selections are validated as a whole: deleted files fall back to the configured sources, and incomplete per-monitor or per-group selections do not shift images onto the wrong display.
- #138: slideshow selection is coordinated. Each batch maximizes distinct canonical files across monitors or span groups; duplicates occur only when the configured pools hold too few unique images.

Display detection is bounded and transactional: transient enumeration failures are retried without changing the active display state, and a slow render neither overlaps another nor accumulates slideshow ticks. An explicit Linux custom command runs once and overrides desktop detection.

## Partial

| Issue | Remaining work |
|-------|----------------|
| [#58](https://github.com/hhannine/superpaper/issues/58) | Manual pan controls exist, but there is no automatic centering on a selected monitor. |
| [#63](https://github.com/hhannine/superpaper/issues/63) | Zoom-in and pan exist; zoom-out below cover-fit is not supported (`superpaper/profiles/profile_file.py` clamps zoom to 1.0). |
| [#92](https://github.com/hhannine/superpaper/issues/92), [#115](https://github.com/hhannine/superpaper/issues/115) | Rendering is cover-and-crop. Fit/contain, letterbox, no-upscale, stretch, and tile modes are missing. |
| [#126](https://github.com/hhannine/superpaper/issues/126) | Native SNI is verified on KDE Wayland, not on the GNOME setup from the original report. |
| [#141](https://github.com/hhannine/superpaper/issues/141) | KDE application and known UI failures were addressed, but the broad report has no automated cross-version Plasma coverage. |
| [#156](https://github.com/hhannine/superpaper/issues/156) | Outer bezels work in non-perspective rendering; perspective geometry ignores them. |
| [#165](https://github.com/hhannine/superpaper/issues/165) | Apply does not block the wx event loop, but the original Windows Save failure was not reproduced. |

## Open Bugs And Platform Work

| Issue | Remaining work |
|-------|----------------|
| [#25](https://github.com/hhannine/superpaper/issues/25) | Displays are re-detected when a profile starts and after the display settings are saved. Missing: detecting hotplug automatically, and re-rendering for the new layout without advancing the slideshow. |
| [#105](https://github.com/hhannine/superpaper/issues/105) | Identify and implement a current, tested Deepin/DDE wallpaper API. |
| [#113](https://github.com/hhannine/superpaper/issues/113) | Add macOS dependencies, user-writable paths, packaging, and current multi-display validation. The known gaps (PyObjC, config location) are in [development-macos.md](docs/development-macos.md). |
| [#153](https://github.com/hhannine/superpaper/issues/153) | Use unique macOS crop generations and delayed cleanup to avoid cached/deleted `-b` image URLs. |

## Open Features And Documentation

| Issue | Request |
|-------|---------|
| [#124](https://github.com/hhannine/superpaper/issues/124) | Perspective setup guide with diagrams and worked examples; the in-app help only describes the fields. |
| [#143](https://github.com/hhannine/superpaper/issues/143) | Time-of-day wallpaper switching. |
| [#139](https://github.com/hhannine/superpaper/issues/139) | Multiple independently configured regions per display. |
| [#96](https://github.com/hhannine/superpaper/issues/96) | Per-workspace wallpapers; KDE Activities are supported but are not virtual desktops. |
| [#42](https://github.com/hhannine/superpaper/issues/42) | Online image source providers and a managed download cache. |
| [#31](https://github.com/hhannine/superpaper/issues/31) | Capability-gated lockscreen backends; equivalent cross-platform behavior is unavailable. |

## Compatibility Policy

Python 3.14 is the floor for development after v2.3.2 (`requires-python` in `pyproject.toml`). The v2.3.2 release is the stable cutoff for older Python environments; source compatibility with earlier Python versions is not preserved.
