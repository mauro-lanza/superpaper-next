import inspect
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import superpaper.desktop as desktop
from superpaper.desktop import linux, process
from superpaper.desktop.backend import Desktop
from superpaper.desktop.wallpaper import ProfileWallpapers, Spanned

IMAGE = "/tmp/wallpaper.png"
# Only KDE Plasma looks at the other profiles' wallpapers.
NO_PROFILES = ProfileWallpapers(current_profile=None, cached_pieces=lambda name: [], state_dir=Path("unused"))


def assert_satisfies_desktop(module):
    """Check ``module`` has every Desktop function, with the same parameters."""
    for name, member in vars(Desktop).items():
        if name.startswith("_") or not callable(member):
            continue
        expected = list(inspect.signature(member).parameters.values())
        actual = list(inspect.signature(getattr(module, name)).parameters.values())
        assert [(p.name, p.kind, p.annotation) for p in actual] == [(p.name, p.kind, p.annotation) for p in expected], (
            name
        )


def fake_screen(number, x, y, width, height, scale=1.0):
    frame = SimpleNamespace(origin=SimpleNamespace(x=x, y=y), size=SimpleNamespace(width=width, height=height))
    return SimpleNamespace(
        number=number,
        frame=frame,
        backingScaleFactor=lambda: scale,
        localizedName=lambda: f"Screen {number}",
        deviceDescription=lambda: {"NSScreenNumber": number},
    )


@pytest.fixture
def appkit(monkeypatch):
    """AppKit, as ``install(screens)`` gives it, with screens as (x, y, width, height[, scale]) in points.

    The first screen is the primary one. ``install`` returns what was set where, as
    (screen number, image) pairs; screen numbers count from 1 in the order given.
    """

    def install(screens):
        set_images = []
        workspace = SimpleNamespace(
            setDesktopImageURL_forScreen_options_error_=lambda url, screen, options, error: (
                set_images.append((screen.number, url)) or (True, None)
            )
        )
        appkit_module = ModuleType("AppKit")
        appkit_module.NSScreen = SimpleNamespace(
            screens=lambda: [fake_screen(number, *screen) for number, screen in enumerate(screens, start=1)]
        )
        appkit_module.NSWorkspace = SimpleNamespace(sharedWorkspace=lambda: workspace)
        foundation = ModuleType("Foundation")
        foundation.NSURL = SimpleNamespace(fileURLWithPath_=lambda path: path)
        monkeypatch.setitem(sys.modules, "AppKit", appkit_module)
        monkeypatch.setitem(sys.modules, "Foundation", foundation)
        monkeypatch.setitem(sys.modules, "Quartz", None)
        return set_images

    yield install
    sys.modules.pop("superpaper.desktop.macos", None)
    if hasattr(desktop, "macos"):
        del desktop.macos


@pytest.fixture
def windows(monkeypatch):
    """The superpaper.desktop.windows module, importable here with the win32 modules faked."""
    shell_package = ModuleType("win32com")
    shell_module = ModuleType("win32com.shell")
    shell_module.shell = SimpleNamespace()
    shell_module.shellcon = SimpleNamespace()
    shell_package.shell = shell_module
    for name, module in {
        "winreg": ModuleType("winreg"),
        "pythoncom": ModuleType("pythoncom"),
        "win32gui": ModuleType("win32gui"),
        "win32com": shell_package,
        "win32com.shell": shell_module,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr("ctypes.windll", SimpleNamespace(user32=SimpleNamespace()), raising=False)
    from superpaper.desktop import windows

    yield windows
    sys.modules.pop("superpaper.desktop.windows", None)
    if hasattr(desktop, "windows"):
        del desktop.windows


@pytest.fixture
def ran(monkeypatch):
    """Record the host programs run; they all succeed unless a test says otherwise."""
    calls = []

    def run(command, **options):
        calls.append((list(command), options))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(process.subprocess, "run", run)
    return calls


def set_wallpaper(set_command="", image=IMAGE):
    return linux.set_wallpaper(Spanned(image), set_command=set_command, profiles=NO_PROFILES)
