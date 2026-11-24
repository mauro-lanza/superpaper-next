"""Align tests show the editor's staged layout and pause the slideshow; saving the display
layout shows the running profile again; a restart shows the last render only while it is
still right."""

from superpaper.geometry import layout_edit
from superpaper.geometry.perspective import Named
from superpaper.paths import resource
from superpaper.profile_actions import align_test_profile
from superpaper.unsaved_changes import ApplyAnswer
from superpaper.wallpaper_change import _render_signature as render_signature


def stage_bezels(editor, millimetres):
    count = len(editor.staged.layout.displays)
    editor.staged.layout = editor.staged.layout.with_bezels([(millimetres, 0.0)] + [(0.0, 0.0)] * (count - 1))
    editor.display_band.update_dirty()


def draft_signatures(cache):
    return [path.read_text(encoding="utf-8") for path in (cache / "preview").glob("draft-?.png.sig")]


def renders(cache, commands, start):
    """The images the setter command was given since ``start``."""
    return [command[1] for command in commands[start:] if command[:1] == ["true"]]


def test_the_align_test_renders_the_staged_layout_not_the_saved_one(gui_env, running_work, editor):
    stage_bezels(editor, 6.0)
    staged = editor.staged.layout
    assert staged != running_work.session.layout
    test_image = [str(resource("test.png"))]
    profile = align_test_profile(test_image[0], editor._selected_perspective(), editor._typed_offsets())

    editor.onAlignTest(None)
    gui_env.settle(running_work)

    assert draft_signatures(gui_env.paths.cache) == [render_signature(staged, profile, test_image)]
    assert running_work.session.layout != staged


def test_the_align_test_pauses_the_running_slideshow_and_the_tray_shows_it(gui_env, running_work, editor):
    assert not gui_env.menu_entry(running_work, "Pause Timer").checked

    editor.onAlignTest(None)
    gui_env.settle(running_work)

    assert running_work.session.paused is True
    assert gui_env.menu_entry(running_work, "Pause Timer").checked
    assert running_work.session.running.profile.name == "Work"


def test_unpausing_ends_the_test(gui_env, running_work, editor):
    editor.onAlignTest(None)
    gui_env.settle(running_work)

    gui_env.click(running_work, "Pause Timer")
    gui_env.settle(running_work)

    assert running_work.session.paused is False
    assert not gui_env.menu_entry(running_work, "Pause Timer").checked


def test_the_align_test_is_refused_while_the_staged_displays_overlap(gui_env, running_work, editor):
    layout = editor.staged.layout
    editor.staged.layout = layout.with_offsets([(0, 0)] * len(layout.displays))
    assert not editor.staged.layout.is_valid()
    gui_env.shown()

    editor.onAlignTest(None)
    gui_env.settle(running_work)

    assert gui_env.shown() == [("editor", "Error", layout_edit.TEST_OVERLAP_MESSAGE)]
    assert draft_signatures(gui_env.paths.cache) == []
    assert running_work.session.paused is False


def test_the_perspective_dialogs_test_renders_the_staged_layout_and_pauses(gui_env, running_work, editor):
    stage_bezels(editor, 6.0)
    dialog = gui_env.open_perspectives(editor)
    dialog.tc_name.SetValue("study")
    dialog.cb_master.SetValue(True)
    dialog.tclist_vieweroffs[2].SetValue("600")

    dialog.onAlignTest(None)
    gui_env.settle(running_work)

    (signature,) = draft_signatures(gui_env.paths.cache)
    staged = editor.staged.layout
    assert staged.perspective("study") is not None
    test_image = str(resource("test.png").resolve())
    profile = align_test_profile(test_image, Named("study"), dialog.typed_offsets)
    assert signature == render_signature(staged, profile, [test_image])
    assert running_work.session.paused is True


def test_the_perspective_dialogs_test_is_refused_while_the_staged_displays_overlap(gui_env, running_work, editor):
    dialog = gui_env.open_perspectives(editor)
    dialog.tc_name.SetValue("study")
    dialog.cb_master.SetValue(True)
    dialog.tclist_vieweroffs[2].SetValue("600")
    layout = editor.staged.layout
    editor.staged.layout = layout.with_offsets([(0, 0)] * len(layout.displays))
    gui_env.shown()

    dialog.onAlignTest(None)
    gui_env.settle(running_work)

    assert gui_env.shown()[-1] == ("editor", "Error", layout_edit.TEST_OVERLAP_MESSAGE)
    assert draft_signatures(gui_env.paths.cache) == []
    assert running_work.session.paused is False


def test_saving_the_display_layout_shows_the_running_profile_again_once_for_the_new_layout(
    gui_env, running_work, editor
):
    session = running_work.session
    stored = session.running
    images = stored.selection.images
    commands = len(gui_env.commands)
    stage_bezels(editor, 4.5)

    editor.display_band.onSave(None)
    gui_env.settle(running_work)

    shown = renders(gui_env.paths.cache, gui_env.commands, commands)
    assert len(shown) == 1
    assert stored.selection.images == images
    signature = (gui_env.paths.cache / f"{shown[0]}.sig").read_text(encoding="utf-8")
    assert signature == render_signature(session.layout, stored.profile, images)
    assert session.layout.bezels_in_mm()[0] == (4.5, 0.0)


def test_saving_the_display_layout_keeps_the_pause(gui_env, running_work, editor):
    gui_env.click(running_work, "Pause Timer")
    gui_env.settle(running_work)
    commands = len(gui_env.commands)
    stage_bezels(editor, 4.5)

    editor.display_band.onSave(None)
    gui_env.settle(running_work)

    assert len(renders(gui_env.paths.cache, gui_env.commands, commands)) == 1
    assert running_work.session.paused is True


def test_saving_the_display_layout_with_nothing_running_shows_nothing(gui_env, superpaper):
    panel = gui_env.open_editor(superpaper)
    commands = len(gui_env.commands)
    stage_bezels(panel, 4.5)

    panel.display_band.onSave(None)
    gui_env.settle(superpaper)

    assert renders(gui_env.paths.cache, gui_env.commands, commands) == []


def test_a_failed_display_layout_save_shows_nothing_again(gui_env, running_work, editor):
    (gui_env.paths.config / "display_systems.dat").mkdir()
    commands = len(gui_env.commands)
    stage_bezels(editor, 4.5)

    editor.display_band.onSave(None)
    gui_env.settle(running_work)

    assert renders(gui_env.paths.cache, gui_env.commands, commands) == []


def test_apply_that_saves_the_display_layout_renders_once(gui_env, running_work, editor):
    gui_env.apply_answer = ApplyAnswer.SAVE_DISPLAYS
    commands = len(gui_env.commands)
    stage_bezels(editor, 4.5)

    editor.onApply(None)
    gui_env.settle(running_work)

    assert len(renders(gui_env.paths.cache, gui_env.commands, commands)) == 1


def restart(gui_env, superpaper):
    gui_env.quit(superpaper)
    gui_env.commands.clear()
    restarted = gui_env.start()
    gui_env.settle(restarted)
    return restarted


def test_a_restart_shows_the_last_render_again_while_it_is_right(gui_env, running_work):
    gui_env.settle(running_work)
    render = str(gui_env.paths.cache / "Work-a.png")

    restarted = restart(gui_env, running_work)

    assert renders(gui_env.paths.cache, gui_env.commands, 0) == [render]
    assert restarted.session.running.profile.name == "Work"


def test_a_restart_ignores_a_test_shown_after_the_last_render(gui_env, running_work, editor):
    editor.onAlignTest(None)
    gui_env.settle(running_work)
    assert draft_signatures(gui_env.paths.cache)

    restart(gui_env, running_work)

    assert renders(gui_env.paths.cache, gui_env.commands, 0) == [str(gui_env.paths.cache / "Work-a.png")]


def test_a_restart_renders_again_when_the_layout_was_saved_since(gui_env, running_work):
    gui_env.settle(running_work)
    gui_env.quit(running_work)
    layout = running_work.session.layout
    count = len(layout.displays)
    saved = layout.with_bezels([(4.5, 0.0)] + [(0.0, 0.0)] * (count - 1))
    assert layout_edit.save_display_settings(gui_env.paths.config, saved) is None
    gui_env.commands.clear()

    restarted = gui_env.start()
    gui_env.settle(restarted)

    (shown,) = renders(gui_env.paths.cache, gui_env.commands, 0)
    assert shown == str(gui_env.paths.cache / "Work-b.png")


def test_a_restart_renders_again_when_the_profile_shows_other_images_now(gui_env, running_work):
    gui_env.settle(running_work)
    gui_env.quit(running_work)
    selected = running_work.session.running.selection.images
    other = next(str(path) for path in sorted(gui_env.images.glob("*.png")) if str(path) not in selected)
    selection_file = next((gui_env.paths.cache / "selections").glob("Work*"))
    selection_file.write_text(selection_file.read_text(encoding="utf-8").replace(selected[0], other), encoding="utf-8")
    gui_env.commands.clear()

    restarted = gui_env.start()
    gui_env.settle(restarted)

    assert restarted.session.running.selection.images == [other]
    assert renders(gui_env.paths.cache, gui_env.commands, 0) == [str(gui_env.paths.cache / "Work-b.png")]
