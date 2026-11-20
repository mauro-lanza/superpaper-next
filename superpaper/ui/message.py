"""Telling the user something: a message dialog, and the end of a draft the editor asked for."""

from typing import Literal

import wx  # ty:ignore[unresolved-import]

from superpaper.unsaved_changes import Answer


def show_message_dialog(
    message: str,
    msg_type: str = "Info",
    parent: wx.Window | None = None,
    style: Literal["OK", "YES_NO"] = "OK",
) -> bool:
    """Show a modal dialog; return whether the user chose Yes (always True for an "OK" dialog)."""
    if style == "YES_NO":
        dial = wx.MessageDialog(parent, message, msg_type, wx.YES_NO | wx.STAY_ON_TOP | wx.CENTRE)
        return dial.ShowModal() == wx.ID_YES
    dial = wx.MessageDialog(parent, message, msg_type, wx.OK | wx.STAY_ON_TOP | wx.CENTRE)
    dial.ShowModal()
    return True


def ask_unsaved_changes(message: str, parent: wx.Window | None = None) -> Answer:
    """Ask whether to save, discard or keep the unsaved changes ``message`` names."""
    dial = wx.MessageDialog(parent, message, "Unsaved changes", wx.YES_NO | wx.CANCEL | wx.STAY_ON_TOP | wx.CENTRE)
    dial.SetYesNoCancelLabels("Save", "Discard", "Cancel")
    match dial.ShowModal():
        case wx.ID_YES:
            return Answer.SAVE
        case wx.ID_NO:
            return Answer.DISCARD
        case _:
            return Answer.CANCEL


def draft_shown(problem: str | None):
    """Finish a draft (Apply, an align test) on the main thread once it is done: end the
    busy cursor it started, and say why it wasn't shown, if it wasn't. The dialog that
    asked for it may be closed by then."""
    wx.EndBusyCursor()
    if problem is not None:
        show_message_dialog(problem, "Error")
