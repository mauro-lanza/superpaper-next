"""Fixtures for the GUI tests: a real wx.App on the current display, Superpaper started
against scratch directories and a fixed pair of monitors, and recorders in place of
everything that would reach the user's desktop (dialogs, hotkeys, wallpaper commands).

Each test gets its own environment: starting Superpaper takes milliseconds, and tests then
can't depend on each other's state.
"""

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import superpaper.desktop.process as process
import superpaper.geometry.display_detection as display_detection
from superpaper.desktop import linux
from superpaper.desktop.tray_menu import Submenu
from superpaper.geometry import display_store
from superpaper.geometry.perspective import Perspective, Swivel, SwivelAxis, Tilt
from superpaper.profiles.profile_id import ProfileId
from superpaper.settings import first_run_settings, read_settings
from superpaper.unsaved_changes import Answer, ApplyAnswer
from tests.conftest import TWO_DISPLAYS
from tests.gui.snapshots import Snapshots

HERE = Path(__file__).parent
SETTINGS = (
    "logging=false\nuse hotkeys=false\nshow_help_at_start=false\nset_command=true {image}\nwarn_large_img=false\n"
)
SLIDESHOW = "name={name}\nspanmode=single\nslideshow=true\ndelay=600\nsortmode=alphabetical\ndisplay0paths={images}\n"
STILL = "name={name}\nspanmode=single\nslideshow=false\ndisplay0paths={images}\n"


def pytest_collection_modifyitems(items):
    for item in items:
        if HERE in item.path.parents:
            item.add_marker(pytest.mark.gui)


class RecordingSystemHotkey:
    """system_hotkey's SystemHotkey without grabbing any keys on the user's desktop."""

    def __init__(self, consumer="callback", check_queue_interval=0.01):
        self.consumer = consumer
        self.bound = {}

    def register(self, hotkey, *args, callback=None, overwrite=False):
        self.bound[tuple(hotkey)] = callback if self.consumer == "callback" else args

    def unregister(self, hotkey):
        del self.bound[tuple(hotkey)]

    def press(self, hotkey):
        self.consumer("an event", hotkey, [self.bound[tuple(hotkey)]])


@pytest.fixture(scope="session")
def wx_app():
    if importlib.util.find_spec("wx") is None:
        pytest.skip("wxPython is not installed")
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("no display: DISPLAY and WAYLAND_DISPLAY are unset")
    import wx

    app = wx.App(False)
    yield app
    app.Destroy()


class GuiEnv:
    """One test's scratch Superpaper installation and the means to drive it."""

    def __init__(self, paths, root, ui, monkeypatch):
        self.monkeypatch = monkeypatch
        self.paths = paths
        self.root = root
        self.images = root / "images"
        self.settings_path = paths.config / "general_settings"
        self.ui = ui
        self.commands = []
        self.dialogs = []
        self.answer_yes = True
        self.unsaved_answer = Answer.DISCARD
        self.unsaved_prompts = []
        self.apply_answer = ApplyAnswer.CANCEL
        self.apply_prompts = []
        self.started = []
        self.opened_dialogs = []
        self.display_watchers = []
        self.os_notifies = True

    def watch_displays(self, on_change):
        """Stands in for the OS's display change notifications."""
        self.display_watchers.append(on_change)
        return self.os_notifies

    def change_displays(self, monitors, *, notifications=1):
        """The monitors change, and the OS reports it ``notifications`` times, as a burst."""
        self.monkeypatch.setattr(linux, "detect_monitors", lambda: monitors)
        for _ in range(notifications):
            self.display_watchers[-1]()

    def wait_for_displays(self, superpaper):
        """Run the event loop past the debounce and what it hands on."""
        end = time.monotonic() + 0.4
        self.wait_until(lambda: time.monotonic() > end)
        self.settle(superpaper)

    def ask_unsaved_changes(self, message, parent=None):
        """Stands in for the save/discard/cancel question: records it, answers ``unsaved_answer``."""
        self.unsaved_prompts.append(message)
        return self.unsaved_answer

    def ask_apply_with_unsaved_displays(self, parent=None, *, can_save):
        """Stands in for Apply's question about unsaved displays: records whether saving was
        offered, answers ``apply_answer``."""
        self.apply_prompts.append(can_save)
        return self.apply_answer

    def profile_file(self, name):
        return self.paths.profiles / f"{name}.profile"

    def write_profile(self, name, text):
        self.profile_file(name).write_text(text, encoding="utf-8")

    def start(self, *, settings=None, startup_profile=None):
        """A running Superpaper, quit when the test ends."""
        settings = settings or read_settings(self.settings_path) or first_run_settings(hotkeys_by_default=True)
        superpaper = self.ui.app.start_superpaper(self.ui.wx.Frame(None), self.paths, settings, linux, startup_profile)
        self.started.append(superpaper)
        return superpaper

    def quit(self, superpaper):
        """Quit through the tray menu's Exit."""
        self.started.remove(superpaper)
        self.click(superpaper, "Exit")

    def menu_entry(self, superpaper, label):
        """The tray menu's entry labelled ``label``, wherever it sits in the menu."""
        entries = []
        for entry in superpaper.tray.menu():
            entries += entry.items if isinstance(entry, Submenu) else [entry]
        return next(entry for entry in entries if getattr(entry, "label", None) == label)

    def click(self, superpaper, label):
        """Click the tray menu's entry labelled ``label``."""
        self.menu_entry(superpaper, label).action()

    def saved(self, superpaper, name):
        """The store's record of the saved profile ``name``, as the menus offer it."""
        return superpaper.store.get(ProfileId.parse(name, windows_names=False))

    def start_profile(self, superpaper, name):
        self.click(superpaper, name)
        self.settle(superpaper)

    def shown(self):
        """The dialogs shown since the last call, as (source module, type, first line)."""
        shown = list(self.dialogs)
        self.dialogs.clear()
        return shown

    def wait_until(self, predicate, timeout=30):
        """Run the wx event loop until ``predicate()`` is true."""
        deadline = time.monotonic() + timeout
        while True:
            self.ui.wx.YieldIfNeeded()
            if predicate():
                return
            if time.monotonic() > deadline:
                message = "timed out waiting for the condition"
                raise TimeoutError(message)
            time.sleep(0.005)

    def flush(self):
        """Run what has been handed to the main loop so far."""
        ran = []
        self.ui.wx.CallAfter(ran.append, True)
        self.wait_until(lambda: ran)

    def settle(self, superpaper):
        """Wait until the session has handled every request made so far, then run what it
        handed back to the main loop."""
        assert superpaper.session.wait_until_handled(10)
        self.flush()

    def open_editor(self, superpaper):
        """Open the wallpaper configuration as the tray does; returns its settings panel."""
        wx, editor = self.ui.wx, self.ui.editor
        before = set(wx.GetTopLevelWindows())
        self.click(superpaper, "Wallpaper Configuration")
        (frame,) = [
            window
            for window in wx.GetTopLevelWindows()
            if window not in before and isinstance(window, editor.ConfigFrame)
        ]
        return self.child_of(frame, editor.WallpaperSettingsPanel)

    def open_perspectives(self, editor):
        """The perspective dialog, opened through the editor's own handler."""
        return self.open_modal(self.ui.editor, "PerspectiveConfig", editor.onPerspectives)

    def open_browse(self, editor):
        """The browse dialog, opened through the editor's own handler."""
        return self.open_modal(self.ui.editor, "BrowsePaths", editor.onBrowsePaths)

    def open_modal(self, module, name, handler):
        """Run ``handler``, which shows the dialog ``module.name`` modally; the dialog is
        returned, left open instead of blocking, and destroyed when the test ends."""
        real = getattr(module, name)
        opened = []

        class OpenedAtOnce(real):
            def ShowModal(self):
                opened.append(self)
                return self.GetReturnCode()

            def Destroy(self):
                return False

        with self.monkeypatch.context() as patch:
            patch.setattr(module, name, OpenedAtOnce)
            handler(None)
        (dialog,) = opened
        self.opened_dialogs.append((dialog, real))
        return dialog

    def child_of(self, frame, kind):
        return next(child for child in frame.GetChildren() if isinstance(child, kind))

    def enable_hotkeys(self, superpaper):
        """Hotkeys on, bound through the recording system_hotkey."""
        superpaper.hotkeys = self.ui.hotkeys.Hotkeys(
            next_wallpaper=superpaper.session.next,
            pause=superpaper.session.toggle_pause,
            start_profile=superpaper.start_profile_by_id,
            call_soon=self.ui.wx.CallAfter,
            report=lambda message: self.dialogs.append(("hotkeys", "Error", message.splitlines()[0])),
            show_problems=True,
        )

    def yes_to_message_dialogs(self):
        """Answer yes/no questions (as the editor asks before deleting a profile) with Yes."""
        self.answer_yes = True

    def close(self):
        self.unsaved_answer = Answer.DISCARD
        for superpaper in list(self.started):
            self.quit(superpaper)
        self.flush()
        for dialog, real in self.opened_dialogs:
            real.Destroy(dialog)
        for window in self.ui.wx.GetTopLevelWindows():
            window.Destroy()
        self.flush()


def seed_images(images):
    images.mkdir()
    for name, colour in (("a.png", (200, 30, 30)), ("b.png", (30, 200, 30)), ("c.png", (30, 30, 200))):
        Image.new("RGB", (64, 36), colour).save(images / name)
    # Stored landscape, top half red, bottom half blue; EXIF orientation 6 = rotate 90° clockwise to view.
    rotated = Image.new("RGB", (40, 20), (220, 0, 0))
    rotated.paste((0, 0, 220), (0, 10, 40, 20))
    exif = Image.Exif()
    exif[0x0112] = 6
    rotated.save(images / "rotated.jpg", "JPEG", exif=exif.tobytes(), quality=95)


@pytest.fixture
def gui_env(wx_app, app_paths, tmp_path, monkeypatch):
    import wx

    import superpaper.desktop.hotkeys as hotkeys
    import superpaper.session
    import superpaper.ui.app as app
    import superpaper.ui.browse_dialog as browse_dialog
    import superpaper.ui.editor as editor
    import superpaper.ui.help as help_dialog
    import superpaper.ui.message as message
    import superpaper.ui.perspective_dialog as perspective_dialog
    import superpaper.ui.settings_dialog as settings_dialog
    import superpaper.ui.tray as tray
    from superpaper.desktop.linux import sni_tray

    ui = SimpleNamespace(
        wx=wx,
        app=app,
        browse_dialog=browse_dialog,
        editor=editor,
        message=message,
        help=help_dialog,
        hotkeys=hotkeys,
        perspective_dialog=perspective_dialog,
        session=superpaper.session,
        settings_dialog=settings_dialog,
        tray=tray,
    )
    env = GuiEnv(app_paths, tmp_path, ui, monkeypatch)
    seed_images(env.images)
    env.settings_path.write_text(SETTINGS, encoding="utf-8")
    env.write_profile("Work", SLIDESHOW.format(name="Work", images=env.images))
    env.write_profile("Home", STILL.format(name="Home", images=env.images))
    env.write_profile(
        "Nas",
        "name=Nas\nspanmode=single\nslideshow=false\ndisplay0paths=/nonexistent/nas\nselected=/nonexistent/nas/a.png\n",
    )
    # A profile with a value that can't be used: the app offers to delete it, once.
    env.write_profile("Broken", "name=Broken\ndelay=soon\n")

    monkeypatch.setattr(linux, "detect_monitors", lambda: TWO_DISPLAYS)
    monkeypatch.setattr(linux, "watch_displays", env.watch_displays)
    monkeypatch.setattr(app, "DISPLAY_CHANGE_DEBOUNCE_MS", 50)
    monkeypatch.setitem(sys.modules, "system_hotkey", SimpleNamespace(SystemHotkey=RecordingSystemHotkey))
    monkeypatch.setattr(sni_tray, "sni_supported", lambda: False)

    real_run = subprocess.run

    def recording_run(command, *args, **kwargs):
        env.commands.append(list(command))
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(process.subprocess, "run", recording_run)

    def dialog_recorder(source):
        def record_dialog(message, msg_type="Info", parent=None, style="OK"):
            env.dialogs.append((source, msg_type, str(message).splitlines()[0]))
            with ui.message.modal():
                return env.answer_yes if style == "YES_NO" else None

        return record_dialog

    for name, module in list(sys.modules.items()):
        if name.startswith("superpaper.ui.") and hasattr(module, "show_message_dialog"):
            monkeypatch.setattr(module, "show_message_dialog", dialog_recorder(name.rsplit(".", 1)[-1]))
        if name.startswith("superpaper.ui.") and hasattr(module, "ask_unsaved_changes"):
            monkeypatch.setattr(module, "ask_unsaved_changes", env.ask_unsaved_changes)
        if name.startswith("superpaper.ui.") and hasattr(module, "ask_apply_with_unsaved_displays"):
            monkeypatch.setattr(module, "ask_apply_with_unsaved_displays", env.ask_apply_with_unsaved_displays)

    yield env
    env.close()


@pytest.fixture
def superpaper(gui_env):
    """Superpaper started on the seeded settings and profiles; nothing runs yet."""
    return gui_env.start()


@pytest.fixture
def running_work(gui_env, superpaper):
    """``superpaper`` with the Work slideshow running."""
    gui_env.start_profile(superpaper, "Work")
    return superpaper


@pytest.fixture
def editor(gui_env, running_work):
    """The wallpaper configuration's settings panel, opened on the running profile."""
    return gui_env.open_editor(running_work)


@pytest.fixture
def snapshots(request, gui_env):
    """The golden files of the scenario in the test module (test_scenario_<name>.py)."""
    snapshots = Snapshots(request.module.__name__.rsplit("test_scenario_", 1)[1])
    snapshots.replace(str(gui_env.root), "<tmp>")
    return snapshots


@pytest.fixture
def saved_layout(gui_env):
    """The layout of the two fixed monitors as a user has saved it: the default positions and
    one perspective, "wall", that isn't the default."""
    layout = display_store.load(gui_env.paths.config, display_detection.detect_displays(linux))
    count = len(layout.displays)
    viewer_position = (0.0, 0.0, layout.max_ppi() * 1200 / 25.4)
    wall = Perspective(
        "wall",
        0,
        viewer_position,
        (Swivel(SwivelAxis.NONE, 0.0, 0.0, 0.0),) * count,
        (Tilt(0.0, 0.0, 0.0),) * count,
    )
    layout = layout.with_perspective(wall, use_perspective=True, is_default=False)
    display_store.save_layout(gui_env.paths.config, layout)
    return layout
