"""Help: the help window, and the help popups of the editor and its dialogs."""

import sys
from dataclasses import replace

import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

import superpaper.perspective as persp
import superpaper.render as render
from superpaper.paths import resource
from superpaper.settings import read_settings, write_settings


class HelpFrame(wx.Frame):
    """Help dialog frame."""

    def __init__(self, settings_path, parent=None):
        wx.Frame.__init__(self, parent=parent, title="Superpaper Help")
        self.frame_sizer = wx.BoxSizer(wx.VERTICAL)
        help_panel = HelpPanel(self, settings_path)
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

    def __init__(self, parent, settings_path):
        wx.Panel.__init__(self, parent)
        self.frame = parent
        self.settings_path = settings_path
        self.sizer_main = wx.BoxSizer(wx.VERTICAL)
        self.sizer_helpcontent = wx.BoxSizer(wx.VERTICAL)
        self.sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)

        show_help = read_settings(settings_path, sys.platform).show_help

        # st_show_at_start = wx.StaticText(self, -1, "Show this help at start")
        self.cb_show_at_start = wx.CheckBox(self, -1, "Show this help at start")
        self.cb_show_at_start.SetValue(show_help)
        self.button_close = wx.Button(self, label="Close")
        self.button_close.Bind(wx.EVT_BUTTON, self.onClose)
        self.sizer_buttons.AddStretchSpacer()
        # self.sizer_buttons.Add(st_show_at_start, 0, wx.ALIGN_CENTER_VERTICAL|wx.ALL, 5)
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
        # st_help = wx.StaticText(self, -1, help_str)
        st_help = wx.TextCtrl(self, -1, help_str, size=wx.Size(700, 400), style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.sizer_helpcontent.Add(st_help, 1, wx.EXPAND | wx.CENTER | wx.ALL, 5)

        self.sizer_main.Add(self.sizer_helpcontent, 1, wx.CENTER | wx.EXPAND)
        self.sizer_main.Add(self.sizer_buttons, 0, wx.CENTER | wx.EXPAND)
        self.SetSizer(self.sizer_main)
        self.sizer_main.Fit(parent)

    def onClose(self, event):
        """Closes help dialog. Saves checkbox state as needed."""
        show_help = self.cb_show_at_start.GetValue()
        settings = read_settings(self.settings_path, sys.platform)
        if settings.show_help != show_help:
            write_settings(self.settings_path, replace(settings, show_help=show_help))
        self.frame.Close(True)


class HelpPopup(wx.PopupTransientWindow):
    """Popup to show a bit of static text"""

    def __init__(
        self,
        parent,
        text,
        show_image_quality=False,
        use_perspective=False,
        persp_name=None,
        style=wx.BORDER_DEFAULT,
    ):
        wx.PopupTransientWindow.__init__(self, parent, style)
        self.mainframe = parent.frame
        self.display_sys = None
        # self.mainframe = parent.parent # persp dialog
        if show_image_quality:
            self.display_sys = self.mainframe.display_sys
            self.advanced_on = self.mainframe.show_advanced_settings
            self.show_image_quality = not self.mainframe.use_multi_image
            self.use_perspective = use_perspective
            self.persp_name = persp_name
        else:
            self.advanced_on = False
            self.show_image_quality = False
            self.use_perspective = False
            self.persp_name = None
        pnl = wx.Panel(self)
        # pnl.SetBackgroundColour("CADET BLUE")

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
        if self.show_image_quality:
            st_qual = wx.StaticText(pnl, -1, self.string_ideal_image_size())
            sizer.Add(st_qual, 0, wx.ALL, 5)
        pnl.SetSizer(sizer)
        sizer.Fit(pnl)
        sizer.Fit(self)
        self.Layout()

    def ProcessLeftDown(self, event):
        return wx.PopupTransientWindow.ProcessLeftDown(self, event)

    def OnDismiss(self):
        self.Destroy()

    def string_ideal_image_size(self):
        "Return a sentence what the minimum source image size is for best quality."
        senten = (
            "For the best image quality with current settings your\n"
            r" wallpapers should be {} or larger."
        )
        display_sys = self.display_sys  # every popup that shows the image quality has one
        if display_sys is None:
            return ""
        if self.advanced_on:
            if self.mainframe.cb_offsets.GetValue():
                offsets = []
                for tc in self.mainframe.tc_list_offsets:
                    off_str = tc.GetValue().split(",")
                    try:
                        offsets.append((int(off_str[0]), int(off_str[1])))
                    except ValueError, IndexError:
                        offsets.append((0, 0))
            else:
                offsets = len(display_sys.disp_list) * [(0, 0)]
            crops = display_sys.get_ppi_norm_crops(offsets)
            persp_data = None
            if self.use_perspective:
                persp_data = display_sys.get_persp_data(self.persp_name)
            if persp_data:
                proj_plane_crops, persp_coeffs = persp.get_backprojected_display_system(crops, persp_data)
                # Canvas containing back-projected displays
                canv = render.compute_working_canvas(proj_plane_crops)
            else:
                canv = render.compute_working_canvas(crops)
        else:
            canv = render.compute_canvas(display_sys.resolutions(), display_sys.digital_offsets())
        res_str = f"{canv[0]}x{canv[1]}"
        fin = senten.format(res_str)
        return fin
