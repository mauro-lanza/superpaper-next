"""A display dragged to a new position keeps it when a bezel is set; Revert, then Save, keeps
the float offsets.

One test: each step starts from the layout the one before left in the editor and on disk.
"""

from superpaper.displays import DisplaySystem


def saved_offsets(config):
    for line in (config / "display_systems.dat").read_text(encoding="utf-8").splitlines():
        if line.startswith("ppi_norm_offsets"):
            return [tuple(float(v) for v in pair.split(",")) for pair in line.split("=")[1].split(";")]
    message = "no offsets saved"
    raise AssertionError(message)


def drag_display_1(layout_editor, dx, dy):
    layout_editor.onConfigure(None)
    shape = layout_editor.draggable_shapes[1]
    shape.pos = (shape.pos[0] + dx, shape.pos[1] + dy)
    layout_editor.positions_dragged = True
    layout_editor.onSave(None)


def test_dragged_positions_survive_a_bezel_revert_and_save(gui_env, saved_layout, snapshots):
    config = gui_env.paths.config
    superpaper = gui_env.start()
    gui_env.settle(superpaper)
    panel = gui_env.open_editor(superpaper)
    band, layout = panel.display_band, panel.display_sys
    layout_editor = panel.wpprev_pnl.layout_editor
    snapshots.replace(layout.key, "<key>")

    def snapshot(step):
        snapshots.take(step, {"display_systems.dat": config / "display_systems.dat"})

    start = layout.get_ppinorm_offsets()
    snapshot("open-editor")

    drag_display_1(layout_editor, 40, 90)
    dragged = layout.get_ppinorm_offsets()
    assert dragged[1] != start[1]
    assert dragged[1][1] > start[1][1] + 50

    band.onConfigureBezels(None)
    layout_editor.bezel_popups[0][0].tc_bez.SetValue("8.5")
    layout_editor.bezel_popups[0][0].onApply(None)
    band.onConfigureBezelsSave(None)
    after = layout.get_ppinorm_offsets()
    shift = 8.5 * layout.max_ppi() / 25.4
    assert after[0] == dragged[0]
    assert abs(after[1][0] - (dragged[1][0] + shift)) < 1e-6
    assert after[1][1] == dragged[1][1]

    band.onSave(None)
    gui_env.settle(superpaper)
    saved = saved_offsets(config)
    snapshot("saved")
    assert all(
        abs(s - a) < 1e-9 for saved_pair, after_pair in zip(saved, after) for s, a in zip(saved_pair, after_pair)
    )
    assert any(v != round(v) for pair in saved for v in pair)

    drag_display_1(layout_editor, 10, 0)
    staged = layout.get_ppinorm_offsets()
    band.onRevert(None)
    reverted = layout.get_ppinorm_offsets()
    snapshot("reverted")
    assert reverted == after
    assert reverted != staged

    layout.save_system()
    snapshot("saved-after-revert")
    assert saved_offsets(config) == saved
    assert DisplaySystem(config).get_ppinorm_offsets() == reverted
