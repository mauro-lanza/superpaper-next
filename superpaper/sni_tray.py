"""Native StatusNotifierItem (SNI) system tray for Linux desktops.

wxPython's ``wx.adv.TaskBarIcon`` is a legacy X11 ``GtkStatusIcon``. On modern
Wayland desktops (notably KDE Plasma 6) there is no X11 systray, only the
StatusNotifierItem (SNI) D-Bus protocol. ``xembedsniproxy`` bridges the *rendering*
of the legacy icon, but it does not deliver click/activation events back to the
wx icon, so the wx tray icon is visible yet completely non-interactive.

This module talks the SNI protocol directly over D-Bus (via ``dbus-python``),
exporting both an ``org.kde.StatusNotifierItem`` object and the
``com.canonical.dbusmenu`` context menu. Incoming D-Bus calls are dispatched
through wxGTK's own GLib main loop (see ``DBusGMainLoop`` usage in the tray
applet), so menu callbacks run on the wx main thread and may touch the GUI
directly.

It is intentionally self-contained and Linux-only; Windows and macOS keep using
the wx ``TaskBarIcon``.
"""

import os
from typing import Any

import superpaper.sp_logging as sp_logging

dbus: Any = None
Image: Any = None

try:
    import dbus  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]
    import dbus.service  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]
except ImportError:
    pass

try:
    from PIL import Image
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
        sp_logging.G_LOGGER.info("SNI watcher probe failed: %s", exc)
        return False


def _load_icon_pixmap(path):
    """Load a PNG into the SNI IconPixmap format: (width, height, ARGB32 big-endian).

    Returns a list with a single pixmap entry, or an empty list on failure.
    """
    if Image is None or not path or not os.path.isfile(path):
        return []
    try:
        with Image.open(path) as img:
            rgba = img.convert("RGBA")
            width, height = rgba.size
            # SNI wants ARGB32 in network (big-endian) byte order. PIL gives RGBA.
            raw = rgba.tobytes("raw", "RGBA")
            argb = bytearray(len(raw))
            argb[0::4] = raw[3::4]  # A
            argb[1::4] = raw[0::4]  # R
            argb[2::4] = raw[1::4]  # G
            argb[3::4] = raw[2::4]  # B
        return [(width, height, dbus.ByteArray(bytes(argb)))]
    except Exception as exc:
        sp_logging.G_LOGGER.info("Failed to load SNI icon pixmap from %s: %s", path, exc)
        return []


class _MenuModel:
    """Builds the dbusmenu layout from the controller and dispatches activations.

    The menu mirrors ``TaskBarIcon.CreatePopupMenu``. It is rebuilt on demand so
    the profile list and pause state are always current.
    """

    # Stable ids for fixed entries; profiles get ids from PROFILE_ID_BASE upward.
    PROFILE_ID_BASE = 1000
    PROFILES_SUBMENU_ID = 12

    def __init__(self, controller):
        self.controller = controller
        self.revision = 1
        # id -> dict(props=..., action=callable|None, children=[ids])
        self._items = {}
        # ordered list of top-level item ids
        self._layout = []

    def rebuild(self):
        """Recompute the menu items, returning the ordered list of top-level ids."""
        ctrl = self.controller
        self._items = {}
        self._layout = []

        def add(
            item_id,
            label,
            action,
            *,
            parent=None,
            separator=False,
            toggle=False,
            toggle_state=0,
            enabled=True,
            submenu=False,
        ):
            if separator:
                props = {"type": "separator"}
            else:
                props = {"label": label, "enabled": enabled}
                if toggle:
                    props["toggle-type"] = "checkmark"
                    props["toggle-state"] = toggle_state
                if submenu:
                    props["children-display"] = "submenu"
            self._items[item_id] = {"props": props, "action": action, "children": []}
            if parent is None:
                self._layout.append(item_id)
            else:
                self._items[parent]["children"].append(item_id)

        add(1, "Open Config Folder", ctrl.open_config)
        add(2, "Wallpaper Configuration", ctrl.configure_wallpapers)
        add(3, "Settings", ctrl.configure_settings)
        add(4, "Reload Profiles", ctrl.reload_profiles)
        add(5, None, None, separator=True)

        # Profiles live in their own submenu to keep the top level tidy.
        add(self.PROFILES_SUBMENU_ID, "Profiles", None, submenu=True)
        next_id = self.PROFILE_ID_BASE
        for profile in getattr(ctrl, "list_of_profiles", []) or []:
            add(
                next_id,
                profile.name,
                (lambda p: lambda: ctrl.start_profile(None, p))(profile),
                parent=self.PROFILES_SUBMENU_ID,
            )
            next_id += 1

        add(6, None, None, separator=True)
        add(7, "Next Wallpaper", ctrl.next_wallpaper)
        add(8, "Pause Timer", ctrl.pause_timer, toggle=True, toggle_state=1 if getattr(ctrl, "is_paused", False) else 0)
        add(9, None, None, separator=True)
        add(10, "About", ctrl.on_about)
        add(11, "Exit", ctrl.on_exit)
        return self._layout

    def activate(self, item_id):
        """Invoke the action bound to ``item_id`` if any."""
        entry = self._items.get(item_id)
        if not entry or entry["action"] is None:
            return
        action = entry["action"]
        # Actions are wx GUI calls; marshal onto the main loop to be safe.
        try:
            import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

            wx.CallAfter(self._safe_call, action)
        except Exception:
            self._safe_call(action)

    @staticmethod
    def _safe_call(action):
        try:
            # Controller methods are bound with an ``event`` first arg; pass None.
            try:
                action(None)
            except TypeError:
                action()
        except Exception as exc:
            sp_logging.G_LOGGER.error("SNI menu action failed: %s", exc, exc_info=True)


def build_tray(controller, bus_name, icon_path, title, tooltip):
    """Create and register the SNI tray. Returns the SNITray or None on failure.

    ``controller`` must provide the action methods used by ``_MenuModel`` plus
    ``configure_wallpapers`` (used for left-click Activate).
    """
    if dbus is None:
        sp_logging.G_LOGGER.info("dbus-python not available; cannot use native SNI tray.")
        return None
    try:
        tray = SNITray(controller, bus_name, icon_path, title, tooltip)
        tray.register()
    except Exception as exc:
        sp_logging.G_LOGGER.info("Failed to start native SNI tray: %s", exc)
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
            entry = self.model._items[item_id]
            children = dbus.Array(signature="v")
            if recursion_depth != 0 and entry["children"]:
                depth = recursion_depth - 1 if recursion_depth > 0 else -1
                for child_id in entry["children"]:
                    children.append(self._build_node(child_id, depth, property_names))
            return dbus.Struct(
                (dbus.Int32(item_id), self._props_variant(entry["props"], property_names), children),
                signature="ia{sv}av",
            )

        @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
        def GetLayout(self, parentId, recursionDepth, propertyNames):
            self.model.rebuild()
            if parentId == 0:
                children = dbus.Array(signature="v")
                depth = recursionDepth - 1 if recursionDepth > 0 else -1
                for item_id in self.model._layout:
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
            wanted = set(ids) if ids else set(self.model._items)
            for item_id, entry in self.model._items.items():
                if item_id in wanted:
                    result.append(
                        dbus.Struct(
                            (dbus.Int32(item_id), self._props_variant(entry["props"], propertyNames)),
                            signature="ia{sv}",
                        )
                    )
            return result

        @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
        def GetProperty(self, id, name):
            self.model.rebuild()
            entry = self.model._items.get(id)
            if entry and name in entry["props"]:
                value = entry["props"][name]
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

        def __init__(self, controller, bus_name, icon_path, title, tooltip):
            self.bus = dbus.SessionBus()
            self._bus_name = dbus.service.BusName(bus_name, self.bus)
            super().__init__(self.bus, SNI_OBJECT_PATH)
            self.controller = controller
            self.title = title
            self.tooltip = tooltip
            self.icon_pixmap = _load_icon_pixmap(icon_path)
            self.model = _MenuModel(controller)
            self.menu = _DBusMenu(self.bus, self.model)

        def register(self):
            """Register this item with the StatusNotifierWatcher."""
            watcher = self.bus.get_object(WATCHER_NAME, WATCHER_PATH)
            iface = dbus.Interface(watcher, WATCHER_NAME)
            iface.RegisterStatusNotifierItem(self._bus_name.get_name())
            sp_logging.G_LOGGER.info("Registered native SNI tray item: %s", self._bus_name.get_name())

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
            sp_logging.G_LOGGER.info("SNI tray Activate (left-click).")
            self.model._safe_call(self.controller.configure_wallpapers)

        @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
        def SecondaryActivate(self, x, y):
            sp_logging.G_LOGGER.info("SNI tray SecondaryActivate (middle-click).")
            self.model._safe_call(self.controller.next_wallpaper)

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
