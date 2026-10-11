"""The KDE tray menu (StatusNotifierItem): built without D-Bus from the tray's state."""

import sys
from types import SimpleNamespace

from superpaper.profile_id import ProfileId
from superpaper.profiles import Profile
from superpaper.ui.sni_tray import _MenuModel


def stored(name):
    return SimpleNamespace(profile=Profile(name=name), profile_id=ProfileId(name))


def test_the_menu_lists_the_profiles_and_starts_the_one_chosen(monkeypatch):
    monkeypatch.setitem(sys.modules, "wx", None)  # run actions at once, not on a wx main loop
    started = []
    work, home = stored("Work"), stored("Home")
    tray = SimpleNamespace(
        list_of_profiles=[work, home],
        is_paused=False,
        start_profile=lambda event, chosen: started.append(chosen),
        **{
            name: lambda event: None
            for name in (
                "open_config",
                "configure_wallpapers",
                "configure_settings",
                "reload_profiles",
                "next_wallpaper",
                "pause_timer",
                "on_about",
                "on_exit",
            )
        },
    )
    menu = _MenuModel(tray)

    menu.rebuild()
    profile_items = menu._items[_MenuModel.PROFILES_SUBMENU_ID]["children"]
    menu.activate(profile_items[1])

    assert [menu._items[item]["props"]["label"] for item in profile_items] == ["Work", "Home"]
    assert started == [home]
