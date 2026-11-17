## CLI usage

Superpaper supports the following arguments, display specific values are given starting from the first display on the left.
- `-h`, `--help`
- `-s`, `--setimages`, list of images to set on your monitors, if given only one it will be spanned across.
- `-a`, `--advanced`, optional, changes spanning to advanced mode, which must first be configured in the GUI.
- `--perspective`, optional, accepts a valid perspective profile name. Perspective profiles are configured in the GUI.
- `--spangroups`, optional, takes a list of spanning groups formatted as: 0 123 46 5.
- `-o`, `--offsets`, optional, image alignment adjustment with pixel offsets (advanced mode).
- `-c`, `--command`, optional, a custom command to set the wallpaper, in quotes (Linux).
- `-p`, `--profile`, start the tray applet running a pre-configured wallpaper profile. Cannot be combined with `--setimages`.
- `-d`, `--debug`, debugging flag. Alone, it runs the full application with debugging.

Without arguments Superpaper runs the tray applet. Errors are logged and exit with status 1; a successful run exits with 0.

An example using all corrections to set a single spanned image:
```
superpaper --setimages /path/to/img.png --advanced --perspective default --spangroups 0 12 --offsets 0 0 40 -100 0 0
```
Offsets are given as a pair-wise list of "horizontal_offset vertical_offset" starting from the first monitor on the left,
i.e. in the above example the display on the left is given no additional offset (0 0) and the display in
the middle is given a horizontal offset to the right by 40px and a vertical offset of 100px up (40 -100).

For the custom command syntax see [custom-command](./custom-command.md).

The resulting image is saved into Superpaper's cache directory (see "Where Superpaper keeps its files" in the [README](../README.md)) and then set as the wallpaper.
