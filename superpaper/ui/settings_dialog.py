"""The general settings window."""

from dataclasses import replace

import wx  # ty:ignore[unresolved-import]


class SettingsFrame(wx.Frame):
    """The general settings window: see SettingsPanel."""

    def __init__(self, get_settings, save_settings):
        wx.Frame.__init__(self, parent=None, title="Superpaper General Settings")
        self.frame_sizer = wx.BoxSizer(wx.VERTICAL)
        settings_panel = SettingsPanel(self, get_settings, save_settings)
        self.frame_sizer.Add(settings_panel, 1, wx.EXPAND)
        self.SetSizer(self.frame_sizer)
        self.Fit()
        self.Layout()
        self.Center()
        self.Show()


class SettingsPanel(wx.Panel):
    """The general settings window's contents, showing ``get_settings()``; ``save_settings(settings)``
    saves the fields as the new settings."""

    def __init__(self, parent, get_settings, save_settings):
        wx.Panel.__init__(self, parent)
        self._get_settings = get_settings
        self._save_settings = save_settings
        self.sizer_main = wx.BoxSizer(wx.VERTICAL)
        self.sizer_grid_settings = wx.GridSizer(3, 2, 5, 5)
        self.sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)
        pnl = self
        st_logging = wx.StaticText(pnl, -1, "Logging")
        st_warn_large = wx.StaticText(pnl, -1, "Large image warning")
        st_setcmd = wx.StaticText(pnl, -1, "Custom command")
        self.cb_logging = wx.CheckBox(pnl, -1, "")
        self.cb_warn_large = wx.CheckBox(pnl, -1, "")
        self.tc_setcmd = wx.TextCtrl(pnl, -1, size=wx.Size(200, -1))

        self.sizer_grid_settings.AddMany(
            [
                (st_logging, 0, wx.ALIGN_RIGHT),
                (self.cb_logging, 0, wx.ALIGN_LEFT),
                (st_warn_large, 0, wx.ALIGN_RIGHT),
                (self.cb_warn_large, 0, wx.ALIGN_LEFT),
                (st_setcmd, 0, wx.ALIGN_RIGHT),
                (self.tc_setcmd, 0, wx.ALIGN_LEFT),
            ]
        )
        g_settings = get_settings()
        self.cb_logging.SetValue(g_settings.logging)
        self.cb_warn_large.SetValue(g_settings.warn_large_img)
        self.tc_setcmd.ChangeValue(g_settings.set_command)
        self.button_save = wx.Button(self, label="Save")
        self.button_close = wx.Button(self, label="Close")
        self.button_save.Bind(wx.EVT_BUTTON, self.onSave)
        self.button_close.Bind(wx.EVT_BUTTON, self.onClose)
        self.sizer_buttons.AddStretchSpacer()
        self.sizer_buttons.Add(self.button_save, 0, wx.ALL, 5)
        self.sizer_buttons.Add(self.button_close, 0, wx.ALL, 5)
        self.sizer_main.Add(self.sizer_grid_settings, 0, wx.CENTER | wx.EXPAND | wx.ALL, 5)
        self.sizer_main.Add(self.sizer_buttons, 0, wx.EXPAND)
        self.SetSizer(self.sizer_main)
        self.sizer_main.Fit(parent)

    def onSave(self, event):
        """Saves settings to file."""
        self._save_settings(
            replace(
                self._get_settings(),
                logging=self.cb_logging.GetValue(),
                warn_large_img=self.cb_warn_large.GetValue(),
                set_command=self.tc_setcmd.GetLineText(0).strip(),
            )
        )

    def onClose(self, event):
        """Closes settings panel."""
        self.GetParent().Close(True)
