# Superpaper Next

A community-maintained fork of [Superpaper](https://github.com/hhannine/superpaper), an advanced multi monitor wallpaper manager for **Linux** and **Windows** operating systems, with partial support (no hotkeys) for **MacOS**.

This fork focuses on KDE Plasma 6 support and improving the wallpaper selection experience. Development and testing is primarily done on Plasma 6; other desktop environments may work but are not actively tested.

![](https://raw.githubusercontent.com/hhannine/Superpaper/branch-resources/readme-banner.jpg)
![](https://raw.githubusercontent.com/hhannine/Superpaper/branch-resources/gui-screenshot.png)


## What's new in this fork

### KDE Plasma 6 & Activity Support
*Contributed by [FredworkLemmas](https://github.com/FredworkLemmas)*

- Per-activity wallpaper support: name your profiles to match your KDE Activities (case-sensitive) and the wallpaper will follow the active activity.
- Updated installation and dependency handling for Plasma 6 environments.

### Wallpaper Selection Improvements
- **Select to use**: the wallpaper you choose is remembered as the profile's current wallpaper. Opening the app or switching to a profile shows that wallpaper and no longer cycles to a random image on launch.
- **Click-to-preview**: clicking a wallpaper in the source list updates the preview panel immediately
- **Apply selected image**: when slideshow is off, "Apply" sets the specific image you selected instead of a random one from the rotation
- **Cycling on demand only**: the wallpaper changes when the slideshow timer fires or when you pick "Next Wallpaper" from the tray, never just because a profile was re-rendered
- **Consistent preview after save**: the preview shows your selected wallpaper instead of a random pick from a freshly shuffled list

### Image Scaling & Position
- **Always fills the screen**: images are cover-fitted so there is never any letterboxing
- **Zoom**: zoom further into the image while it keeps filling the display
- **Horizontal / vertical positioning**: move the visible area within the image to place the content where you want it, with a live preview
- Saved per profile. These controls apply to a single fixed image, so they are reset and disabled while a profile's slideshow is enabled.

### Native Wayland System Tray
- **Interactive tray on Wayland**: a native `StatusNotifierItem` tray icon replaces the legacy X11 tray, which appeared but was completely unclickable on modern Wayland desktops (notably KDE Plasma 6).
- **Full tray controls**: left-click opens the wallpaper settings, middle-click advances the wallpaper, and right-click shows the full menu with your profiles grouped under a **Profiles** submenu.
- Automatically used on Linux when a `StatusNotifierWatcher` is present, falling back to the classic tray otherwise.

### Display System Settings
- **Dedicated Save / Revert**: display sizes, bezels and physical positions are system-wide settings (shared by all profiles) and now have their own explicit Save and Revert instead of being written to disk silently.
- **Test before you commit**: "Apply" renders with your staged, unsaved system settings, so you can check bezels and sizes before saving them permanently.
- **Collapsible band**: the system settings live in a collapsible "Display system settings" band above the profile selector; its Save/Revert buttons gray out when nothing has changed.
- **Manual display sizes**: input display sizes manually with always-visible inch fields (the old "Override detected sizes" toggle is gone).

### Stability & Bug Fixes
- **Responsive while applying**: the GUI no longer freezes while a profile is being applied.
- **Outer bezels on apply**: outer bezels are now respected when the wallpaper is applied, matching the preview.
- **CLI `--profile`**: launching with `--profile <name>` now resolves the profile and applies the wallpaper on startup.
- **Robust file handling**: a missing wallpaper file can no longer cause an infinite loop, and an empty image list no longer crashes.
- Plus NumPy 1.24+ compatibility, Zorin OS detection, Python 3.13 install fixes, and various correctness/type-safety improvements.


## Planned Improvements

- **Visual wallpaper selector**: replace the file path list with an image grid/icon view, showing the path on hover
- **Interactive positioning**: drag-to-pan and scroll-to-zoom directly on the preview, in addition to the current sliders


## Features

### Novel features include
- Advanced wallpaper spanning options
  - Pixel density correction
  - Bezel correction
  - Perspective correction
  - These are described in more detail on this [wiki page](https://github.com/hhannine/superpaper/wiki/Wallpaper-spanning-with-advanced-options:-what-the-pixel-density-and-perspective-corrections-are-about).
- Extensive Linux support!
  - Aims to support all desktop environments
  - Span wallpaper on KDE and XFCE!
- Cross-platform: works on Linux, MacOS, and Windows
  - MacOS needs testing and packaging

### Features in detail
- Set a single image across all displays
- Set different image on every display
- Span images on groups of displays: one image on laptop screen and another spanned on two external monitors, for example.
- **Pixel density correction**: span an image flawlessly across displays of different shapes and sizes!
- **Bezel correction**: let the image continuously span behind your bezels.
- **Perspective correction**: span the image even more flawlessly!
- Manual pixel offsets for fine-tuning
- **System display settings**: display sizes, bezels and positions are shared by all profiles, with a dedicated Save/Revert and a "test before save" Apply.
- **Image zoom & positioning**: zoom into an image and move the visible area while it keeps filling the screen (single-image profiles)
- Slideshow with configurable file order from local sources
- Add wallpapers one by one or a folder at a time (no subfolders)
- Command-line interface
- Run a script after wallpaper change: [example script](./example-script/run-after-wp-change.py)
- Tray applet for slideshow control (native StatusNotifierItem tray on Wayland)
- Hotkey support for easy slideshow control (Only Linux and Windows)
- Align test tool to help fine tune your settings (Accessible only from GUI)

In the above banner photo you can see the PPI and bezel corrections in action. The left one is a 27" 4K display, and the right one is a 25" 1440p display.

Supported Linux desktop environments / window managers are:
- BSPWM (needs feh)
- Budgie
- Cinnamon
- Gnome
- i3 (needs feh)
- KDE
- LXDE & LXQt
- Mate
- Pantheon
- XFCE

and additionally there is support for
- supplying a [custom command](./docs/custom-command.md) to set the wallpaper

if support for your system of choice is not built-in.


### Support
If you find Superpaper useful please consider supporting the original developer:

- [Support via PayPal](https://www.paypal.me/superpaper/5)
- [Support via Github Sponsors](https://github.com/sponsors/hhannine)


## Installation

### Linux

An AppImage package is available on the [releases page](https://github.com/mauro-lanza/superpaper-next/releases).
The AppImage will run once you make it executable.

#### From source

1. Clone the repo
2. Create a virtualenv: `python -m venv .venv && source .venv/bin/activate`
3. Install requirements: `pip install -r requirements_install_python_package.txt`
4. Run: `python -m superpaper`

For other installation options see: [installing on linux](./docs/installation-linux.md).

### Windows 10 & 11

A Windows installer and a portable package are available on the upstream [releases page](https://github.com/hhannine/superpaper/releases).

### MacOS

 You must install the dependencies and run the project, see [development-macos](./docs/development-macos.md).


## Usage

You can either:

- Open Superpaper as a graphical application
  - First run opens help and wallpaper settings. Disable 'show help at start' to run Superpaper silently in the background.
  - Control Superpaper in the background from the tray menu or with hotkeys.
- Call it from the [command-line](./docs/cli-usage.md)
  - Perspectives cannot be configured or used through the CLI currently.


## Troubleshooting

If you run into issues and Superpaper closes unexpectedly, you can either:
- Enable logging in the Settings.
- Manually enable logging in the 'general_settings' file by setting 'logging=true'.
- Run Superpaper from the command-line with the switch '--debug' to get debugging prints.
```sh
superpaper --debug
#or
./Superpaper-2.0.2-x86_64.AppImage --debug
```
Check the logs and come create an issue!


## Known issues

For some common problems and solutions, check [Known issues](./docs/known-issues.md).


## License

Superpaper is published under the [MIT License](./LICENSE).
