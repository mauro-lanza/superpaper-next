"""Native StatusNotifierItem (SNI) system tray for Linux desktops.

wxPython's ``wx.adv.TaskBarIcon`` is a legacy X11 ``GtkStatusIcon``. On modern
Wayland desktops (notably KDE Plasma 6) there is no X11 systray, only the
StatusNotifierItem (SNI) D-Bus protocol. ``xembedsniproxy`` bridges the *rendering*
of the legacy icon, but it does not deliver click/activation events back to the
wx icon, so the wx tray icon is visible yet completely non-interactive.

This module talks the SNI protocol directly over D-Bus (via ``dbus-python``),
exporting both an ``org.kde.StatusNotifierItem`` object and the
``com.canonical.dbusmenu`` context menu. Incoming D-Bus calls are dispatched
through the GUI toolkit's GLib main loop (``DBusGMainLoop`` set as the default by
the application), and menu actions are handed on to the GUI's main loop with
``call_soon``, so they may touch the GUI directly.

It is intentionally self-contained and Linux-only; Windows and macOS keep using
the toolkit's own tray icon.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import count
from typing import Any, assert_never

from superpaper.rendering.render import load_argb32
from superpaper.tray_menu import Check, Item, MenuEntry, Separator, Submenu

logger = logging.getLogger(__name__)

dbus: Any = None

try:
    import dbus  # ty:ignore[unresolved-import]
    import dbus.service  # ty:ignore[unresolved-import]
except ImportError:
    pass


SNI_OBJECT_PATH = "/StatusNotifierItem"
MENU_OBJECT_PATH = "/MenuBar"
SNI_IFACE = "org.kde.StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"


def sni_supported():
    """Return True if a StatusNotifierWatcher is available on the session bus."""
    if dbus is None:
        return False
    try:
        bus = dbus.SessionBus()
        return bool(bus.name_has_owner(WATCHER_NAME))
    except Exception as exc:
        logger.info("SNI watcher probe failed: %s", exc)
        return False


def _load_icon_pixmap(path):
    """Load a PNG into the SNI IconPixmap format: (width, height, ARGB32 big-endian).

    Returns a list with a single pixmap entry, or an empty list on failure.
    """
    pixmap = load_argb32(path)
    if pixmap is None:
        return []
    width, height, argb = pixmap
    return [(width, height, dbus.ByteArray(argb))]


def _run_action(action: Callable[[], None]) -> None:
    try:
        action()
    except Exception as exc:
        logger.error("SNI menu action failed: %s", exc, exc_info=True)


@dataclass(frozen=True, slots=True)
class _Node:
    """One dbusmenu item: its properties, what clicking it does, and the ids of its children."""

    props: Mapping[str, str | int | bool]
    action: Callable[[], None] | None
    children: tuple[int, ...]


def _item_node(item: Item) -> _Node:
    return _Node({"label": item.label, "enabled": True}, item.action, ())


class _MenuModel:
    """Builds the dbusmenu layout from the tray's menu and dispatches activations.

    It is rebuilt on demand so the profile list and pause state are always current.
    """

    def __init__(self, menu: Callable[[], tuple[MenuEntry, ...]], call_soon: Callable[[Callable[[], None]], None]):
        self._menu = menu
        self._call_soon = call_soon
        self.revision = 1
        self.nodes: dict[int, _Node] = {}
        self.layout: tuple[int, ...] = ()

    def rebuild(self) -> None:
        """Recompute the nodes and the ids of the top-level ones, in menu order."""
        ids = count(1)
        # The top level gets its ids first, so they stay put when the profiles come and go.
        top = [(next(ids), entry) for entry in self._menu()]
        nodes: dict[int, _Node] = {}
        for node_id, entry in top:
            match entry:
                case Item():
                    nodes[node_id] = _item_node(entry)
                case Check(label, action, checked):
                    props = {"label": label, "enabled": True, "toggle-type": "checkmark", "toggle-state": int(checked)}
                    nodes[node_id] = _Node(props, action, ())
                case Separator():
                    nodes[node_id] = _Node({"type": "separator"}, None, ())
                case Submenu(label, items):
                    children = []
                    for item in items:
                        child_id = next(ids)
                        nodes[child_id] = _item_node(item)
                        children.append(child_id)
                    props = {"label": label, "enabled": True, "children-display": "submenu"}
                    nodes[node_id] = _Node(props, None, tuple(children))
                case _:
                    assert_never(entry)
        self.nodes = nodes
        self.layout = tuple(node_id for node_id, _ in top)

    def activate(self, item_id: int) -> None:
        """Run the action of the item ``item_id``, if it has one, on the GUI's main loop."""
        node = self.nodes.get(item_id)
        if node is None or node.action is None:
            return
        action = node.action
        self._call_soon(lambda: _run_action(action))


def build_tray(
    *,
    menu: Callable[[], tuple[MenuEntry, ...]],
    call_soon: Callable[[Callable[[], None]], None],
    activate: Callable[[], None],
    secondary_activate: Callable[[], None],
    bus_name: str,
    icon_path: str,
    title: str,
    tooltip: str,
):
    """Create and register the SNI tray. Returns the SNITray or None on failure.

    ``menu`` gives the entries of the context menu as they are now, whose actions run
    through ``call_soon``; ``activate`` and ``secondary_activate`` are what a left and a
    middle click do.
    """
    if dbus is None:
        logger.info("dbus-python not available; cannot use native SNI tray.")
        return None
    try:
        tray = SNITray(menu, call_soon, activate, secondary_activate, bus_name, icon_path, title, tooltip)
        tray.register()
    except Exception as exc:
        logger.info("Failed to start native SNI tray: %s", exc)
        return None
    return tray


if dbus is not None:

    class _DBusMenu(dbus.service.Object):
        """``com.canonical.dbusmenu`` implementation backed by a ``_MenuModel``."""

        def __init__(self, bus, model):
            super().__init__(bus, MENU_OBJECT_PATH)
            self.model = model
            self.model.rebuild()

        # --- helpers -------------------------------------------------------
        def _props_variant(self, props, property_names):
            out = dbus.Dictionary(signature="sv")
            for key, value in props.items():
                if property_names and key not in property_names:
                    continue
                if key == "toggle-state":
                    out[key] = dbus.Int32(value)
                else:
                    out[key] = dbus.String(value)
            return out

        # --- com.canonical.dbusmenu methods --------------------------------
        def _build_node(self, item_id, recursion_depth, property_names):
            """Recursively build a dbusmenu (id, props, children) struct."""
            node = self.model.nodes[item_id]
            children = dbus.Array(signature="v")
            if recursion_depth != 0 and node.children:
                depth = recursion_depth - 1 if recursion_depth > 0 else -1
                for child_id in node.children:
                    children.append(self._build_node(child_id, depth, property_names))
            return dbus.Struct(
                (dbus.Int32(item_id), self._props_variant(node.props, property_names), children),
                signature="ia{sv}av",
            )

        @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
        def GetLayout(self, parentId, recursionDepth, propertyNames):
            self.model.rebuild()
            if parentId == 0:
                children = dbus.Array(signature="v")
                depth = recursionDepth - 1 if recursionDepth > 0 else -1
                for item_id in self.model.layout:
                    children.append(self._build_node(item_id, depth, propertyNames))
                root_props = self._props_variant({"children-display": "submenu"}, propertyNames)
                root = dbus.Struct((dbus.Int32(0), root_props, children), signature="ia{sv}av")
            else:
                root = self._build_node(parentId, recursionDepth, propertyNames)
            return dbus.UInt32(self.model.revision), root

        @dbus.service.method(MENU_IFACE, in_signature="aias", out_signature="a(ia{sv})")
        def GetGroupProperties(self, ids, propertyNames):
            self.model.rebuild()
            result = dbus.Array(signature="(ia{sv})")
            wanted = set(ids) if ids else set(self.model.nodes)
            for item_id, node in self.model.nodes.items():
                if item_id in wanted:
                    result.append(
                        dbus.Struct(
                            (dbus.Int32(item_id), self._props_variant(node.props, propertyNames)),
                            signature="ia{sv}",
                        )
                    )
            return result

        @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
        def GetProperty(self, id, name):
            self.model.rebuild()
            node = self.model.nodes.get(id)
            if node and name in node.props:
                value = node.props[name]
                return dbus.Int32(value) if name == "toggle-state" else dbus.String(value)
            return dbus.String("")

        @dbus.service.method(MENU_IFACE, in_signature="isvu", out_signature="")
        def Event(self, id, eventId, data, timestamp):
            if eventId == "clicked":
                self.model.activate(int(id))

        @dbus.service.method(MENU_IFACE, in_signature="a(isvu)", out_signature="ai")
        def EventGroup(self, events):
            errors = dbus.Array(signature="i")
            for item_id, event_id, _data, _timestamp in events:
                if event_id == "clicked":
                    self.model.activate(int(item_id))
            return errors

        @dbus.service.method(MENU_IFACE, in_signature="i", out_signature="b")
        def AboutToShow(self, id):
            self.model.rebuild()
            return dbus.Boolean(True)

        @dbus.service.method(MENU_IFACE, in_signature="ai", out_signature="aiai")
        def AboutToShowGroup(self, ids):
            self.model.rebuild()
            return dbus.Array(signature="i"), dbus.Array(signature="i")

        # --- properties ----------------------------------------------------
        @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
        def Get(self, interface, prop):
            return self.GetAll(interface).get(prop, dbus.String(""))

        @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            return dbus.Dictionary(
                {
                    "Version": dbus.UInt32(3),
                    "TextDirection": dbus.String("ltr"),
                    "Status": dbus.String("normal"),
                    "IconThemePath": dbus.Array([], signature="s"),
                },
                signature="sv",
            )

        # --- signals -------------------------------------------------------
        @dbus.service.signal(MENU_IFACE, signature="a(ia{sv})a(ias)")
        def ItemsPropertiesUpdated(self, updated, removed):
            pass

        @dbus.service.signal(MENU_IFACE, signature="ui")
        def LayoutUpdated(self, revision, parent):
            pass

    class SNITray(dbus.service.Object):
        """``org.kde.StatusNotifierItem`` implementation."""

        def __init__(self, menu, call_soon, activate, secondary_activate, bus_name, icon_path, title, tooltip):
            self.bus = dbus.SessionBus()
            self._bus_name = dbus.service.BusName(bus_name, self.bus)
            super().__init__(self.bus, SNI_OBJECT_PATH)
            self._on_activate = activate
            self._on_secondary_activate = secondary_activate
            self.title = title
            self.tooltip = tooltip
            self.icon_pixmap = _load_icon_pixmap(icon_path)
            self.model = _MenuModel(menu, call_soon)
            self.menu = _DBusMenu(self.bus, self.model)

        def register(self):
            """Register this item with the StatusNotifierWatcher."""
            watcher = self.bus.get_object(WATCHER_NAME, WATCHER_PATH)
            iface = dbus.Interface(watcher, WATCHER_NAME)
            iface.RegisterStatusNotifierItem(self._bus_name.get_name())
            logger.info("Registered native SNI tray item: %s", self._bus_name.get_name())

        def remove(self):
            """Tear down the exported D-Bus objects (best-effort, on exit)."""
            try:
                self.menu.remove_from_connection()
            except Exception:
                pass
            try:
                self.remove_from_connection()
            except Exception:
                pass

        # --- org.kde.StatusNotifierItem methods ----------------------------
        @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
        def Activate(self, x, y):
            logger.info("SNI tray Activate (left-click).")
            _run_action(self._on_activate)

        @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
        def SecondaryActivate(self, x, y):
            logger.info("SNI tray SecondaryActivate (middle-click).")
            _run_action(self._on_secondary_activate)

        @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
        def ContextMenu(self, x, y):
            # The menu is exported via the dbusmenu object; KDE shows it itself.
            pass

        @dbus.service.method(SNI_IFACE, in_signature="is", out_signature="")
        def Scroll(self, delta, orientation):
            pass

        # --- properties ----------------------------------------------------
        @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
        def Get(self, interface, prop):
            return self.GetAll(interface).get(prop, dbus.String(""))

        @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            tooltip = dbus.Struct(
                (dbus.String(""), dbus.Array([], signature="(iiay)"), dbus.String(self.tooltip), dbus.String("")),
                signature="sa(iiay)ss",
            )
            return dbus.Dictionary(
                {
                    "Category": dbus.String("ApplicationStatus"),
                    "Id": dbus.String("superpaper"),
                    "Title": dbus.String(self.title),
                    "Status": dbus.String("Active"),
                    "IconName": dbus.String("superpaper"),
                    "IconPixmap": dbus.Array(self.icon_pixmap, signature="(iiay)"),
                    "ToolTip": tooltip,
                    "ItemIsMenu": dbus.Boolean(False),
                    "Menu": dbus.ObjectPath(MENU_OBJECT_PATH),
                },
                signature="sv",
            )

        # --- signals -------------------------------------------------------
        @dbus.service.signal(SNI_IFACE, signature="")
        def NewIcon(self):
            pass

        @dbus.service.signal(SNI_IFACE, signature="")
        def NewTitle(self):
            pass

        @dbus.service.signal(SNI_IFACE, signature="")
        def NewToolTip(self):
            pass

        @dbus.service.signal(SNI_IFACE, signature="s")
        def NewStatus(self, status):
            pass
