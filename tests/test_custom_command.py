from superpaper.settings import read_settings

# These desktops take the whole image, so the setter needs no display layout to cut it.
NO_LAYOUT = None


def test_custom_command_runs_once_in_known_session(profile_modules, monkeypatch, app_paths):
    _, wpproc = profile_modules
    calls = []
    set_command = "setter --image {image}"
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")
    monkeypatch.setattr(wpproc.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))

    wpproc.set_wallpaper_linux(
        "/tmp/wallpaper with spaces.png", display_system=NO_LAYOUT, paths=app_paths, set_command=set_command
    )

    assert [call[0] for call in calls] == [["setter", "--image", "/tmp/wallpaper with spaces.png"]]
    assert calls[0][1]["env"] == wpproc.host_spawn_env()


def test_custom_command_runs_once_in_unknown_session(profile_modules, monkeypatch, app_paths):
    _, wpproc = profile_modules
    calls = []
    set_command = "setter {image}"
    monkeypatch.setenv("DESKTOP_SESSION", "unknown")
    monkeypatch.setattr(wpproc.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))

    wpproc.set_wallpaper_linux("/tmp/wallpaper.png", display_system=NO_LAYOUT, paths=app_paths, set_command=set_command)

    assert [call[0] for call in calls] == [["setter", "/tmp/wallpaper.png"]]
    assert "shell" not in calls[0][1]


def test_feh_override_is_exclusive(profile_modules, monkeypatch, app_paths):
    _, wpproc = profile_modules
    calls = []
    set_command = "feh"
    monkeypatch.setenv("DESKTOP_SESSION", "i3")
    monkeypatch.setattr(wpproc.subprocess, "run", lambda command, **kwargs: calls.append(command))

    wpproc.set_wallpaper_linux("/tmp/wallpaper.png", display_system=NO_LAYOUT, paths=app_paths, set_command=set_command)

    assert calls == [["feh", "--bg-scale", "--no-xinerama", "/tmp/wallpaper.png"]]


def test_no_custom_command_preserves_native_dispatch(profile_modules, monkeypatch, app_paths):
    _, wpproc = profile_modules
    calls = []
    set_command = ""
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")
    monkeypatch.setattr(wpproc.subprocess, "run", lambda command, **kwargs: calls.append(command))

    wpproc.set_wallpaper_linux("/tmp/wallpaper.png", display_system=NO_LAYOUT, paths=app_paths, set_command=set_command)

    assert len(calls) == 2
    assert all(command[0] == "/usr/bin/gsettings" for command in calls)


def test_settings_command_preserves_equals(tmp_path):
    settings_file = tmp_path / "general_settings"
    settings_file.write_text("set_command=env FOO=bar setter {image}\n", encoding="utf-8")

    assert read_settings(settings_file, "linux").set_command == "env FOO=bar setter {image}"


def test_settings_without_a_command_have_none(tmp_path):
    settings_file = tmp_path / "general_settings"
    settings_file.write_text("logging=false\n", encoding="utf-8")

    assert read_settings(settings_file, "linux").set_command == ""


def test_custom_command_receives_host_environment(profile_modules, monkeypatch, app_paths):
    _, wpproc = profile_modules
    set_command = "setter {image}"
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")
    monkeypatch.setenv("SUPERPAPER_HOSTENV_XDG_DATA_DIRS", "/host/data")
    received_env = None

    def run(_command, **kwargs):
        nonlocal received_env
        received_env = kwargs["env"]

    monkeypatch.setattr(wpproc.subprocess, "run", run)
    wpproc.set_wallpaper_linux("/tmp/wallpaper.png", display_system=NO_LAYOUT, paths=app_paths, set_command=set_command)

    assert received_env is not None
    assert received_env["XDG_DATA_DIRS"] == "/host/data"
    assert not any(key.startswith("SUPERPAPER_HOSTENV_") for key in received_env)


def test_post_change_script_receives_each_source_as_an_argument(profile_modules, monkeypatch, app_paths):
    _, wpproc = profile_modules
    calls = []
    (app_paths.config / "run-after-wp-change.py").touch()
    monkeypatch.setattr(wpproc, "IS_WINDOWS", False)
    monkeypatch.setattr(wpproc, "IS_LINUX", True)
    monkeypatch.setattr(wpproc.subprocess, "run", lambda command, **kwargs: calls.append(command))

    wpproc.set_wallpaper(
        "/tmp/wallpaper.png",
        source_files=["/a.png", "/b c.png"],
        display_system=NO_LAYOUT,
        paths=app_paths,
        set_command="setter {image}",
    )

    assert calls[-1] == [
        "python3",
        str(app_paths.config / "run-after-wp-change.py"),
        "/tmp/wallpaper.png",
        "/a.png",
        "/b c.png",
    ]


def test_missing_python_for_the_post_change_script_is_logged_not_raised(profile_modules, monkeypatch, app_paths):
    _, wpproc = profile_modules
    (app_paths.config / "run-after-wp-change.py").touch()
    monkeypatch.setattr(wpproc, "IS_WINDOWS", False)
    monkeypatch.setattr(wpproc, "IS_LINUX", True)

    def run(command, **_kwargs):
        if command[0] == "python3":
            raise FileNotFoundError(command[0])

    monkeypatch.setattr(wpproc.subprocess, "run", run)

    status = wpproc.set_wallpaper(
        "/tmp/wallpaper.png", ["/a.png"], display_system=NO_LAYOUT, paths=app_paths, set_command="setter {image}"
    )

    assert status == 0
