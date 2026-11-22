"""Watching the displays through GDK, with GDK and GObject faked."""

import ctypes
from types import SimpleNamespace

import pytest

from superpaper.desktop.linux import gdk_displays

DISPLAY = 0x1000
SCREEN = 0x2000


class FakeLibrary:
    """A ctypes library whose functions are the ones in ``functions``; any other is missing."""

    def __init__(self, **functions):
        self._functions = functions

    def __getattr__(self, name):
        if name not in self._functions:
            raise AttributeError(name)
        return self._functions[name]


class FakeFunction:
    def __init__(self, result=None):
        self.result = result
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


@pytest.fixture
def gdk(monkeypatch):
    connect = FakeFunction(result=7)
    libraries = {
        gdk_displays.GDK_LIBRARY: FakeLibrary(
            gdk_display_get_default=FakeFunction(DISPLAY),
            gdk_display_get_default_screen=FakeFunction(SCREEN),
        ),
        gdk_displays.GOBJECT_LIBRARY: FakeLibrary(g_signal_connect_data=connect),
    }

    def load(name):
        if name not in libraries:
            raise OSError(name)
        return libraries[name]

    monkeypatch.setattr(ctypes, "CDLL", load)
    monkeypatch.setattr(gdk_displays, "_handlers", [])
    return SimpleNamespace(connect=connect, libraries=libraries)


def test_the_display_and_screen_signals_are_connected_and_call_back(gdk):
    changes = []

    assert gdk_displays.watch_displays(lambda: changes.append("changed")) is True

    connected = [(call[0], call[1]) for call in gdk.connect.calls]
    assert connected == [
        (DISPLAY, b"monitor-added"),
        (DISPLAY, b"monitor-removed"),
        (SCREEN, b"monitors-changed"),
        (SCREEN, b"size-changed"),
    ]
    display_handler = gdk.connect.calls[0][2]
    screen_handler = gdk.connect.calls[2][2]
    display_handler(DISPLAY, 0x3000, None)
    screen_handler(SCREEN, None)
    assert changes == ["changed", "changed"]


def test_the_handlers_are_kept_referenced(gdk):
    gdk_displays.watch_displays(lambda: None)

    assert len(gdk_displays._handlers) == 2


@pytest.mark.parametrize("missing", [gdk_displays.GDK_LIBRARY, gdk_displays.GOBJECT_LIBRARY])
def test_a_missing_library_means_the_os_cannot_notify(gdk, missing):
    del gdk.libraries[missing]

    assert gdk_displays.watch_displays(lambda: None) is False


def test_a_missing_symbol_means_the_os_cannot_notify(gdk):
    gdk.libraries[gdk_displays.GOBJECT_LIBRARY] = FakeLibrary()

    assert gdk_displays.watch_displays(lambda: None) is False


def test_no_open_display_means_the_os_cannot_notify(gdk):
    gdk.libraries[gdk_displays.GDK_LIBRARY] = FakeLibrary(
        gdk_display_get_default=FakeFunction(None), gdk_display_get_default_screen=FakeFunction(None)
    )

    assert gdk_displays.watch_displays(lambda: None) is False
    assert gdk.connect.calls == []
