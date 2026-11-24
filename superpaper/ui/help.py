"""Help: the help window, and the help popups of the editor and its dialogs."""

from dataclasses import replace

import wx  # ty:ignore[unresolved-import]

from superpaper.paths import resource

PERSPECTIVE_HELP = (
    "Perspective corrections were created to fix the\n"
    "wallpaper misalignment that arises when your displays\n"
    "are not in a common plane, like they would be on the\n"
    "wall. Straight lines are cut into pieces when displays\n"
    "are both tilted and turned respective to each other.\n"
    "These corrections work by undoing the perspective changes\n"
    "caused by the rotation of the displays.\n"
    "\n"
    "In this dialog you may configure perspective setting\n"
    "profiles, and test their effects with the tools in the\n"
    "lower left corner."
)

PERSPECTIVE_PROFILE_HELP = (
    "Perspective corrections do not work equally well\n"
    "with different kinds of images so you can create\n"
    "separate profiles, such as 'tilts_only' or 'swivel+tilt'"
)

CENTRAL_DISPLAY_HELP = (
    "To compute the perspective transforms the (rough)\n"
    "position of your eyes relative to your displays\n"
    "needs to be known. This is entered by selecting\n"
    "one display as the central display and entering\n"
    "distance offsets relative to that display's center.\n"
    "\n"
    "Distance must be entered and non-zero, horizontal\n"
    "and vertical offsets are optional. Lengths are\n"
    "in millimeters."
)

DISPLAY_ROTATION_HELP = (
    "Here you enter the display rotation (tilt and swivel)\n"
    "parameters. Use these parameters to tell how your displays\n"
    "are rotated relative to the setup where they would be in a\n"
    "common plane.\n"
    "The parameters are:\n"
    "     - swivel axis: left or right edge of the display\n"
    "     - swivel angle in degrees\n"
    "     - swivel axis lateral offset from display edge [mm]\n"
    "     - swivel axis depth offset from display edge [mm]\n"
    "     - tilt angle in degrees\n"
    "     - tilt axis vertical offset from horizontal midline [mm]\n"
    "     - tilt axis depth offset from display surface [mm]",
    "Signs of angles are determined by the right hand rule:\n"
    "Grab the rotation axis with your right hand fist and extend\n"
    "your thumb in the direction of the axis: up for swivels and\n"
    "left for tilts. Now the direction of your curled fingers will\n"
    "tell the direction the display will rotate with a positive angle\n"
    "and the rotation is reversed for a negative angle.",
    "The axis offsets are completely optional. The most important\n"
    "one is the tilt axis DEPTH offset since the actual axis\n"
    "of the tilt is the joint in the display mount behind the panel.\n"
    "Without this depth offset the tilt is performed around the display\n"
    "horizontal midline which is on the display surface.",
)

POSITIONS_HELP = (
    "In this dialog you may adjust the positions of your displays\n"
    "more accurately by either entering measurements or just\n"
    "fine tune the dragged positions by trial and error. You can\n"
    "either enter the positions in millimeters or in the pixels\n"
    "of the used image. Position update might be inaccurate if you\n"
    "need to move a display substantially outside the shown area.\n"
    "In this case save the current position and then proceed to\n"
    "correct the position further.\n"
    "\n"
    "Current positions of the edges of each display Left, Top,\n"
    "Right, Bottom are given as measured from the top left\n"
    "corner of the display area such that the left-most and\n"
    "top-most edge are at 0. Right, Bottom edge positions\n"
    "include bezel sizes."
)


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
        self.button_close.Bind(wx.EVT_BUTTON, lambda event: self.frame.Close(True))
        self.frame.Bind(wx.EVT_CLOSE, self.onClose)
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
            and this means that to get a correctly spanned image across  the monitor array,  the  relative
            physical locations of the displays needs to be known.  A  configuration  is guessed but if your
            monitors  are  arranged  in  another  way,  you  can  adjust  the  positions  of  the  displays  by
            entering the 'Positions' tool and dragging the display previews.

    - Bezel correction:
            Display bezel thicknesses and gaps can be taken into account when computing the wallpaper
            span.  Enter bezel sizes with the  'Configure'  button next to  'Adjust bezel sizes'  in the
            display settings. Adjacent bezels and gap are added together.

    - Display size detection:
            To apply PPI correction Superpaper needs to know the physical sizes of your displays.  These
            are  attempted to be detected  automatically.  If this fails,  you can enter  the  correct  values
            under 'Input display sizes manually'.

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
        """Saves the checkbox state when the window closes, however it is closed."""
        show_help = self.cb_show_at_start.GetValue()
        settings = self._get_settings()
        if settings.show_help != show_help:
            self._update_settings(replace(settings, show_help=show_help))
        event.Skip()


class HelpPopup(wx.PopupTransientWindow):
    """Popup to show a bit of static text, optionally followed by a line of quality advice."""

    def __init__(self, parent, text, quality_text=None, style=wx.BORDER_DEFAULT):
        wx.PopupTransientWindow.__init__(self, parent, style)
        pnl = wx.Panel(self)

        paragraphs = [text] if isinstance(text, str) else list(text)
        if quality_text is not None:
            paragraphs.append(quality_text)
        sizer = wx.BoxSizer(wx.VERTICAL)
        for paragraph in paragraphs:
            sizer.Add(wx.StaticText(pnl, -1, paragraph), 0, wx.ALL, 5)
        pnl.SetSizer(sizer)
        sizer.Fit(pnl)
        sizer.Fit(self)
        self.Layout()

    def OnDismiss(self):
        self.Destroy()


def show_help_popup(parent, text, button, quality_text=None):
    """Pop ``text`` (a string, or a string for each paragraph) up below ``button``,
    followed by ``quality_text`` if given."""
    popup = HelpPopup(parent, text, quality_text)
    popup.Position(button.ClientToScreen((0, 0)), wx.Size(0, button.GetSize()[1]))
    popup.Popup()


def help_button(parent: wx.Window, text: str | tuple[str, ...]) -> wx.BitmapButton:
    """A "?" button on ``parent`` that pops ``text`` up below itself."""
    bitmap = wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_BUTTON, wx.Size(20, 20))
    button = wx.BitmapButton(parent, bitmap=wx.BitmapBundle(bitmap))
    button.Bind(wx.EVT_BUTTON, lambda event: show_help_popup(parent, text, button))
    return button


def image_quality_advice(source_size):
    """The sentence on how large wallpapers should be, given the (width, height) of the
    image the settings call for."""
    return (
        "For the best image quality with current settings your\n"
        f" wallpapers should be {source_size[0]}x{source_size[1]} or larger."
    )
