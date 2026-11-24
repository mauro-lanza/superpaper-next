"""Telling the user something, or asking: a message dialog, and the end of an align test the editor asked for."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import wx  # ty:ignore[unresolved-import]

from superpaper.unsaved_changes import Answer, ApplyAnswer, apply_answer

_open_modals = 0
_when_closed: list[Callable[[], None]] = []


@contextmanager
def modal() -> Iterator[None]:
    """While it runs, a modal is open: the event loop goes on, so handlers can start under
    the one that opened it. What mustn't happen then waits in ``when_modals_closed``."""
    global _open_modals
    _open_modals += 1
    try:
        yield
    finally:
        _open_modals -= 1
        if _open_modals == 0:
            closed = list(_when_closed)
            _when_closed.clear()
            for action in closed:
                wx.CallAfter(action)  # after the handler that opened the modal has finished


def in_modal() -> bool:
    return _open_modals > 0


def when_modals_closed(action: Callable[[], None]) -> None:
    """Run ``action`` on the main loop once no modal is open; asking again meanwhile counts once."""
    if action not in _when_closed:
        _when_closed.append(action)


def show_modal(dialog: wx.Dialog) -> int:
    """Show ``dialog`` modally and return its result. Every modal of the editor goes through here."""
    with modal():
        return dialog.ShowModal()


def show_message(message: str, title: str = "Info", parent: wx.Window | None = None) -> None:
    """Show a modal message with an OK button."""
    with wx.MessageDialog(parent, message, title, wx.OK | wx.STAY_ON_TOP | wx.CENTRE) as dial:
        show_modal(dial)


def confirm(message: str, title: str = "Info", parent: wx.Window | None = None) -> bool:
    """Show a modal Yes / No question; return whether the user chose Yes."""
    with wx.MessageDialog(parent, message, title, wx.YES_NO | wx.STAY_ON_TOP | wx.CENTRE) as dial:
        return show_modal(dial) == wx.ID_YES


def _answer(result: int) -> Answer:
    """The button of a Yes / No / Cancel question that closed the dialog."""
    match result:
        case wx.ID_YES:
            return Answer.SAVE
        case wx.ID_NO:
            return Answer.DISCARD
        case _:
            return Answer.CANCEL


def ask_unsaved_changes(message: str, parent: wx.Window | None = None) -> Answer:
    """Ask whether to save, discard or keep the unsaved changes ``message`` names."""
    with wx.MessageDialog(
        parent, message, "Unsaved changes", wx.YES_NO | wx.CANCEL | wx.STAY_ON_TOP | wx.CENTRE
    ) as dial:
        dial.SetYesNoCancelLabels("Save", "Discard", "Cancel")
        return _answer(show_modal(dial))


def ask_apply_with_unsaved_displays(parent: wx.Window | None, *, can_save: bool) -> ApplyAnswer:
    """Ask how to apply while the display layout has unsaved changes; without ``can_save``
    (the layout is invalid) saving it is not offered."""
    message = "Displays have unsaved changes."
    buttons = wx.YES_NO | wx.CANCEL if can_save else wx.YES_NO
    with wx.MessageDialog(parent, message, "Unsaved changes", buttons | wx.STAY_ON_TOP | wx.CENTRE) as dial:
        if can_save:
            dial.SetYesNoCancelLabels(
                ApplyAnswer.SAVE_DISPLAYS.value, ApplyAnswer.USE_SAVED_DISPLAYS.value, ApplyAnswer.CANCEL.value
            )
        else:
            dial.SetYesNoLabels(ApplyAnswer.USE_SAVED_DISPLAYS.value, ApplyAnswer.CANCEL.value)
        return apply_answer(_answer(show_modal(dial)), can_save=can_save)


def draft_shown(problem: str | None):
    """Finish an align test on the main thread once it is done: end the
    busy cursor it started, and say why it wasn't shown, if it wasn't. The dialog that
    asked for it may be closed by then."""
    wx.EndBusyCursor()
    if problem is not None:
        show_message(problem, "Error")
