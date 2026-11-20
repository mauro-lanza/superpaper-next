"""Native StatusNotifierItem (SNI) system tray for Linux.

wx's ``TaskBarIcon`` is a legacy X11 status icon: on Wayland desktops such as KDE Plasma 6
the proxy that draws it never delivers clicks back, so the icon is dead. Talking SNI and
dbusmenu over D-Bus directly keeps the tray interactive; actions run through ``call_soon``.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import count
from typing import Any, assert_never

from PIL import Image

from superpaper.desktop.tray_menu import Check, Item, MenuEntry, Notice, Separator, Submenu

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
NOTICE_ID = 1_000_000
NOTICE_SEPARATOR_ID = 1_000_001


def sni_supported() -> bool:
    """Return True if a StatusNotifierWatcher is available on the session bus."""
    if dbus is None:
        return False
    try:
        bus = dbus.SessionBus()
        return bool(bus.name_has_owner(WATCHER_NAME))
    except Exception as exc:
        logger.info("SNI watcher probe failed: %s", exc)
        return False


def _load_icon_pixmap(path: str) -> list[tuple[int, int, Any]]:
    """The PNG at ``path`` as a one-entry SNI IconPixmap (width, height, big-endian ARGB32); empty if unreadable."""
    try:
        with Image.open(path) as img:
            rgba = img.convert("RGBA")
    except (OSError, ValueError) as error:
        logger.info("Failed to load the icon %s: %s", path, error)
        return []
    raw = rgba.tobytes("raw", "RGBA")
    argb = bytearray(len(raw))
    argb[0::4] = raw[3::4]
    argb[1::4] = raw[0::4]
    argb[2::4] = raw[1::4]
    argb[3::4] = raw[2::4]
    return [(*rgba.size, dbus.ByteArray(bytes(argb)))]


def _variant(key: str, value: str | int | bool) -> Any:
    """A dbusmenu property value typed as the spec has it: booleans, the toggle state as int32, else strings."""
    if isinstance(value, bool):
        return dbus.Boolean(value)
    if key == "toggle-state":
        return dbus.Int32(value)
    return dbus.String(value)


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


def _entry_node(entry: Item | Check | Notice) -> _Node:
    match entry:
        case Item(label, action, enabled):
            return _Node({"label": label, "enabled": enabled}, action, ())
        case Check(label, action, checked, enabled):
            props = {"label": label, "enabled": enabled, "toggle-type": "checkmark", "toggle-state": int(checked)}
            return _Node(props, action, ())
        case Notice(label):
            return _Node({"label": label, "enabled": False}, None, ())
        case _:
            assert_never(entry)


class MenuModel:
    """Builds the dbusmenu layout from the tray's menu and dispatches activations. It needs
    no D-Bus, which is how it is tested."""

    def __init__(self, menu: Callable[[], tuple[MenuEntry, ...]], call_soon: Callable[[Callable[[], None]], None]):
        self._menu = menu
        self._call_soon = call_soon
        self.nodes: dict[int, _Node] = {}
        self.layout: tuple[int, ...] = ()

    def rebuild(self) -> None:
        """Recompute the nodes and the ids of the top-level ones, in menu order."""
        ids = count(1)
        # The top level gets its ids first, so they stay put when the profiles come and go.
        # A notice and the separator after it have fixed ids, so that the other items keep
        # theirs when it comes and goes while the menu is open.
        top = []
        after_notice = False
        for entry in self._menu():
            if isinstance(entry, Notice):
                node_id = NOTICE_ID
            elif after_notice and isinstance(entry, Separator):
                node_id = NOTICE_SEPARATOR_ID
            else:
                node_id = next(ids)
            after_notice = isinstance(entry, Notice)
            top.append((node_id, entry))
        nodes: dict[int, _Node] = {}
        for node_id, entry in top:
            match entry:
                case Item() | Check() | Notice():
                    nodes[node_id] = _entry_node(entry)
                case Separator():
                    nodes[node_id] = _Node({"type": "separator"}, None, ())
                case Submenu(label, items):
                    children = []
                    for item in items:
                        child_id = next(ids)
                        nodes[child_id] = _entry_node(item)
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
        if node is None or node.action is None or not node.props["enabled"]:
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
        """``com.canonical.dbusmenu`` implementation backed by a ``MenuModel``."""

        def __init__(self, bus, model):
            super().__init__(bus, MENU_OBJECT_PATH)
            self.model = model
            self.model.rebuild()

        def _props_variant(self, props, property_names):
            out = dbus.Dictionary(signature="sv")
            for key, value in props.items():
                if property_names and key not in property_names:
                    continue
                out[key] = _variant(key, value)
            return out

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
            return dbus.UInt32(1), root

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
                return _variant(name, node.props[name])
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
            self.model = MenuModel(menu, call_soon)
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
