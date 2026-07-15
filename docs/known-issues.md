# Known Issues

The maintained issue inventory is in [`ISSUES.md`](../ISSUES.md). The most important current limitations are:

- Display connection and disconnection are not detected automatically.
- Perspective-corrected rendering does not yet include outer bezels.
- The native Wayland tray has been verified on KDE Plasma, but not across GNOME configurations.
- Deepin/DDE has no current tested wallpaper backend.
- macOS support is source-only and still needs packaging and multi-display reliability work.
- Windows build tooling needs validation on a Windows host.

Python 3.14 is required for source installations after v2.3.2. Use the v2.3.2 AppImage when an older system Python must remain supported.

The AppImage intentionally isolates GIO modules, GSettings schemas, and font configuration from the host. Do not apply older `GIO_EXTRA_MODULES` or `XDG_DATA_DIRS` workarounds to it; those can reintroduce the library mismatches that isolation prevents.
