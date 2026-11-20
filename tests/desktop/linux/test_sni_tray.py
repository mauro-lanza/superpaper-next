"""The KDE tray menu (StatusNotifierItem): built without D-Bus from the tray's menu entries."""

from superpaper.desktop.linux.sni_tray import NOTICE_ID, NOTICE_SEPARATOR_ID, MenuModel
from superpaper.desktop.tray_menu import Check, Item, Separator, Submenu, failure_notice


def model_of(menu):
    return MenuModel(menu, lambda action: action())


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


def test_a_notice_is_a_disabled_line_that_does_nothing():
    failure = [failure_notice("Image missing")]
    model = model_of(lambda: (*failure, Item("Exit", lambda: None)))

    model.rebuild()
    notice = model.nodes[model.layout[0]]
    model.activate(model.layout[0])
    failure.clear()
    model.rebuild()

    assert notice.props == {"label": "Last change failed: Image missing", "enabled": False}
    assert notice.action is None
    assert len(model.layout) == 1


def test_regular_items_keep_their_ids_while_a_notice_shows():
    failure = []
    model = model_of(lambda: (*failure, *entries([])))

    model.rebuild()
    before = {node_id: node.props for node_id, node in model.nodes.items()}
    failure.extend([failure_notice("Image missing"), Separator()])
    model.rebuild()

    assert before.items() <= {node_id: node.props for node_id, node in model.nodes.items()}.items()
    assert len(model.nodes) == len(before) + 2
    assert model.layout[:2] == (NOTICE_ID, NOTICE_SEPARATOR_ID)


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
