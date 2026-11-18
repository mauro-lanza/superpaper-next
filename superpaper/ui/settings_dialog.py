"""The general settings window."""

import wx  # ty:ignore[unresolved-import]

from superpaper.settings import format_hotkey, parse_hotkey


class SettingsFrame(wx.Frame):
    """The general settings window: see SettingsPanel."""

    def __init__(self, settings, save_settings):
        wx.Frame.__init__(self, parent=None, title="Superpaper General Settings")
        self.frame_sizer = wx.BoxSizer(wx.VERTICAL)
        settings_panel = SettingsPanel(self, settings, save_settings)
        self.frame_sizer.Add(settings_panel, 1, wx.EXPAND)
        self.SetAutoLayout(True)
        self.SetSizer(self.frame_sizer)
        self.Fit()
        self.Layout()
        self.Center()
        self.Show()


class SettingsPanel(wx.Panel):
    """The general settings window's contents, showing ``settings``; ``save_settings(**changes)``
    saves the fields as the new settings."""

    def __init__(self, parent, settings, save_settings):
        wx.Panel.__init__(self, parent)
        self.frame = parent
        self._save_settings = save_settings
        self.sizer_main = wx.BoxSizer(wx.VERTICAL)
        self.sizer_grid_settings = wx.GridSizer(6, 2, 5, 5)
        self.sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)
        pnl = self
        st_logging = wx.StaticText(pnl, -1, "Logging")
        st_usehotkeys = wx.StaticText(pnl, -1, "Use hotkeys")
        st_warn_large = wx.StaticText(pnl, -1, "Large image warning")
        st_hk_next = wx.StaticText(pnl, -1, "Hotkey: Next wallpaper")
        st_hk_pause = wx.StaticText(pnl, -1, "Hotkey: Pause slideshow")
        st_setcmd = wx.StaticText(pnl, -1, "Custom command")
        self.cb_logging = wx.CheckBox(pnl, -1, "")
        self.cb_usehotkeys = wx.CheckBox(pnl, -1, "")
        self.cb_warn_large = wx.CheckBox(pnl, -1, "")
        self.tc_hk_next = wx.TextCtrl(pnl, -1, size=wx.Size(200, -1))
        self.tc_hk_pause = wx.TextCtrl(pnl, -1, size=wx.Size(200, -1))
        self.tc_setcmd = wx.TextCtrl(pnl, -1, size=wx.Size(200, -1))

        self.sizer_grid_settings.AddMany(
            [
                (st_logging, 0, wx.ALIGN_RIGHT),
                (self.cb_logging, 0, wx.ALIGN_LEFT),
                (st_usehotkeys, 0, wx.ALIGN_RIGHT),
                (self.cb_usehotkeys, 0, wx.ALIGN_LEFT),
                (st_warn_large, 0, wx.ALIGN_RIGHT),
                (self.cb_warn_large, 0, wx.ALIGN_LEFT),
                (st_hk_next, 0, wx.ALIGN_RIGHT),
                (self.tc_hk_next, 0, wx.ALIGN_LEFT),
                (st_hk_pause, 0, wx.ALIGN_RIGHT),
                (self.tc_hk_pause, 0, wx.ALIGN_LEFT),
                (st_setcmd, 0, wx.ALIGN_RIGHT),
                (self.tc_setcmd, 0, wx.ALIGN_LEFT),
            ]
        )
        self.update_fields(settings)
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

    def update_fields(self, g_settings):
        """Updates dialog field contents."""
        self.cb_logging.SetValue(g_settings.logging)
        self.cb_usehotkeys.SetValue(g_settings.use_hotkeys)
        self.cb_warn_large.SetValue(g_settings.warn_large_img)
        self.tc_hk_next.ChangeValue(format_hotkey(g_settings.hk_binding_next))
        self.tc_hk_pause.ChangeValue(format_hotkey(g_settings.hk_binding_pause))
        self.tc_setcmd.ChangeValue(g_settings.set_command)

    def onSave(self, event):
        """Saves settings to file."""
        self._save_settings(
            logging=self.cb_logging.GetValue(),
            use_hotkeys=self.cb_usehotkeys.GetValue(),
            warn_large_img=self.cb_warn_large.GetValue(),
            hk_binding_next=parse_hotkey(self.tc_hk_next.GetLineText(0)),
            hk_binding_pause=parse_hotkey(self.tc_hk_pause.GetLineText(0)),
            set_command=self.tc_setcmd.GetLineText(0).strip(),
        )

    def onClose(self, event):
        """Closes settings panel."""
        self.frame.Close(True)
