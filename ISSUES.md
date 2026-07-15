# Open Issues Tracker

Cross-reference of open issues from [hhannine/superpaper](https://github.com/hhannine/superpaper/issues) against this fork, reviewed 2026-07-15.

## Resolved In This Fork

The reported failures in #140, #154, #158, #163, and #168 are directly addressed in the current source. The AppImage fixes for #164, #169, and #170 shipped in v2.3.2; the builder now compiles the project's Python 3.14 floor on Ubuntu 22.04 so later artifacts retain the same glibc compatibility.

Issue #162's original missing-`setuptools` failure was fixed before the packaging modernization. Python 3.13 itself is now intentionally outside the post-v2.3.2 support policy described below.

Issue #135's infinite retry is fixed. Persisted selections are also validated atomically now: deleted files fall back to configured sources, and incomplete per-monitor/group selections no longer shift images onto the wrong display.

Issue #138 is resolved by coordinated slideshow selection. Each batch maximizes distinct canonical files across monitors or span groups, while allowing duplicates only when the configured pools do not contain enough unique images.

## Partial

| Issue | Remaining work |
|-------|----------------|
| [#58](https://github.com/hhannine/superpaper/issues/58) | Manual pan controls exist, but there is no automatic centering on a selected monitor. |
| [#63](https://github.com/hhannine/superpaper/issues/63) | Zoom-in and pan exist; zoom-out below cover-fit is intentionally not supported yet. |
| [#92](https://github.com/hhannine/superpaper/issues/92), [#115](https://github.com/hhannine/superpaper/issues/115) | Rendering remains cover-and-crop. Fit/contain, letterbox, no-upscale, stretch, and tile modes remain. |
| [#126](https://github.com/hhannine/superpaper/issues/126) | Native SNI is verified on KDE Wayland, not yet on the GNOME setup from the original report. |
| [#141](https://github.com/hhannine/superpaper/issues/141) | KDE application and known UI failures were addressed, but the broad report has no automated cross-version Plasma coverage. |
| [#156](https://github.com/hhannine/superpaper/issues/156) | Outer bezels work in non-perspective rendering; perspective geometry still ignores them. |
| [#165](https://github.com/hhannine/superpaper/issues/165) | Apply no longer blocks the wx event loop, but the original Windows Save failure was not reproduced. |

## Open Bugs And Platform Work

| Issue | Remaining work |
|-------|----------------|
| [#25](https://github.com/hhannine/superpaper/issues/25) | Detect display hotplug, adapt/reload the profile, and re-render without advancing the slideshow. |
| [#105](https://github.com/hhannine/superpaper/issues/105) | Identify and implement a current, tested Deepin/DDE wallpaper API. |
| [#113](https://github.com/hhannine/superpaper/issues/113) | Add macOS dependencies, user-writable paths, packaging, and current multi-display validation. |
| [#153](https://github.com/hhannine/superpaper/issues/153) | Use unique macOS crop generations and delayed cleanup to avoid cached/deleted `-b` image URLs. |

## Open Features And Documentation

| Issue | Request |
|-------|---------|
| [#124](https://github.com/hhannine/superpaper/issues/124) | Clear perspective setup guide with diagrams and examples. |
| [#143](https://github.com/hhannine/superpaper/issues/143) | Time-of-day wallpaper switching. |
| [#139](https://github.com/hhannine/superpaper/issues/139) | Multiple independently configured regions per display. |
| [#96](https://github.com/hhannine/superpaper/issues/96) | Per-workspace wallpapers; KDE Activities are supported but are not virtual desktops. |
| [#42](https://github.com/hhannine/superpaper/issues/42) | Online image source providers and a managed download cache. |
| [#31](https://github.com/hhannine/superpaper/issues/31) | Capability-gated lockscreen backends; equivalent cross-platform behavior is unavailable. |

## Compatibility Policy

Python 3.14 is the floor for development after v2.3.2. The v2.3.2 release remains the stable cutoff for older Python environments; the fork does not intend to preserve source compatibility with earlier Python versions.
