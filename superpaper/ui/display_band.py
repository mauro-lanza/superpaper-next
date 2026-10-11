"""The editor's display settings band: the displays' diagonal sizes and bezels, which apply
to every profile, with their own Save and Revert."""

import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

from superpaper.ui.help import HelpPopup


class DisplayBand(wx.CollapsiblePane):
    """The collapsible band above the profile row: the display-wide settings (diagonal
    sizes, bezels) that every profile shares, with a dedicated Save and Revert.

    Edits apply at once to the editor's staged layout ``display_sys``, so the preview can
    be used to dial in values, but they are only written to disk when Save is pressed;
    Revert restores the last saved state. Collapsed by default: set it once and forget it.

    ``preview`` shows the layout and is where bezels are set. The editor provides the
    rest: ``relayout()`` lays the editor out again, ``refresh_preview()`` shows the staged
    layout in the preview, ``enable_profile_editing(enable)`` locks the profile settings
    while bezels are being set, and ``on_saved()`` is called once the layout is saved.
    """

    def __init__(
        self,
        parent,
        display_sys,
        preview,
        *,
        field_width,
        relayout,
        refresh_preview,
        enable_profile_editing,
        on_saved,
    ):
        super().__init__(
            parent,
            label="Display system settings  (apply to all profiles)",
            style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE,
        )
        self.display_sys = display_sys
        self._preview = preview
        self._relayout = relayout
        self._refresh_preview = refresh_preview
        self._enable_profile_editing = enable_profile_editing
        self._on_saved = on_saved
        # The settings as last saved or loaded: Save and Revert are enabled only while
        # the staged layout differs from them.
        self._clean = None
        self._reverting = False
        self.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self.onToggle)
        pane = self.GetPane()

        band = wx.BoxSizer(wx.HORIZONTAL)

        # Diagonal sizes group
        self.sizer_setting_diaginch = wx.BoxSizer(wx.VERTICAL)
        self._build_diaginch_controls(pane, field_width)
        band.Add(self.sizer_setting_diaginch, 0, wx.ALL, 8)

        band.Add(wx.StaticLine(pane, style=wx.LI_VERTICAL), 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)

        # Bezels group
        self.sizer_setting_bezels = wx.BoxSizer(wx.VERTICAL)
        self._build_bezel_controls(pane)
        band.Add(self.sizer_setting_bezels, 0, wx.ALL, 8)

        band.AddStretchSpacer()

        # System Save / Revert
        sys_btns = wx.BoxSizer(wx.VERTICAL)
        self.button_system_save = wx.Button(pane, label="Save")
        self.button_system_revert = wx.Button(pane, label="Revert")
        self.button_system_save.Bind(wx.EVT_BUTTON, self.onSave)
        self.button_system_revert.Bind(wx.EVT_BUTTON, self.onRevert)
        self.button_system_save.SetToolTip(wx.ToolTip("Save these display settings for all profiles."))
        self.button_system_revert.SetToolTip(wx.ToolTip("Discard unsaved display setting changes."))
        self.button_system_save.Disable()
        self.button_system_revert.Disable()
        sys_btns.Add(self.button_system_save, 0, wx.ALL, 3)
        sys_btns.Add(self.button_system_revert, 0, wx.ALL, 3)
        band.Add(sys_btns, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 8)

        pane.SetSizer(band)
        self.Collapse(True)

    def _build_diaginch_controls(self, parent, field_width):
        """Build the manual display diagonal size controls."""
        self.cb_diaginch = wx.CheckBox(parent, -1, "Input display sizes manually")
        self.cb_diaginch.Bind(wx.EVT_CHECKBOX, self.onCheckboxDiaginch)
        self.st_diaginch = wx.StaticText(parent, -1, "Display diagonal sizes (inches):")
        self.sizer_setting_diaginch.Add(self.cb_diaginch, 0, wx.ALIGN_LEFT | wx.BOTTOM, 5)
        self.sizer_setting_diaginch.Add(self.st_diaginch, 0, wx.ALIGN_LEFT | wx.LEFT, 10)
        diags = [str(dsp.diagonal_size()[1]) for dsp in self.display_sys.disp_list]
        tc_list_sizer_diag = wx.WrapSizer(wx.HORIZONTAL)
        self.tc_list_diaginch = [
            wx.TextCtrl(parent, -1, size=wx.Size(field_width, -1), style=wx.TE_RIGHT)
            for _ in self.display_sys.disp_list
        ]
        use_user_diags = self.display_sys.use_user_diags
        for tc, diag in zip(self.tc_list_diaginch, diags):
            tc_list_sizer_diag.Add(tc, 0, wx.ALIGN_LEFT | wx.ALL, 5)
            tc.ChangeValue(diag)
            tc.Enable(use_user_diags)
            # Dedicated handler consumes the event so display-size edits don't
            # reach the profile field handler (these are system-wide settings).
            tc.Bind(wx.EVT_TEXT, self._on_diagonal_changed)
        self.sizer_setting_diaginch.Add(tc_list_sizer_diag, 0, wx.ALIGN_LEFT | wx.LEFT, 5)
        self.cb_diaginch.SetValue(use_user_diags)

    def _build_bezel_controls(self, parent):
        """Build the bezel configuration controls."""
        st_bezels = wx.StaticText(parent, -1, "Adjust bezel sizes:")
        self.sizer_bezel_buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.button_bezels = wx.Button(parent, -1, label="Configure")
        self.button_bezels_save = wx.Button(parent, -1, label="Done")
        self.button_bezels_canc = wx.Button(parent, -1, label="Cancel")
        self.button_bezels.Bind(wx.EVT_BUTTON, self.onConfigureBezels)
        self.button_bezels_save.Bind(wx.EVT_BUTTON, self.onConfigureBezelsSave)
        self.button_bezels_canc.Bind(wx.EVT_BUTTON, self.onConfigureBezelsCanc)
        help_bmp = wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_BUTTON, wx.Size(20, 20))
        self.button_help_bezel = wx.BitmapButton(parent, bitmap=wx.BitmapBundle(help_bmp), name="butt_help_bez")
        self.button_help_bezel.Bind(wx.EVT_BUTTON, self.onHelpBezels)
        self.sizer_bezel_buttons.Add(self.button_bezels, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.sizer_bezel_buttons.Add(self.button_bezels_save, 0, wx.ALIGN_CENTER_VERTICAL | wx.TOP | wx.BOTTOM, 5)
        self.sizer_bezel_buttons.Add(self.button_bezels_canc, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.sizer_bezel_buttons.Add(self.button_help_bezel, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.sizer_setting_bezels.Add(st_bezels, 0, wx.ALL, 0)
        self.sizer_setting_bezels.Add(self.sizer_bezel_buttons, 1, wx.EXPAND, 0)
        self.button_bezels_save.Disable()
        self.button_bezels_canc.Disable()

    def onToggle(self, event):
        """Re-layout the editor when the band is expanded or collapsed."""
        self._relayout()

    #
    # Change tracking
    #
    def _snapshot(self):
        """Capture the display-wide settings as a comparable structure."""
        ds = self.display_sys
        return {
            "bezels": tuple((round(b[0], 2), round(b[1], 2)) for b in ds.bezels_in_mm()),
            "offsets": tuple((round(o[0]), round(o[1])) for o in ds.get_ppinorm_offsets()),
            "use_user_diags": ds.use_user_diags,
            "diags": tuple(round(dsp.diagonal_size()[1], 2) for dsp in ds.disp_list),
        }

    def _restore(self, snap):
        """Restore the staged layout to a previously captured snapshot."""
        ds = self.display_sys
        ds.update_bezels([tuple(b) for b in snap["bezels"]])
        if snap["use_user_diags"]:
            ds.update_display_diags(list(snap["diags"]), reset_offsets=False)
        else:
            ds.update_display_diags("auto")
        # Positions are restored last; the diag/bezel updates above recompute
        # initial offsets, so the saved offsets must be written afterwards.
        ds.update_ppinorm_offsets([tuple(o) for o in snap["offsets"]])
        self._refresh_preview()

    def _show_diagonals(self):
        """Sync the diagonal-size text fields and checkbox to the staged layout."""
        self.cb_diaginch.SetValue(self.display_sys.use_user_diags)
        diags = [str(dsp.diagonal_size()[1]) for dsp in self.display_sys.disp_list]
        for tc, diag in zip(self.tc_list_diaginch, diags):
            tc.ChangeValue(diag)
            tc.Enable(self.display_sys.use_user_diags)

    def set_baseline(self):
        """Record the current display-wide settings as the saved, clean baseline."""
        self._clean = self._snapshot()
        self.button_system_save.Enable(False)
        self.button_system_revert.Enable(False)

    def update_dirty(self):
        """Enable Save and Revert while there are unsaved changes, and only then."""
        if self._reverting or self._clean is None:
            return
        dirty = self._snapshot() != self._clean
        if dirty != self.button_system_save.IsEnabled():
            self.button_system_save.Enable(dirty)
            self.button_system_revert.Enable(dirty)

    def _on_diagonal_changed(self, event):
        """Live-apply valid diagonal-size edits and refresh the dirty state.

        Consumes the event so it does not also reach the profile-level field
        handler (display sizes are system-wide, not part of a profile).
        """
        if not self._reverting and self.cb_diaginch.GetValue():
            inches = []
            for tc in self.tc_list_diaginch:
                val = _diagonal(tc.GetValue())
                if not val:
                    # Mid-edit / invalid entry: don't apply, wait for valid input.
                    inches = None
                    break
                inches.append(val)
            if inches:
                self.display_sys.update_display_diags(inches, reset_offsets=False)
                self._refresh_preview()
        self.update_dirty()

    def onSave(self, event):
        """Write the staged display-wide settings to disk."""
        self.display_sys.save_system()
        self._on_saved()
        self.set_baseline()

    def onRevert(self, event):
        """Discard unsaved display-wide changes, restoring the baseline."""
        if self._clean is None:
            return
        self._reverting = True
        self._restore(self._clean)
        self._show_diagonals()
        self._reverting = False
        self.update_dirty()

    #
    # Diagonal sizes
    #
    def onCheckboxDiaginch(self, event):
        """Toggle manual display sizes. Changes are staged, not saved to disk.

        Checking enables the inch fields and applies their current values to the
        preview; unchecking returns to auto-detected sizes. Either way the change
        is only persisted when the band's Save is pressed.
        """
        cb_state = self.cb_diaginch.GetValue()
        for tc in self.tc_list_diaginch:
            tc.Enable(cb_state)
        if cb_state:
            # Apply the current field values (if valid) so the preview updates.
            self._on_diagonal_changed(None)
        else:
            # Back to auto-detected sizes (staged only).
            self.display_sys.update_display_diags("auto")
            self._show_diagonals()
            self._refresh_preview()
            self.update_dirty()

    def enable_diagonals(self, enable):
        """Enable the diagonal-size controls, or disable them while display positions or
        bezels are being set; the inch fields and their label only while sizes are
        entered by hand."""
        entered = enable and self.cb_diaginch.GetValue()
        self.cb_diaginch.Enable(enable)
        self.st_diaginch.Enable(entered)
        for tc in self.tc_list_diaginch:
            tc.Enable(entered)

    #
    # Bezels
    #
    def toggle_bezel_buttons(self, bezel_mode=False, enable_config_butt=True):
        """Enable the bezel buttons for the mode: Done and Cancel while bezels are being
        set, and Configure otherwise, if ``enable_config_butt``. Help is always enabled."""
        self.button_bezels.Enable(enable_config_butt)
        self.button_bezels_save.Enable(bezel_mode)
        self.button_bezels_canc.Enable(bezel_mode)
        self.button_help_bezel.Enable(True)

    def onConfigureBezels(self, event):
        """Start bezel size config mode."""
        self._enable_profile_editing(False)
        self._preview.start_bezel_config()
        self.button_bezels.Disable()
        self.button_bezels_save.Enable()
        self.button_bezels_canc.Enable()

    def onConfigureBezelsSave(self, event):
        """Exit bezel config mode, staging the new bezel sizes (not saved yet)."""
        self._enable_profile_editing(True)
        self._preview.bezel_config_save()
        self.button_bezels_save.Disable()
        self.button_bezels_canc.Disable()
        self.button_bezels.Enable()
        self.update_dirty()

    def onConfigureBezelsCanc(self, event):
        """Cancel out of bezel size config mode."""
        self._enable_profile_editing(True)
        self._preview.bezel_config_cancel()
        self.button_bezels_save.Disable()
        self.button_bezels_canc.Disable()
        self.button_bezels.Enable()

    def onHelpBezels(self, evt):
        """Popup bezel config help."""
        text = (
            "Configure your bezels in the wallpaper preview\n"
            "panel with the buttons placed at the right and\n"
            "bottom edges of displays. Bezels between displays\n"
            "are meaningful. Adjacent bezel pair thicknesses are\n"
            "grouped together with the gap in between to a single\n"
            "number."
        )
        pop = HelpPopup(self.GetParent(), text)
        btn = evt.GetEventObject()
        pos = btn.ClientToScreen((0, 0))
        sz = btn.GetSize()
        pop.Position(pos, wx.Size(0, sz[1]))
        pop.Popup()


def _diagonal(inch_str):
    """The diagonal size entered as ``inch_str``, in inches; False unless it is a positive
    number."""
    try:
        num = float(inch_str)
        if num > 0:
            return num
        else:
            return False
    except ValueError:
        return False
