"""Telling the user something: a message dialog, printed instead when there is no GUI;
and the end of a draft the editor asked for."""

from typing import Any

# wxPython is optional (the CLI runs without it); the name stays bound either way.
wx: Any = None
try:
    import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]
except ImportError:
    pass


def show_message_dialog(message, msg_type="Info", parent=None, style="OK"):
    """General purpose info dialog in GUI mode, falls back to print in CLI mode."""
    # Type can be 'Info', 'Error', 'Question', 'Exclamation'
    # In CLI mode there is no wx.App, so fall back to printing the message.
    if wx is None or wx.App.Get() is None:
        print(f"[{msg_type}] {message}")
        if style == "YES_NO":
            return False
        return
    if style == "OK":
        dial = wx.MessageDialog(parent, message, msg_type, wx.OK | wx.STAY_ON_TOP | wx.CENTRE)
        dial.ShowModal()
    elif style == "YES_NO":
        dial = wx.MessageDialog(parent, message, msg_type, wx.YES_NO | wx.STAY_ON_TOP | wx.CENTRE)
        res = dial.ShowModal()
        return res == wx.ID_YES


def draft_shown(problem):
    """Finish a draft (Apply, an align test) on the main thread once it is done: end the
    busy cursor it started, and say why it wasn't shown, if it wasn't. The dialog that
    asked for it may be closed by then."""
    wx.EndBusyCursor()
    if problem is not None:
        show_message_dialog(problem, "Error")
