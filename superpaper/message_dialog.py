"""Error etc. info dialog."""

import wx


def show_message_dialog(message, msg_type="Info", parent=None, style="OK"):
    """General purpose info dialog in GUI mode, falls back to print in CLI mode."""
    # Type can be 'Info', 'Error', 'Question', 'Exclamation'
    # In CLI mode there is no wx.App, so fall back to printing the message.
    if wx.App.Get() is None:
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
        if res == wx.ID_YES:
            return True
        else:
            return False
