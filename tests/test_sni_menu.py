"""The KDE tray menu (StatusNotifierItem): built without D-Bus from the tray's menu entries."""

from superpaper.desktop.sni_tray import _MenuModel
from superpaper.desktop.tray_menu import Check, Item, Separator, Submenu


def model_of(menu):
    return _MenuModel(menu, lambda action: action())


def entries(started, *, paused=False):
    return (
        Item("Settings", lambda: started.append("settings")),
        Separator(),
        Submenu(
            "Profiles", (Item("Work", lambda: started.append("Work")), Item("Home", lambda: started.append("Home")))
        ),
        Separator(),
        Check("Pause Timer", lambda: started.append("pause"), checked=paused),
    )


def test_the_menu_lists_the_profiles_and_starts_the_one_chosen():
    started = []
    model = model_of(lambda: entries(started))

    model.rebuild()
    submenu = model.nodes[model.layout[2]]
    model.activate(submenu.children[1])

    assert [model.nodes[child].props["label"] for child in submenu.children] == ["Work", "Home"]
    assert submenu.props["children-display"] == "submenu"
    assert submenu.action is None
    assert started == ["Home"]


def test_the_top_level_keeps_its_ids_when_the_profiles_change():
    profiles = [Item("Work", lambda: None)]
    menu = lambda: (Item("Settings", lambda: None), Submenu("Profiles", tuple(profiles)), Item("Exit", lambda: None))  # noqa: E731
    model = model_of(menu)

    model.rebuild()
    before = model.layout
    profiles.append(Item("Home", lambda: None))
    model.rebuild()

    assert model.layout == before == (1, 2, 3)
    assert sorted(model.nodes) == [1, 2, 3, 4, 5]


def test_a_check_item_carries_its_state():
    started = []
    model = model_of(lambda: entries(started, paused=True))

    model.rebuild()
    check = model.nodes[model.layout[4]]
    model.activate(model.layout[4])

    assert check.props == {"label": "Pause Timer", "enabled": True, "toggle-type": "checkmark", "toggle-state": 1}
    assert started == ["pause"]


def test_separators_and_unknown_ids_do_nothing():
    started = []
    model = model_of(lambda: entries(started))

    model.rebuild()
    model.activate(model.layout[1])
    model.activate(model.layout[2])
    model.activate(999)

    assert model.nodes[model.layout[1]].props == {"type": "separator"}
    assert started == []


def test_an_action_that_fails_is_logged_and_the_menu_carries_on(caplog):
    def broken():
        message = "broken"
        raise RuntimeError(message)

    model = model_of(lambda: (Item("Broken", broken),))

    model.rebuild()
    model.activate(1)

    assert "SNI menu action failed: broken" in caplog.text
