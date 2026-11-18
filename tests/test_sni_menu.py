"""The KDE tray menu (StatusNotifierItem): built without D-Bus from the tray's menu entries."""

import pytest

from superpaper.desktop import sni_tray as sni_module
from superpaper.tray_menu import Check, Item, Separator, Submenu


@pytest.fixture
def sni_tray():
    """The SNI module, whose ``call_soon`` runs actions at once."""
    return sni_module


def model_of(sni_tray, menu):
    return sni_tray._MenuModel(menu, lambda action: action())


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


def test_the_menu_lists_the_profiles_and_starts_the_one_chosen(sni_tray):
    started = []
    model = model_of(sni_tray, lambda: entries(started))

    model.rebuild()
    submenu = model.nodes[model.layout[2]]
    model.activate(submenu.children[1])

    assert [model.nodes[child].props["label"] for child in submenu.children] == ["Work", "Home"]
    assert submenu.props["children-display"] == "submenu"
    assert submenu.action is None
    assert started == ["Home"]


def test_the_top_level_keeps_its_ids_when_the_profiles_change(sni_tray):
    profiles = [Item("Work", lambda: None)]
    menu = lambda: (Item("Settings", lambda: None), Submenu("Profiles", tuple(profiles)), Item("Exit", lambda: None))  # noqa: E731
    model = model_of(sni_tray, menu)

    model.rebuild()
    before = model.layout
    profiles.append(Item("Home", lambda: None))
    model.rebuild()

    assert model.layout == before == (1, 2, 3)
    assert sorted(model.nodes) == [1, 2, 3, 4, 5]


def test_a_check_item_carries_its_state(sni_tray):
    started = []
    model = model_of(sni_tray, lambda: entries(started, paused=True))

    model.rebuild()
    check = model.nodes[model.layout[4]]
    model.activate(model.layout[4])

    assert check.props == {"label": "Pause Timer", "enabled": True, "toggle-type": "checkmark", "toggle-state": 1}
    assert started == ["pause"]


def test_separators_and_unknown_ids_do_nothing(sni_tray):
    started = []
    model = model_of(sni_tray, lambda: entries(started))

    model.rebuild()
    model.activate(model.layout[1])
    model.activate(model.layout[2])
    model.activate(999)

    assert model.nodes[model.layout[1]].props == {"type": "separator"}
    assert started == []


def test_an_action_that_fails_is_logged_and_the_menu_carries_on(sni_tray, caplog):
    def broken():
        message = "broken"
        raise RuntimeError(message)

    model = model_of(sni_tray, lambda: (Item("Broken", broken),))

    model.rebuild()
    model.activate(1)

    assert "SNI menu action failed: broken" in caplog.text
