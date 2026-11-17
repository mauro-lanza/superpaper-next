# Custom command to set the wallpaper

On Linux the option `Set command` (or `--command` on the command line) accepts a user-defined command to set the wallpaper. When configured, this command replaces desktop-environment detection and runs exactly once.
As a special case, one can tell Superpaper to use `feh` with a tested and built-in command by setting:
```
set_command=feh
```
In the custom command, `{image}` is replaced by the path of the wallpaper image, for example with the Gnome command:
```
gsettings set org.gnome.desktop.background picture-uri file://{image}
```

The command is split on whitespace into executable arguments without invoking a shell. Pipes, redirects, quoting, and other shell syntax are not supported; use a wrapper executable for complex commands.

## Script after a wallpaper change

`run-after-wp-change.py` in the config directory is run with `python3` after each change, with the wallpaper image as the first argument followed by each source image. See the [example script](../example-script/run-after-wp-change.py).
