# Custom command to set the wallpaper

On Linux the option `Set command` accepts a user-defined command to set the wallpaper. When configured, this command replaces desktop-environment detection and runs exactly once.
As a special case, one can tell Superpaper to use `feh` with a tested and built-in command by setting:
```
set_command=feh
```
In the custom command, replace '/path/to/img.jpg' by '{image}', i.e. for example with the Gnome command:
```
gsettings set org.gnome.desktop.background picture-uri file://{image}
```

The command is split into executable arguments without invoking a shell. Pipes, redirects, quoting, and other shell syntax are not supported; use a wrapper executable for complex commands.
