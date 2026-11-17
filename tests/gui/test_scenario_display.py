"""The display band and the perspectives dialog, clicked through in order.

One test, because each step builds on the files the one before saved: what the scenario
verifies is the sequence (edit, save, revert, restart) against the layout files.
"""

from superpaper.displays import DisplaySystem


def state(layout):
    return {
        "offsets": [tuple(round(v, 6) for v in offset) for offset in layout.get_ppinorm_offsets()],
        "bezels": layout.bezels_in_mm(),
        "diagonals": [display.diagonal_size()[1] for display in layout.disp_list],
        "entered diagonals": layout.use_user_diags,
        "perspectives": layout.perspective_dict,
        "default": layout.default_perspective,
        "use perspective": layout.use_perspective,
    }


def assert_restart_loads(layout, config):
    """Load the layout afresh, as the next start does, and expect the editor's."""
    again = state(DisplaySystem(config))
    differences = {name: (value, again[name]) for name, value in state(layout).items() if again[name] != value}
    assert not differences


def test_display_settings_and_perspectives(gui_env, saved_layout, snapshots):
    ui = gui_env.ui
    config = gui_env.paths.config
    superpaper = gui_env.start()
    superpaper.update_settings(warn_large_img=True)
    gui_env.start_profile(superpaper, "Work")
    panel = gui_env.open_editor(superpaper)
    band = panel.display_band
    layout = panel.display_sys
    key = layout.key
    snapshots.replace(key, "<key>")

    def layout_file():
        return (config / "display_systems.dat").read_text(encoding="utf-8")

    def perspective_file():
        path = config / f"{key}.persp"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def snapshot(step):
        snapshots.take(
            step, {"display_systems.dat": config / "display_systems.dat", "layout.persp": config / f"{key}.persp"}
        )

    # Open the editor: it shows the layout saved for these displays.
    snapshot("open-editor")
    assert_restart_loads(layout, config)

    # Bezels: 8.5 mm right of display 0; save the bezels, then the display settings.
    band.onConfigureBezels(None)
    right_of_first = panel.wpprev_pnl.layout_editor.bezel_popups[0][0]
    right_of_first.tc_bez.SetValue("8.5")
    right_of_first.onApply(None)
    band.onConfigureBezelsSave(None)
    offered = band.button_system_save.IsEnabled()
    band.onSave(None)
    gui_env.settle(superpaper)
    snapshot("bezel-saved")
    assert offered
    assert not band.button_system_save.IsEnabled()
    assert "bezel_mms = 8.5,0.0;0.0,0.0" in layout_file()
    assert superpaper.session.display_system.bezels_in_mm()[0] == (8.5, 0.0)
    assert_restart_loads(layout, config)

    # Diagonal of display 0: 24.0 -> 28.0 inches; save.
    assert layout.disp_list[0].diagonal_size()[1] == 24.0
    band.cb_diaginch.SetValue(True)
    band.onCheckboxDiaginch(None)
    band.tc_list_diaginch[0].ChangeValue("28.0")
    band._on_diagonal_changed(None)
    offered = band.button_system_save.IsEnabled()
    band.onSave(None)
    gui_env.settle(superpaper)
    snapshot("diagonal-saved")
    saved_layout_file = layout_file()
    assert offered
    assert "user_diagonal_inches = 28.0," in saved_layout_file
    assert_restart_loads(layout, config)

    # Diagonal of display 0: 30.0 inches, then Revert.
    band.tc_list_diaginch[0].ChangeValue("30.0")
    band._on_diagonal_changed(None)
    staged = layout.disp_list[0].diagonal_size()[1]
    band.onRevert(None)
    snapshot("diagonal-reverted")
    assert staged == 30.0
    assert layout.disp_list[0].diagonal_size()[1] == 28.0
    assert layout_file() == saved_layout_file

    dialog = ui.perspective_dialog.PerspectiveConfig(panel)
    assert dialog.warn_large_img

    # Perspectives: create 'desk', the default, viewer 700 mm away, display 1 swivelled 20° on its left edge.
    dialog.onCreateNewProfile(None)
    dialog.tc_name.SetValue("desk")
    dialog.cb_master.SetValue(True)
    dialog.cb_dispsys_def.SetValue(True)
    dialog.tclist_vieweroffs[2].SetValue("700")
    dialog.grid_rows[1][1].SetSelection(1)
    dialog.grid_rows[1][2].SetValue("20")
    gui_env.shown()
    saved = dialog.onSave(None)
    gui_env.settle(superpaper)
    snapshot("desk-created")
    assert saved == 1
    assert layout.default_perspective == "desk"
    assert "def_perspective = desk" in layout_file()
    assert "use_perspective = 1" in layout_file()
    assert "[desk]\n" in perspective_file()
    assert "swivels = 0,0.0,0.0,0.0;1,20.0,0.0,0.0" in perspective_file()
    assert gui_env.shown() == []
    assert_restart_loads(layout, config)

    # Apply in the editor: the profile renders with the default perspective.
    panel.onApply(None)
    gui_env.settle(superpaper)
    assert list((gui_env.paths.cache / "preview").glob("draft-?.png"))
    assert gui_env.shown() == []

    # Edit 'desk': viewer 900 mm away.
    dialog.choice_profiles.SetSelection(dialog.choice_profiles.FindString("desk"))
    dialog.populate_fields("desk")
    dialog.tclist_vieweroffs[2].SetValue("900")
    dialog.onSave(None)
    gui_env.settle(superpaper)
    snapshot("desk-edited")
    distance = layout.perspective_dict["desk"]["viewer_pos"][2]
    assert f"viewer_pos = 0.0,0.0,{distance}" in perspective_file()

    # Create 'couch', not the default, viewer 2500 mm away.
    dialog.onCreateNewProfile(None)
    dialog.tc_name.SetValue("couch")
    dialog.cb_master.SetValue(True)
    dialog.cb_dispsys_def.SetValue(False)
    dialog.tclist_vieweroffs[2].SetValue("2500")
    dialog.onSave(None)
    gui_env.settle(superpaper)
    snapshot("couch-created")
    assert sorted(layout.perspective_dict) == ["couch", "desk", "wall"]
    assert layout.default_perspective == "desk"
    assert "[couch]" in perspective_file()
    assert "def_perspective = desk" in layout_file()

    # Edit 'couch' into settings that need a huge intermediate image; answer No, then Yes.
    dialog.choice_profiles.SetSelection(dialog.choice_profiles.FindString("couch"))
    dialog.populate_fields("couch")
    dialog.tclist_vieweroffs[0].SetValue("-300")
    dialog.tclist_vieweroffs[2].SetValue("100")
    dialog.grid_rows[1][1].SetSelection(2)
    dialog.grid_rows[1][2].SetValue("89.5")
    files_before = (layout_file(), perspective_file())
    state_before = state(layout)
    gui_env.shown()
    gui_env.answer_yes = False
    refused = dialog.onSave(None)
    gui_env.settle(superpaper)
    warned = gui_env.shown()
    snapshot("couch-refused")
    assert refused == 0
    assert [kind for _, kind, _ in warned] == ["Info"]
    assert state(layout) == state_before
    assert (layout_file(), perspective_file()) == files_before
    gui_env.answer_yes = True
    accepted = dialog.onSave(None)
    gui_env.settle(superpaper)
    snapshot("couch-accepted")
    assert accepted == 1
    assert "1,89.5,0.0,0.0" not in perspective_file()
    assert "2,89.5,0.0,0.0" in perspective_file()
    assert_restart_loads(layout, config)

    # Delete 'desk', the default.
    dialog.choice_profiles.SetSelection(dialog.choice_profiles.FindString("desk"))
    dialog.onDeleteProfile(None)
    gui_env.settle(superpaper)
    snapshot("desk-deleted")
    assert sorted(layout.perspective_dict) == ["couch", "wall"]
    assert layout.default_perspective is None
    assert "def_perspective = None" in layout_file()
    assert "[desk]" not in perspective_file()
    dialog.Destroy()

    # Restart: the saved layout is what loads, and the session's layout is the saved one.
    restarted = DisplaySystem(config)
    assert_restart_loads(layout, config)
    assert state(superpaper.session.display_system) == state(restarted)
    assert not list(config.glob(".superpaper-*.tmp"))
