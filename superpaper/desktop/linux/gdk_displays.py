"""Display change notifications on Linux, from GDK 3 through ctypes: X11 and Wayland alike,
without a Python binding."""

import ctypes
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

GDK_LIBRARY = "libgdk-3.so.0"
GOBJECT_LIBRARY = "libgobject-2.0.so.0"
DISPLAY_SIGNALS = ("monitor-added", "monitor-removed")  # (display, monitor, data); GTK 3.22
SCREEN_SIGNALS = ("monitors-changed", "size-changed")  # (screen, data); resolution and arrangement

_ON_DISPLAY_SIGNAL = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_ON_SCREEN_SIGNAL = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)

# A ctypes callback that is garbage collected crashes the process when GDK calls it.
_handlers: list[object] = []


def watch_displays(on_change: Callable[[], None]) -> bool:
    """Call ``on_change()`` on GTK's main thread when GDK reports a display change; False
    if GDK 3 isn't available, or there is no display open yet."""
    try:
        gdk = ctypes.CDLL(GDK_LIBRARY)
        gobject = ctypes.CDLL(GOBJECT_LIBRARY)
        gdk.gdk_display_get_default.restype = ctypes.c_void_p
        gdk.gdk_display_get_default_screen.argtypes = [ctypes.c_void_p]
        gdk.gdk_display_get_default_screen.restype = ctypes.c_void_p
        gobject.g_signal_connect_data.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        gobject.g_signal_connect_data.restype = ctypes.c_ulong
        display = gdk.gdk_display_get_default()
        if not display:
            logger.info("No GDK display to watch for changes.")
            return False
        screen = gdk.gdk_display_get_default_screen(display)
    except (OSError, AttributeError) as error:
        logger.info("Display changes can't be watched through GDK: %s", error)
        return False

    def on_display_signal(instance: int | None, argument: int | None, data: int | None) -> None:
        on_change()

    def on_screen_signal(instance: int | None, data: int | None) -> None:
        on_change()

    display_handler = _ON_DISPLAY_SIGNAL(on_display_signal)
    screen_handler = _ON_SCREEN_SIGNAL(on_screen_signal)
    _handlers.extend([display_handler, screen_handler])
    connected = [
        gobject.g_signal_connect_data(display, name.encode(), display_handler, None, None, 0)
        for name in DISPLAY_SIGNALS
    ]
    if screen:
        connected += [
            gobject.g_signal_connect_data(screen, name.encode(), screen_handler, None, None, 0)
            for name in SCREEN_SIGNALS
        ]
    return any(connected)
