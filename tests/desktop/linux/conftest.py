import sys
from types import ModuleType, SimpleNamespace

import pytest

from superpaper.desktop.linux import kde

# Two displays, showing desktops 1 and 2 of the current activity; the other activities'
# desktops are on no screen (-1), as before Plasma 6.8.
DESKTOPS = "1,0,1;2,1,1;3,-1,0;4,-1,0;5,-1,0;6,-1,0"


class FakePlasma:
    """Plasma's scripting interface: it lists the desktops and records the wallpaper scripts."""

    def __init__(self):
        self.scripts = []
        self.failure = None
        self.desktops = DESKTOPS

    def evaluateScript(self, script):
        if script == kde.DESKTOPS_SCRIPT:
            return self.desktops
        if self.failure:
            raise self.failure
        self.scripts.append(script)
        return ""


@pytest.fixture
def plasma(monkeypatch):
    """A fake PlasmaShell behind a fake dbus-python."""
    shell = FakePlasma()
    dbus = ModuleType("dbus")
    dbus.SessionBus = lambda: SimpleNamespace(get_object=lambda name, path: (name, path))
    dbus.Interface = lambda proxy, dbus_interface: (
        shell
        if (proxy, dbus_interface)
        == (
            ("org.kde.plasmashell", "/PlasmaShell"),
            "org.kde.PlasmaShell",
        )
        else None
    )
    monkeypatch.setitem(sys.modules, "dbus", dbus)
    return shell
