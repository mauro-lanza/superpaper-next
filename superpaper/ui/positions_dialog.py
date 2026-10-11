"""Entering display positions exactly, in millimetres or pixels."""

import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

from superpaper.paths import resource
from superpaper.ui.help import HelpPopup
from superpaper.ui.message import show_message_dialog


class DisplayPositionEntry(wx.Frame):
    """Display position fine control dialog."""

    def __init__(self, parent, dragged_positions=False):
        wx.Frame.__init__(self, parent.frame, -1, "Enter display positions")
        self.ToggleWindowStyle(wx.STAY_ON_TOP)
        self.SetIcon(wx.Icon(str(resource("superpaper.png")), wx.BITMAP_TYPE_PNG))
        self.Bind(wx.EVT_CLOSE, self.OnClose)

        self.tc_width = 100
        self.parent = parent
        self.frame = parent  # help dialog looks for this name
        self.parent.button_save.Disable()
        self.parent.button_cancel.Disable()
        self.display_sys = parent.display_sys
        if dragged_positions:
            self.parent.export_offsets(self.display_sys)  # export dragged offsets first
        self.old_ppinorm_offs = self.display_sys.get_ppinorm_offsets()  # back up the offsets

        self.help_bmp = wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_BUTTON, wx.Size(20, 20))

        sizer_main = wx.BoxSizer(wx.VERTICAL)

        # Display position config
        self.create_position_config(len(self.display_sys.disp_list))

        # Bottom row buttons
        self.create_bottom_butts()

        self.set_unit_labels(self.cb_use_px.GetValue())

        sizer_main.Add(self.sizer_pos_conf, 0, wx.ALL | wx.EXPAND, 5)
        sizer_main.Add(self.sizer_buttons, 0, wx.ALL | wx.EXPAND, 5)
        self.SetSizer(sizer_main)
        self.Fit()
        self.populate_fields()
        self.Center()
        self.Show()

    def create_position_config(self, num_disps):
        """Create display position entry and data grid sizer."""
        cols = 7
        gap = 5
        self.sizer_pos_conf = wx.BoxSizer(wx.VERTICAL)
        self.grid = wx.FlexGridSizer(cols, gap, gap)

        # header
        hd_id = wx.StaticText(self, -1, "Display")
        self.hd_left = wx.StaticText(self, -1, "Left")
        self.hd_top = wx.StaticText(self, -1, "Top")
        self.hd_right = wx.StaticText(self, -1, "Right")
        self.hd_bott = wx.StaticText(self, -1, "Bottom")
        self.hd_left_new = wx.StaticText(self, -1, "Left new")
        self.hd_top_new = wx.StaticText(self, -1, "Top new")
        self.grid.Add(hd_id, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(self.hd_left, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(self.hd_top, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(self.hd_right, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(self.hd_bott, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(self.hd_left_new, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(self.hd_top_new, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)

        # Fill grid rows
        self.grid_rows = []
        for i in range(num_disps):
            row = self.display_opt_widget_row(i)
            self.grid_rows.append(row)
            sizer_row = [(item, 0, wx.ALL | wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL, 1) for item in row]
            self.grid.AddMany(sizer_row)
        self.sizer_pos_conf.Add(self.grid, 0, wx.EXPAND | wx.ALL, 0)

    def display_opt_widget_row(self, row_id):
        """Return a display position config widget row."""
        # statbox_disp_opts = self.sizer_disp_opts.GetStaticBox()
        statbox_disp_opts = self
        row_id = wx.StaticText(statbox_disp_opts, -1, str(row_id))
        row_left = wx.TextCtrl(
            statbox_disp_opts,
            -1,
            size=wx.Size(self.tc_width, -1),
            style=wx.TE_RIGHT | wx.TE_READONLY,
        )
        row_top = wx.TextCtrl(
            statbox_disp_opts,
            -1,
            size=wx.Size(self.tc_width, -1),
            style=wx.TE_RIGHT | wx.TE_READONLY,
        )
        row_right = wx.TextCtrl(
            statbox_disp_opts,
            -1,
            size=wx.Size(self.tc_width, -1),
            style=wx.TE_RIGHT | wx.TE_READONLY,
        )
        row_bottom = wx.TextCtrl(
            statbox_disp_opts,
            -1,
            size=wx.Size(self.tc_width, -1),
            style=wx.TE_RIGHT | wx.TE_READONLY,
        )
        row_left_new = wx.TextCtrl(
            statbox_disp_opts,
            -1,
            size=wx.Size(self.tc_width, -1),
            style=wx.TE_RIGHT | wx.TE_PROCESS_ENTER,
        )
        row_top_new = wx.TextCtrl(
            statbox_disp_opts,
            -1,
            size=wx.Size(self.tc_width, -1),
            style=wx.TE_RIGHT | wx.TE_PROCESS_ENTER,
        )

        row_left.Disable()
        row_top.Disable()
        row_right.Disable()
        row_bottom.Disable()

        row_left_new.Bind(wx.EVT_TEXT_ENTER, self.OnEnter)
        row_top_new.Bind(wx.EVT_TEXT_ENTER, self.OnEnter)

        row = [row_id, row_left, row_top, row_right, row_bottom, row_left_new, row_top_new]
        return row

    def set_unit_labels(self, use_px):
        """Show units in column labels."""
        if use_px:
            unit_str = "[px]"
        else:
            unit_str = "[mm]"
        self.hd_left.SetLabel("Left " + unit_str)
        self.hd_top.SetLabel("Top " + unit_str)
        self.hd_right.SetLabel("Right " + unit_str)
        self.hd_bott.SetLabel("Bottom " + unit_str)
        self.hd_left_new.SetLabel("Left new " + unit_str)
        self.hd_top_new.SetLabel("Top new " + unit_str)

    def create_bottom_butts(self):
        """Create sizer for bottom row buttons."""
        self.sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)

        self.cb_use_px = wx.CheckBox(self, -1, "Use pixels (exact)")
        self.cb_use_px.SetValue(False)
        self.cb_use_px.Bind(wx.EVT_CHECKBOX, self.onCbusepx)

        self.button_preview = wx.Button(self, label="Preview")
        self.button_apply = wx.Button(self, label="Apply")
        self.button_cancel = wx.Button(self, label="Cancel")

        self.button_preview.Bind(wx.EVT_BUTTON, self.onPreview)
        self.button_apply.Bind(wx.EVT_BUTTON, self.onApply)
        self.button_cancel.Bind(wx.EVT_BUTTON, self.onCancel)

        self.button_help_pos = wx.BitmapButton(self, bitmap=wx.BitmapBundle(self.help_bmp))
        self.button_help_pos.Bind(wx.EVT_BUTTON, self.onHelpExactPositions)

        self.sizer_buttons.Add(self.cb_use_px, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.sizer_buttons.AddStretchSpacer()
        self.sizer_buttons.Add(self.button_help_pos, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_buttons.Add(self.button_preview, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_buttons.Add(self.button_apply, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_buttons.Add(self.button_cancel, 0, wx.CENTER | wx.ALL, 5)

    def OnEnter(self, evt):
        """Bind pressing Enter in the txtctrl to update preview."""
        self.onPreview(evt)

    def OnClose(self, evt):
        """Make closing out behave as cancellation."""
        self.onCancel(evt)

    def onCbusepx(self, event):
        """Updates units of shown position data."""
        use_px = self.cb_use_px.GetValue()
        self.convert_units(use_px)
        self.set_unit_labels(use_px)

    def update_offsets_and_redraw(self):
        """Collect display postitions and redraw preview."""
        max_ppi = self.display_sys.max_ppi()
        if self.cb_use_px.GetValue():
            unit_mult = 1
        else:
            unit_mult = max_ppi / 25.4  # convert ppi to px/mm
        offs = []
        for row in self.grid_rows:
            new_off = []
            for tc in row[-2:]:
                tc_val = tc.GetValue()
                try:
                    new_off.append(float(tc_val) * unit_mult)
                except ValueError:
                    if tc_val:
                        msg = f"Entered value '{tc_val}' is not valid."
                    else:
                        msg = "Please enter a position for every display. Some value is empty."
                    show_message_dialog(msg)
                    return False
            offs.append(tuple(new_off))
        offs = self.sanitize_offs(offs)

        self.display_sys.update_ppinorm_offsets(offs)
        self.parent.display_data = self.display_sys.get_disp_list(True)
        self.parent.refresh_preview(use_ppi_px=True, force_refresh=True)
        self.parent.create_shapes()
        self.parent.frame.Refresh()

        self.populate_fields()
        return True

    def onPreview(self, event):
        """Updates the display preview based on the entered position values."""
        self.update_offsets_and_redraw()

    def onApply(self, event):
        """Apply display positions and close dialog."""
        res = self.update_offsets_and_redraw()
        if res:
            self.parent.button_save.Enable()
            self.parent.button_cancel.Enable()
            self.parent.positions_dragged = False
            self.Destroy()

    def onCancel(self, event):
        """Closes display position config, throwing away unsaved contents."""
        # Restore old offsets
        self.display_sys.update_ppinorm_offsets(self.old_ppinorm_offs)
        # redraw preview with restored data
        self.parent.display_data = self.display_sys.get_disp_list(True)
        self.parent.refresh_preview(use_ppi_px=True, force_refresh=True)
        self.parent.create_shapes()
        self.parent.frame.Refresh()
        # close dialog
        self.parent.button_save.Enable()
        self.parent.button_cancel.Enable()
        self.Destroy()

    def onHelpExactPositions(self, evt):
        """Popup exact position entry main help."""
        text = (
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
        pop = HelpPopup(
            self,
            text,
            show_image_quality=False,
        )
        btn = evt.GetEventObject()
        pos = btn.ClientToScreen((0, 0))
        sz = btn.GetSize()
        pop.Position(pos, wx.Size(0, sz[1]))
        pop.Popup()

    def populate_fields(self):
        """Populate config fields from DisplaySystem offsets."""
        max_ppi = self.display_sys.max_ppi()
        if self.cb_use_px.GetValue():
            unit_mult = 1
        else:
            unit_mult = 1 / (max_ppi / 25.4)  # convert ppi to px/mm
        crops = self.display_sys.get_ppi_norm_crops(len(self.display_sys.disp_list) * [(0, 0)])
        bezels = self.display_sys.bezels_in_px()
        for row, ltrb, bez in zip(self.grid_rows, crops, bezels):
            row[0].SetLabel(str(self.grid_rows.index(row)))
            row[1].SetValue(str(ltrb[0] * unit_mult))
            row[2].SetValue(str(ltrb[1] * unit_mult))
            row[3].SetValue(str((ltrb[2] + bez[0]) * unit_mult))
            row[4].SetValue(str((ltrb[3] + bez[1]) * unit_mult))
            row[5].SetValue(str(ltrb[0] * unit_mult))
            row[6].SetValue(str(ltrb[1] * unit_mult))

    def convert_units(self, use_px):
        """Convert table data between px and mm in place."""
        max_ppi = self.display_sys.max_ppi()
        if use_px:
            # convert from mm to px
            unit_mult = max_ppi / 25.4
        else:
            # convert from px to mm
            unit_mult = 1 / (max_ppi / 25.4)
        for row in self.grid_rows:
            for tc in row[1:]:
                curval = tc.GetValue()
                if curval:
                    tc.SetValue(str(unit_mult * float(curval)))

    def sanitize_offs(self, offsets):
        """Return offsets translated to be non-negative, anchoring to (0,0)."""
        sanitized_offs = []
        leftmost_offset = min([off[0] for off in offsets])
        topmost_offset = min([off[1] for off in offsets])
        for off in offsets:
            sanitized_offs.append((off[0] - leftmost_offset, off[1] - topmost_offset))
        return sanitized_offs
