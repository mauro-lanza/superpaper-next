"""The profile editor and the tray, clicked through in order.

One test: each step starts from the profiles, selections and running pointer the one before
left, and the scenario verifies that sequence (save, apply, rename, delete, restart).
"""

from types import SimpleNamespace

import pytest
from PIL import Image

from superpaper.desktop.tray_menu import Submenu


def profile_files(paths):
    files = {f"profiles/{path.name}": path for path in paths.profiles.glob("*.profile")}
    files.update({f"selections/{path.name}": path for path in (paths.cache / "selections").glob("*.json")})
    files["running_profile"] = paths.cache / "running_profile"
    return files


@pytest.fixture
def wallpapers(gui_env):
    """Three wallpapers, and Main, a profile listing them, as the only saved profile."""
    folder = gui_env.root / "wallpapers"
    folder.mkdir()
    for index, colour in enumerate(((200, 30, 30), (30, 200, 30), (30, 30, 200)), start=1):
        Image.new("RGB", (64, 36), colour).save(folder / f"wall-{index}.png")
    for path in gui_env.paths.profiles.iterdir():
        path.unlink()
    sources = ";".join(str(folder / f"wall-{index}.png") for index in (1, 2, 3))
    gui_env.write_profile(
        "Main", f"name=Main\nspanmode=single\nslideshow=false\nsortmode=alphabetical\ndisplay0paths={sources}\n"
    )
    return folder


def shown(stored):
    return stored.selection.images


def selection_text(paths, name):
    path = paths.cache / "selections" / f"{name}.json"
    return path.read_text(encoding="utf-8") if path.exists() else None


def profile_text(paths, name):
    path = paths.profiles / f"{name}.profile"
    return path.read_text(encoding="utf-8") if path.exists() else None


def choose(gui_env, superpaper, panel, name):
    """Pick a profile in the editor's profile list, as a click does."""
    panel.update_choiceprofile()
    panel._select_in_dropdown(name)
    panel.populate_fields(gui_env.saved(superpaper, name))


def click_row(panel, index):
    """Click the source list's row ``index``."""
    panel.path_listctrl.Focus(index)
    panel.onWallpaperItemSelected(SimpleNamespace(GetIndex=lambda: index))


def test_profile_editor_and_tray(gui_env, wallpapers, snapshots):
    paths = gui_env.paths

    def snapshot(step):
        snapshots.take(step, profile_files(paths))

    def slideshow_running(superpaper):
        return superpaper.session._deadline is not None

    # Start the tray: it restores Main, which was running; open the editor.
    first = gui_env.start()
    gui_env.start_profile(first, "Main")
    gui_env.quit(first)
    superpaper = gui_env.start()
    gui_env.settle(superpaper)
    panel = gui_env.open_editor(superpaper)
    snapshot("start")
    assert superpaper.session.running.profile.name == "Main"
    assert panel.tc_name.GetValue() == "Main"
    first_image = str(wallpapers / "wall-1.png")
    second_image = str(wallpapers / "wall-2.png")
    assert shown(superpaper.session.running) == [first_image]

    # Zoom Main to 125 %; Save.
    panel.sld_zoom.SetValue(125)
    panel.onZoomOffsetChange(None)
    gui_env.shown()
    panel.onSave(None)
    gui_env.settle(superpaper)
    snapshot("zoom-saved")
    assert gui_env.shown() == []
    assert "zoom=1.25" in profile_text(paths, "Main")
    assert superpaper.session.running.profile.zoom == 1.25

    # Click the second image in the source list; Apply: it is shown, remembered and running.
    click_row(panel, 1)
    before = profile_text(paths, "Main")
    panel.onApply(None)
    gui_env.settle(superpaper)
    snapshot("second-image-applied")
    assert gui_env.shown() == []
    assert shown(gui_env.saved(superpaper, "Main")) == [second_image]
    assert profile_text(paths, "Main") == before
    assert superpaper.session.running is gui_env.saved(superpaper, "Main")
    assert panel._pick is None

    # Create a new profile 'Office': a slideshow of the wallpapers folder, alphabetical, every 10 minutes; Save.
    panel.onCreateNewProfile(None)
    panel.tc_name.ChangeValue("Office")
    panel.populate_lc_browse([[str(wallpapers)]])
    panel.cb_slideshow.SetValue(True)
    panel.onCheckboxSlideshow(None)
    panel.tc_sshow_delay.ChangeValue("10")
    panel.ch_sshow_sort.SetSelection(panel.ch_sshow_sort.FindString("Alphabetical"))
    panel.onSave(None)
    gui_env.settle(superpaper)
    snapshot("office-created")
    assert gui_env.shown() == []

    # Start Office from the tray menu; Next wallpaper.
    gui_env.click(superpaper, "Office")
    gui_env.settle(superpaper)
    before_next = shown(superpaper.session.running)
    gui_env.click(superpaper, "Next Wallpaper")
    gui_env.settle(superpaper)
    snapshot("office-next")
    assert superpaper.session.running.profile.name == "Office"
    assert slideshow_running(superpaper)
    assert shown(superpaper.session.running) != before_next

    # Rename Office to Study in the editor; Save.
    choose(gui_env, superpaper, panel, "Office")
    panel.tc_name.ChangeValue("Study")
    panel.onSave(None)
    gui_env.settle(superpaper)
    snapshot("renamed")
    assert gui_env.shown() == []
    assert profile_text(paths, "Office") is None
    assert profile_text(paths, "Study") is not None
    assert superpaper.session.running.profile.name == "Study"
    assert slideshow_running(superpaper)
    assert selection_text(paths, "Study") is not None

    # Change Study's delay to 20 without saving; Revert.
    panel.tc_sshow_delay.ChangeValue("20")
    panel.onRevert(None)
    gui_env.settle(superpaper)
    snapshot("reverted")
    assert panel.tc_sshow_delay.GetValue() == "10.0"

    # Edit Study.profile outside the editor (delay 15 minutes); Revert; Save.
    study = paths.profiles / "Study.profile"
    study.write_text(study.read_text(encoding="utf-8").replace("delay=600.0", "delay=900.0"), encoding="utf-8")
    panel.onRevert(None)
    reverted = panel.tc_sshow_delay.GetValue()
    panel.onSave(None)
    gui_env.settle(superpaper)
    snapshot("edited-outside-reverted-saved")
    assert reverted == "15.0"
    assert gui_env.shown() == []

    # Delete Study, the running profile, in the editor.
    choose(gui_env, superpaper, panel, "Study")
    armed = slideshow_running(superpaper)
    gui_env.yes_to_message_dialogs()
    panel.onDeleteProfile(None)
    gui_env.settle(superpaper)
    snapshot("study-deleted")
    assert profile_text(paths, "Study") is None
    assert selection_text(paths, "Study") is None
    assert armed
    assert not slideshow_running(superpaper)
    assert superpaper.session.running is None

    # Start Main from the tray menu.
    gui_env.click(superpaper, "Main")
    gui_env.settle(superpaper)
    snapshot("main-started")
    assert superpaper.session.running.profile.name == "Main"
    assert shown(superpaper.session.running) == [second_image]

    # Quit; break a profile by hand; start again, answering No to deleting it.
    gui_env.quit(superpaper)
    gui_env.write_profile("Broken", "name=Broken\ndelay=soon\n")
    gui_env.shown()
    gui_env.answer_yes = False
    superpaper = gui_env.start()
    gui_env.settle(superpaper)
    snapshot("restarted-with-broken-profile")
    asked = [dialog for dialog in gui_env.shown() if "Broken.profile" in dialog[2]]
    assert superpaper.session.running.profile.name == "Main"
    assert shown(superpaper.session.running) == [second_image]
    assert asked
    assert (paths.profiles / "Broken.profile").exists()
    (profiles,) = (entry for entry in superpaper.tray.menu() if isinstance(entry, Submenu))
    assert [item.label for item in profiles.items] == ["Main"]
    assert not list(paths.config.rglob(".superpaper-*.tmp"))
    assert not list(paths.cache.rglob(".superpaper-*.tmp"))

    # Open the editor and Save Main, unchanged, with the broken profile still there.
    panel = gui_env.open_editor(superpaper)
    before = profile_text(paths, "Main")
    panel.onSave(None)
    gui_env.settle(superpaper)
    snapshot("saved-unchanged")
    assert profile_text(paths, "Main") == before
