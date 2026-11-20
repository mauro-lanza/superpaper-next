"""Telling the user something, or asking: a message dialog, and the end of an align test the editor asked for."""

from typing import Literal

import wx  # ty:ignore[unresolved-import]

from superpaper.unsaved_changes import Answer, ApplyAnswer


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


def ask_apply_with_unsaved_displays(parent: wx.Window | None, *, can_save: bool) -> ApplyAnswer:
    """Ask how to apply while the display layout has unsaved changes; without ``can_save``
    (the layout is invalid) saving it is not offered."""
    message = "Displays have unsaved changes."
    if can_save:
        dial = wx.MessageDialog(parent, message, "Unsaved changes", wx.YES_NO | wx.CANCEL | wx.STAY_ON_TOP | wx.CENTRE)
        dial.SetYesNoCancelLabels(
            ApplyAnswer.SAVE_DISPLAYS.value, ApplyAnswer.USE_SAVED_DISPLAYS.value, ApplyAnswer.CANCEL.value
        )
    else:
        dial = wx.MessageDialog(parent, message, "Unsaved changes", wx.YES_NO | wx.STAY_ON_TOP | wx.CENTRE)
        dial.SetYesNoLabels(ApplyAnswer.USE_SAVED_DISPLAYS.value, ApplyAnswer.CANCEL.value)
    result = dial.ShowModal()
    if result == wx.ID_YES:
        return ApplyAnswer.SAVE_DISPLAYS if can_save else ApplyAnswer.USE_SAVED_DISPLAYS
    if result == wx.ID_NO and can_save:
        return ApplyAnswer.USE_SAVED_DISPLAYS
    return ApplyAnswer.CANCEL


def draft_shown(problem: str | None):
    """Finish an align test on the main thread once it is done: end the
    busy cursor it started, and say why it wasn't shown, if it wasn't. The dialog that
    asked for it may be closed by then."""
    wx.EndBusyCursor()
    if problem is not None:
        show_message_dialog(problem, "Error")
