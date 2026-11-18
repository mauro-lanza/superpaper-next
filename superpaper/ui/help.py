"""Help: the help window, and the help popups of the editor and its dialogs."""

import wx  # ty:ignore[unresolved-import]

from superpaper.paths import resource


class HelpFrame(wx.Frame):
    """Help dialog frame."""

    def __init__(self, get_settings, update_settings, parent=None):
        wx.Frame.__init__(self, parent=parent, title="Superpaper Help")
        self.frame_sizer = wx.BoxSizer(wx.VERTICAL)
        help_panel = HelpPanel(self, get_settings, update_settings)
        self.frame_sizer.Add(help_panel, 1, wx.EXPAND)
        self.SetAutoLayout(True)
        self.SetSizer(self.frame_sizer)
        self.SetIcon(wx.Icon(str(resource("superpaper.png")), wx.BITMAP_TYPE_PNG))
        self.Fit()
        self.Layout()
        self.Center()
        self.Show()


class HelpPanel(wx.Panel):
    """Help dialog contents."""

    def __init__(self, parent, get_settings, update_settings):
        wx.Panel.__init__(self, parent)
        self.frame = parent
        self._get_settings = get_settings
        self._update_settings = update_settings
        self.sizer_main = wx.BoxSizer(wx.VERTICAL)
        self.sizer_helpcontent = wx.BoxSizer(wx.VERTICAL)
        self.sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)

        show_help = get_settings().show_help

        self.cb_show_at_start = wx.CheckBox(self, -1, "Show this help at start")
        self.cb_show_at_start.SetValue(show_help)
        self.button_close = wx.Button(self, label="Close")
        self.button_close.Bind(wx.EVT_BUTTON, self.onClose)
        self.sizer_buttons.AddStretchSpacer()
        self.sizer_buttons.Add(self.cb_show_at_start, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.sizer_buttons.Add(self.button_close, 0, wx.CENTER | wx.ALL, 5)

        help_str = """
How to use Superpaper:

In the Wallpaper Configuration you can adjust all your wallpaper settings.  Other  application  wide
settings  can be  changed in the  Settings menu.  Both  are  accessible from the  system tray menu.

IMPORTANT NOTE: For the wallpapers to be set correctly, you must set in your OS the background
fitting option to 'Span'.

Description of Wallpaper Configuration 'advanced span' options:
    In advanced span mode PPI, bezel and perspective corrections are applied to the wallpaper. The
    following settings are used to configure this:

    - Physical display positions:
            In 'advanced span' mode Superpaper corrects for different pixel densities between displays
            and this means that to get a corretly  spanned image across  the monitor array,  the  relative
            physical locations of the displays needs to be known.  A  configuration  is guessed but if your
            monitors  are  arranged  in  another  way,  you  can  adjust  the  positions  of  the  displays  by
            entering the 'Positions' tool and dragging the display previews.

    - Bezel correction:
            Display bezel thicknesses and gaps can be taken into account when computing the wallpaper
            span.  Enter bezel sizes by selecting  'Configure bezels'  in  Advanced  Wallpaper  Adjustment
            subsection. Adjacent bezels and gap are added together.

    - Display size detection:
            To apply PPI correction Superpaper needs to know the physical sizes of your displays.  These
            are  attempted to be detected  automatically.  If this fails,  you can enter  the  correct  values
            under 'Display Diagonal Sizes'.

    - Display rotations and viewer position
            Perspective corrections use the position of the viewer and the 3D alignment of the displays to
            adjust the shown image. Details on how to configure this are in the helps of the perspective
            configuration dialog.

Tips:
    - Superpaper running in the background is controlled from the Tray Icon/Applet.
    - To start Superpaper in the background, disable the 'Show this help at start' checkbox.
    - You can use the given example profiles as templates: just change the name and whatever else,
      save, and its a new profile.
    - 'Align Test' feature allows you to test your alignment settings.
"""
        st_help = wx.TextCtrl(self, -1, help_str, size=wx.Size(700, 400), style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.sizer_helpcontent.Add(st_help, 1, wx.EXPAND | wx.CENTER | wx.ALL, 5)

        self.sizer_main.Add(self.sizer_helpcontent, 1, wx.CENTER | wx.EXPAND)
        self.sizer_main.Add(self.sizer_buttons, 0, wx.CENTER | wx.EXPAND)
        self.SetSizer(self.sizer_main)
        self.sizer_main.Fit(parent)

    def onClose(self, event):
        """Closes help dialog. Saves checkbox state as needed."""
        show_help = self.cb_show_at_start.GetValue()
        if self._get_settings().show_help != show_help:
            self._update_settings(show_help=show_help)
        self.frame.Close(True)


class HelpPopup(wx.PopupTransientWindow):
    """Popup to show a bit of static text, optionally followed by a line of quality advice."""

    def __init__(self, parent, text, quality_text=None, style=wx.BORDER_DEFAULT):
        wx.PopupTransientWindow.__init__(self, parent, style)
        pnl = wx.Panel(self)

        stlist = []
        if isinstance(text, str):
            st = wx.StaticText(pnl, -1, text)
            stlist.append(st)
        else:
            for textstr in text:
                st = wx.StaticText(pnl, -1, textstr)
                stlist.append(st)
        sizer = wx.BoxSizer(wx.VERTICAL)
        for st in stlist:
            sizer.Add(st, 0, wx.ALL, 5)
        if quality_text is not None:
            st_qual = wx.StaticText(pnl, -1, quality_text)
            sizer.Add(st_qual, 0, wx.ALL, 5)
        pnl.SetSizer(sizer)
        sizer.Fit(pnl)
        sizer.Fit(self)
        self.Layout()

    def ProcessLeftDown(self, event):
        return wx.PopupTransientWindow.ProcessLeftDown(self, event)

    def OnDismiss(self):
        self.Destroy()


def show_help_popup(parent, text, button, quality_text=None):
    """Pop ``text`` (a string, or a string for each paragraph) up below ``button``,
    followed by ``quality_text`` if given."""
    popup = HelpPopup(parent, text, quality_text)
    popup.Position(button.ClientToScreen((0, 0)), wx.Size(0, button.GetSize()[1]))
    popup.Popup()


def image_quality_advice(source_size):
    """The sentence on how large wallpapers should be, given the (width, height) of the
    image the settings call for."""
    return (
        "For the best image quality with current settings your\n"
        f" wallpapers should be {source_size[0]}x{source_size[1]} or larger."
    )
