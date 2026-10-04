def test_custom_command_runs_once_in_known_session(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    calls = []
    monkeypatch.setattr(wpproc, "G_SET_COMMAND_STRING", "setter --image {image}")
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")
    monkeypatch.setattr(wpproc.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))

    wpproc.set_wallpaper_linux("/tmp/wallpaper with spaces.png")

    assert [call[0] for call in calls] == [["setter", "--image", "/tmp/wallpaper with spaces.png"]]
    assert calls[0][1]["env"] == wpproc.host_spawn_env()


def test_custom_command_runs_once_in_unknown_session(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    calls = []
    monkeypatch.setattr(wpproc, "G_SET_COMMAND_STRING", "setter {image}")
    monkeypatch.setenv("DESKTOP_SESSION", "unknown")
    monkeypatch.setattr(wpproc.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs)))

    wpproc.set_wallpaper_linux("/tmp/wallpaper.png")

    assert [call[0] for call in calls] == [["setter", "/tmp/wallpaper.png"]]
    assert "shell" not in calls[0][1]


def test_feh_override_is_exclusive(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    calls = []
    monkeypatch.setattr(wpproc, "G_SET_COMMAND_STRING", "feh")
    monkeypatch.setenv("DESKTOP_SESSION", "i3")
    monkeypatch.setattr(wpproc.subprocess, "run", lambda command, **kwargs: calls.append(command))

    wpproc.set_wallpaper_linux("/tmp/wallpaper.png")

    assert calls == [["feh", "--bg-scale", "--no-xinerama", "/tmp/wallpaper.png"]]


def test_no_custom_command_preserves_native_dispatch(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    calls = []
    monkeypatch.setattr(wpproc, "G_SET_COMMAND_STRING", "")
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")
    monkeypatch.setattr(wpproc.subprocess, "run", lambda command, **kwargs: calls.append(command))

    wpproc.set_wallpaper_linux("/tmp/wallpaper.png")

    assert len(calls) == 2
    assert all(command[0] == "/usr/bin/gsettings" for command in calls)


def test_settings_command_preserves_equals(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    settings_file = tmp_path / "general_settings"
    settings_file.write_text("set_command=env FOO=bar setter {image}\n", encoding="utf-8")
    monkeypatch.setattr(data, "CONFIG_PATH", str(tmp_path))
    monkeypatch.setattr(wpproc, "G_SET_COMMAND_STRING", "")

    settings = data.GeneralSettingsData()

    assert settings.set_command == "env FOO=bar setter {image}"
    assert settings.set_command == wpproc.G_SET_COMMAND_STRING


def test_settings_reload_clears_removed_command(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    settings_file = tmp_path / "general_settings"
    settings_file.write_text("logging=false\n", encoding="utf-8")
    monkeypatch.setattr(data, "CONFIG_PATH", str(tmp_path))
    monkeypatch.setattr(wpproc, "G_SET_COMMAND_STRING", "stale {image}")

    settings = data.GeneralSettingsData()

    assert settings.set_command == ""
    assert wpproc.G_SET_COMMAND_STRING == ""


def test_same_settings_instance_clears_removed_command(profile_modules, monkeypatch, tmp_path):
    data, wpproc = profile_modules
    settings_file = tmp_path / "general_settings"
    settings_file.write_text("set_command=setter {image}\n", encoding="utf-8")
    monkeypatch.setattr(data, "CONFIG_PATH", str(tmp_path))
    settings = data.GeneralSettingsData()
    settings_file.write_text("logging=false\n", encoding="utf-8")

    settings.parse_settings()

    assert settings.set_command == ""
    assert wpproc.G_SET_COMMAND_STRING == ""


def test_custom_command_receives_host_environment(profile_modules, monkeypatch):
    _, wpproc = profile_modules
    monkeypatch.setattr(wpproc, "G_SET_COMMAND_STRING", "setter {image}")
    monkeypatch.setenv("DESKTOP_SESSION", "gnome")
    monkeypatch.setenv("SUPERPAPER_HOSTENV_XDG_DATA_DIRS", "/host/data")
    received_env = None

    def run(_command, **kwargs):
        nonlocal received_env
        received_env = kwargs["env"]

    monkeypatch.setattr(wpproc.subprocess, "run", run)
    wpproc.set_wallpaper_linux("/tmp/wallpaper.png")

    assert received_env is not None
    assert received_env["XDG_DATA_DIRS"] == "/host/data"
    assert not any(key.startswith("SUPERPAPER_HOSTENV_") for key in received_env)


def test_post_change_script_receives_each_source_as_an_argument(profile_modules, monkeypatch, tmp_path):
    _, wpproc = profile_modules
    calls = []
    (tmp_path / "run-after-wp-change.py").touch()
    monkeypatch.setattr(wpproc, "CONFIG_PATH", str(tmp_path))
    monkeypatch.setattr(wpproc, "IS_WINDOWS", False)
    monkeypatch.setattr(wpproc, "IS_LINUX", True)
    monkeypatch.setattr(wpproc, "G_SET_COMMAND_STRING", "setter {image}")
    monkeypatch.setattr(wpproc.subprocess, "run", lambda command, **kwargs: calls.append(command))

    wpproc.set_wallpaper("/tmp/wallpaper.png", source_files=["/a.png", "/b c.png"])

    assert calls[-1] == [
        "python3",
        str(tmp_path / "run-after-wp-change.py"),
        "/tmp/wallpaper.png",
        "/a.png",
        "/b c.png",
    ]


def test_missing_python_for_the_post_change_script_is_logged_not_raised(profile_modules, monkeypatch, tmp_path):
    _, wpproc = profile_modules
    (tmp_path / "run-after-wp-change.py").touch()
    monkeypatch.setattr(wpproc, "CONFIG_PATH", str(tmp_path))
    monkeypatch.setattr(wpproc, "IS_WINDOWS", False)
    monkeypatch.setattr(wpproc, "IS_LINUX", True)
    monkeypatch.setattr(wpproc, "G_SET_COMMAND_STRING", "setter {image}")

    def run(command, **_kwargs):
        if command[0] == "python3":
            raise FileNotFoundError(command[0])

    monkeypatch.setattr(wpproc.subprocess, "run", run)

    assert wpproc.set_wallpaper("/tmp/wallpaper.png", source_files=["/a.png"]) == 0
