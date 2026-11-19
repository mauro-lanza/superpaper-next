"""Entering display positions exactly, in millimetres or pixels."""

from collections.abc import Callable

import wx  # ty:ignore[unresolved-import]

from superpaper.geometry import positions
from superpaper.paths import resource
from superpaper.ui.help import show_help_popup
from superpaper.ui.message import show_message_dialog


class DisplayPositionEntry(wx.Frame):
    """Display position fine control dialog."""

    def __init__(
        self,
        preview,
        *,
        set_save_cancel_enabled: Callable[[bool], None],
        create_shapes: Callable[[], None],
        on_applied: Callable[[], None],
    ):
        wx.Frame.__init__(self, preview.GetParent(), -1, "Enter display positions")
        self.ToggleWindowStyle(wx.STAY_ON_TOP)
        self.SetIcon(wx.Icon(str(resource("superpaper.png")), wx.BITMAP_TYPE_PNG))
        self.Bind(wx.EVT_CLOSE, self.onCancel)

        self.tc_width = 100
        self.preview = preview
        self._set_save_cancel_enabled = set_save_cancel_enabled
        self._create_shapes = create_shapes
        self._on_applied = on_applied
        self._set_save_cancel_enabled(False)
        self.staged = preview.staged
        self.offsets_on_open = self.staged.layout.ppi_norm_offsets

        self.help_bmp = wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_BUTTON, wx.Size(20, 20))

        sizer_main = wx.BoxSizer(wx.VERTICAL)

        # Display position config
        self.create_position_config(len(self.staged.layout.displays))

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
        row_id = wx.StaticText(self, -1, str(row_id))
        row_edges = [
            wx.TextCtrl(self, -1, size=wx.Size(self.tc_width, -1), style=wx.TE_RIGHT | wx.TE_READONLY) for _ in range(4)
        ]
        row_new = [
            wx.TextCtrl(self, -1, size=wx.Size(self.tc_width, -1), style=wx.TE_RIGHT | wx.TE_PROCESS_ENTER)
            for _ in range(2)
        ]
        for tc in row_edges:
            tc.Disable()
        for tc in row_new:
            tc.Bind(wx.EVT_TEXT_ENTER, self.onPreview)

        return [row_id, *row_edges, *row_new]

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

    def onCbusepx(self, event):
        """Updates units of shown position data."""
        use_px = self.cb_use_px.GetValue()
        try:
            self.convert_units(use_px)
        except ValueError as error:
            show_message_dialog(f"The positions could not be converted: {error}", "Error")
            self.cb_use_px.SetValue(not use_px)
            return
        self.set_unit_labels(use_px)

    def update_offsets_and_redraw(self):
        """Collect display postitions and redraw preview."""
        fields = [(row[-2].GetValue(), row[-1].GetValue()) for row in self.grid_rows]
        try:
            offs = positions.parse_new_offsets(fields, self.staged.layout.max_ppi(), use_px=self.cb_use_px.GetValue())
        except ValueError as error:
            show_message_dialog(str(error))
            return False

        self.staged.layout = self.staged.layout.with_offsets(offs)
        self._redraw()

        self.populate_fields()
        return True

    def _redraw(self):
        """Redraw the preview and shapes from the staged layout."""
        self.preview.display_data = self.staged.layout.ppi_norm_areas()
        self.preview.refresh_preview(use_ppi_px=True)
        self._create_shapes()
        self.preview.GetParent().Refresh()

    def onPreview(self, event):
        """Updates the display preview based on the entered position values."""
        self.update_offsets_and_redraw()

    def onApply(self, event):
        """Apply display positions and close dialog."""
        res = self.update_offsets_and_redraw()
        if res:
            self._set_save_cancel_enabled(True)
            self._on_applied()
            self.Destroy()

    def onCancel(self, event):
        """Closes display position config, throwing away unsaved contents."""
        # Restore old offsets
        self.staged.layout = self.staged.layout.with_offsets(self.offsets_on_open)
        self._redraw()
        # close dialog
        self._set_save_cancel_enabled(True)
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
        show_help_popup(self, text, evt.GetEventObject())

    def populate_fields(self):
        """Populate config fields from the staged layout's offsets."""
        layout = self.staged.layout
        edges = positions.edges_in_unit(layout, use_px=self.cb_use_px.GetValue())
        for index, (row, (left, top, right, bottom)) in enumerate(zip(self.grid_rows, edges, strict=True)):
            row[0].SetLabel(str(index))
            row[1].SetValue(str(left))
            row[2].SetValue(str(top))
            row[3].SetValue(str(right))
            row[4].SetValue(str(bottom))
            row[5].SetValue(str(left))
            row[6].SetValue(str(top))

    def convert_units(self, use_px):
        """Convert table data between px and mm in place; raises ValueError, changing nothing,
        if a field is not a number."""
        max_ppi = self.staged.layout.max_ppi()
        converted = [
            (tc, positions.convert_unit(tc.GetValue(), max_ppi, to_px=use_px))
            for row in self.grid_rows
            for tc in row[1:]
        ]
        for tc, text in converted:
            tc.SetValue(text)
