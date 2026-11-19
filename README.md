# Superpaper Next

A community-maintained fork of [Superpaper](https://github.com/hhannine/superpaper), an advanced multi monitor wallpaper manager for **Linux** and **Windows** operating systems, with partial support for **MacOS** (hotkeys are off by default and unsupported).

This fork focuses on KDE Plasma 6 support and the wallpaper selection experience. Development and testing is primarily done on Plasma 6; other desktop environments may work but are not actively tested.

![](https://raw.githubusercontent.com/hhannine/Superpaper/branch-resources/readme-banner.jpg)
![](https://raw.githubusercontent.com/hhannine/Superpaper/branch-resources/gui-screenshot.png)


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
- **Bezel correction**: let the image continuously span behind your bezels, outer bezels included.
- **Perspective correction**: span the image even more flawlessly!
- Manual pixel offsets for fine-tuning
- **Image zoom & positioning**: images are cover-fitted, so they always fill the screen without letterboxing. Zoom further in and move the visible area, with a live preview. Saved per profile and available for single fixed images only: the controls are reset and disabled while a profile's slideshow is enabled.
- **System display settings**: display sizes, bezels and physical positions are shared by all profiles. They live in a collapsible "Display system settings" band above the profile selector, with their own Save and Revert. "Apply" renders with the staged, unsaved values, so you can check them before saving.
- **Wallpaper selection**: clicking a wallpaper in the source list updates the preview. The wallpaper you choose is the profile's current wallpaper and is shown when the app opens or the profile is switched to. With the slideshow off, "Apply" sets the selected image.
- Slideshow with configurable file order from local sources. The wallpaper changes when the slideshow timer fires or on "Next Wallpaper" from the tray.
- Add wallpapers one by one or a folder at a time (no subfolders)
- **KDE Activities**: name a profile after a KDE Activity (case-sensitive) and its wallpaper follows the active activity. KDE Plasma 6 and Activity support: *Contributed by [FredworkLemmas](https://github.com/FredworkLemmas)*
- Command-line interface
- Run a script after wallpaper change: [example script](./docs/examples/run-after-wp-change.py)
- Tray applet for slideshow control. On Linux a native StatusNotifierItem tray is used when a `StatusNotifierWatcher` is on the session bus (left-click opens the settings, middle-click advances the wallpaper, right-click shows the menu with the profiles under **Profiles**); otherwise the classic wx tray is used.
- Hotkey support for easy slideshow control (Linux and Windows; off by default and unsupported on MacOS)
- Align test tool to help fine tune your settings (Accessible only from GUI)

In the above banner photo you can see the PPI and bezel corrections in action. The left one is a 27" 4K display, and the right one is a 25" 1440p display.

Supported Linux desktop environments / window managers are:
- BSPWM (needs feh)
- Budgie
- Cinnamon
- Gnome
- i3 (needs feh)
- KDE
- LXQt (including Lubuntu)
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

Superpaper Next requires Python 3.14+.

### Linux

An AppImage package is available on the [releases page](https://github.com/mauro-lanza/superpaper-next/releases).
The AppImage will run once you make it executable.

#### From source

1. Clone the repo
2. Create a virtualenv: `python -m venv .venv && source .venv/bin/activate`
3. Install Superpaper with its Linux extras: `pip install -e '.[gui,linux]'`
4. Run: `python -m superpaper`

For other installation options see: [installing on linux](./docs/installation-linux.md). To run the GUI tests, see [running GUI tests](./docs/development-gui-tests.md).

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
  - Perspective profiles are created in the GUI and selected with `--perspective`.

### Where Superpaper keeps its files

- **Linux:** settings, profiles and display layouts in `~/.config/superpaper`
  (`$XDG_CONFIG_HOME/superpaper`); rendered wallpapers, the log and the slideshow
  position in `~/.cache/superpaper/temp` (`$XDG_CACHE_HOME/superpaper/temp`).
- **Windows:** beside the program for a portable install, otherwise in
  `%LOCALAPPDATA%\Superpaper`.
- **macOS:** beside the program.

To use other directories, for example to try something without touching your own
setup, set `SUPERPAPER_CONFIG_HOME` and `SUPERPAPER_CACHE_HOME` to the directories
to use. The cache directory should hold nothing but Superpaper's files: when it starts,
Superpaper deletes the rendered wallpapers of profiles that no longer exist.


## Troubleshooting

If you run into issues and Superpaper closes unexpectedly, you can either:
- Enable logging in the Settings.
- Manually enable logging in the 'general_settings' file by setting 'logging=true'.
- Run Superpaper from the command-line with the switch '--debug' to get debugging prints.
```sh
superpaper --debug
#or
./Superpaper-<version>-x86_64.AppImage --debug
```
Check the logs and come create an issue!


## Known issues

For known differences from upstream issues, see [ISSUES.md](./ISSUES.md).


## License

Superpaper is published under the [MIT License](./LICENSE).
