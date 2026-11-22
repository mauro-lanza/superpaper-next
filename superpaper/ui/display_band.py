"""The editor's display settings band: the displays' diagonal sizes and bezels, which apply
to every profile, with their own Save and Revert."""

from dataclasses import dataclass

import wx  # ty:ignore[unresolved-import]

from superpaper.geometry import layout_edit
from superpaper.geometry.displays import Layout
from superpaper.ui.help import show_help_popup
from superpaper.ui.message import show_message_dialog

INVALID_COLOUR = wx.Colour(255, 200, 200)
LABEL = "Display system settings  (apply to all profiles)"
UNSAVED_MARKER = "Displays: unsaved"
INVALID_DIAGONALS_MESSAGE = "Every display size must be a number from 1 to 1000 inches."


@dataclass(frozen=True, slots=True)
class _Typing:
    """The layout before diagonals were typed, and the one the typing staged from it."""

    base: Layout
    result: Layout


class DisplayBand(wx.CollapsiblePane):
    """The collapsible band above the profile row: the display-wide settings (diagonal
    sizes, bezels) that every profile shares, with a dedicated Save and Revert.

    Edits apply at once to the editor's ``staged`` layout, so the preview can
    be used to dial in values, but they are only written to disk when Save is pressed;
    Revert restores the last saved state. Collapsed by default: set it once and forget it.

    ``layout_editor`` sets the bezels in the preview. The editor provides the
    rest: ``relayout()`` lays the editor out again, ``refresh_preview()`` shows the staged
    layout in the preview, ``enable_profile_editing(enable)`` locks the profile settings
    while bezels are being set, ``save_layout(layout)`` writes a layout to disk and returns
    a SaveFailed or None, and
    ``on_saved()`` is called once the layout is saved.
    """

    def __init__(
        self,
        parent,
        staged,
        layout_editor,
        *,
        field_width,
        relayout,
        refresh_preview,
        enable_profile_editing,
        save_layout,
        on_saved,
    ):
        super().__init__(
            parent,
            label=LABEL,
            style=wx.CP_DEFAULT_STYLE | wx.CP_NO_TLW_RESIZE,
        )
        self.staged = staged
        self._layout_editor = layout_editor
        self._relayout = relayout
        self._refresh_preview = refresh_preview
        self._enable_profile_editing = enable_profile_editing
        self._save_layout = save_layout
        self._on_saved = on_saved
        # The settings as last saved or loaded: Save and Revert are enabled only while
        # the staged layout differs from them.
        self._clean = None
        # The field texts typed before manual sizes were unchecked, for checking them again;
        # forgotten whenever the settings are saved or reverted.
        self._typed_diagonals = None
        self._typing = None
        self._reverting = False
        self._unsaved_marker_shown = False
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
        layout = self.staged.layout
        tc_list_sizer_diag = wx.WrapSizer(wx.HORIZONTAL)
        self.tc_list_diaginch = [
            wx.TextCtrl(parent, -1, size=wx.Size(field_width, -1), style=wx.TE_RIGHT) for _ in layout.displays
        ]
        for tc in self.tc_list_diaginch:
            tc_list_sizer_diag.Add(tc, 0, wx.ALIGN_LEFT | wx.ALL, 5)
            # Dedicated handler consumes the event so display-size edits don't
            # reach the profile field handler (these are system-wide settings).
            tc.Bind(wx.EVT_TEXT, self._on_diagonal_changed)
        self.sizer_setting_diaginch.Add(tc_list_sizer_diag, 0, wx.ALIGN_LEFT | wx.LEFT, 5)
        self._show_diagonals()

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
    def _restore(self, settings):
        """Restore the staged layout to previously captured settings."""
        self.staged.layout = self.staged.layout.with_settings(settings)
        self._refresh_preview()

    def _show_diagonals(self):
        """Sync the diagonal-size text fields and checkbox to the staged layout."""
        layout = self.staged.layout
        self.cb_diaginch.SetValue(layout.uses_user_diagonals)
        diags = [str(diagonal) for diagonal in layout.diagonal_inches()]
        for tc, diag in zip(self.tc_list_diaginch, diags, strict=True):
            tc.ChangeValue(diag)
            tc.Enable(layout.uses_user_diagonals)
        self._mark_invalid_diagonals()

    def set_baseline(self):
        """Record the current display-wide settings as the saved, clean baseline."""
        self._clean = self.staged.layout.settings()
        self._typed_diagonals = None
        self._typing = None
        self.button_system_save.Enable(False)
        self.button_system_revert.Enable(False)
        self._show_unsaved_marker(False)

    def update_dirty(self):
        """Enable Save while there are unsaved changes and every diagonal is valid, and
        Revert while there are unsaved changes or an invalid diagonal."""
        if self._reverting or self._clean is None:
            return
        dirty = self.staged.layout.settings() != self._clean
        invalid = self._has_invalid_diagonals()
        self.button_system_save.Enable(dirty and not invalid)
        self.button_system_revert.Enable(dirty or invalid)
        self._show_unsaved_marker(dirty or invalid)

    def has_unsaved_changes(self):
        """Whether the staged settings differ from the saved ones, or a diagonal is typed
        that can't be staged."""
        if self._clean is None:
            return False
        return self.staged.layout.settings() != self._clean or self._has_invalid_diagonals()

    def can_save(self):
        """Whether the staged settings can be saved: no diagonal is typed that can't be staged."""
        return not self._has_invalid_diagonals()

    def _show_unsaved_marker(self, unsaved):
        self._unsaved_marker_shown = unsaved
        self.SetLabel(f"{LABEL}  -  {UNSAVED_MARKER}" if unsaved else LABEL)

    def shows_unsaved_marker(self):
        """Whether the header carries the unsaved marker. Kept here because wxGTK's
        CollapsiblePane::SetLabel only updates the GtkExpander, so GetLabel reads back empty."""
        return self._unsaved_marker_shown

    def _has_invalid_diagonals(self):
        return self.cb_diaginch.GetValue() and any(
            layout_edit.parse_diagonal(tc.GetValue()) is None for tc in self.tc_list_diaginch
        )

    def _mark_invalid_diagonals(self):
        """Colour the diagonal fields whose text isn't a valid size."""
        for tc in self.tc_list_diaginch:
            valid = not tc.IsEnabled() or layout_edit.parse_diagonal(tc.GetValue()) is not None
            tc.SetBackgroundColour(wx.NullColour if valid else INVALID_COLOUR)
            tc.Refresh()

    def _on_diagonal_changed(self, event):
        """Live-apply valid diagonal-size edits and refresh the dirty state.

        Consumes the event so it does not also reach the profile-level field
        handler (display sizes are system-wide, not part of a profile). An invalid
        entry marks its field and leaves the staged layout as it is.
        """
        if not self._reverting and self.cb_diaginch.GetValue():
            self._mark_invalid_diagonals()
            inches = layout_edit.parse_diagonals([tc.GetValue() for tc in self.tc_list_diaginch])
            if inches is not None:
                self._stage_diagonals(inches)
        self.update_dirty()

    def _stage_diagonals(self, inches):
        """Stage ``inches``, shifting only the overlapping displays. Positions are fitted
        from those before the typing began, so passing through a value such as the "1" of
        "15.6" leaves no gap behind."""
        current = self.staged.layout
        if self._typing is None or current.settings() != self._typing.result.settings():
            base = current
        else:
            base = self._typing.base
        resized = layout_edit.fit_resized(base.with_diagonals(inches))
        self._typing = _Typing(base, resized.layout)
        self.staged.layout = resized.layout
        self._refresh_preview()
        if resized.rearranged_all:
            show_message_dialog(layout_edit.REARRANGED_MESSAGE, "Info")

    def onSave(self, event):
        self.save()

    def save(self):
        """Write the staged display-wide settings to disk; tells the user and returns False
        if a diagonal is invalid or the write fails."""
        if self._has_invalid_diagonals():
            show_message_dialog(INVALID_DIAGONALS_MESSAGE, "Error")
            return False
        failed = self._save_layout(self.staged.layout)
        if failed is not None:
            show_message_dialog(failed.message, "Error")
            return False
        self._on_saved()
        self.set_baseline()
        return True

    def onRevert(self, event):
        """Discard unsaved display-wide changes, restoring the baseline."""
        if self._clean is None:
            return
        self._reverting = True
        self._restore(self._clean)
        self._typed_diagonals = None
        self._typing = None
        self._show_diagonals()
        self._reverting = False
        self.update_dirty()

    #
    # Diagonal sizes
    #
    def onCheckboxDiaginch(self, event):
        """Toggle manual display sizes. Changes are staged, not saved to disk.

        Unchecking shows the auto-detected sizes and remembers the typed ones; checking
        brings them back. Only displays that overlap afterwards are moved. Either way the
        change is only persisted when the band's Save is pressed.
        """
        cb_state = self.cb_diaginch.GetValue()
        for tc in self.tc_list_diaginch:
            tc.Enable(cb_state)
        before = self.staged.layout
        if cb_state:
            if self._typed_diagonals is not None:
                for tc, text in zip(self.tc_list_diaginch, self._typed_diagonals, strict=True):
                    tc.ChangeValue(text)
            resized = layout_edit.with_entered_diagonals(before, [tc.GetValue() for tc in self.tc_list_diaginch])
            if resized is None:
                self._mark_invalid_diagonals()
                self.update_dirty()
                return
        else:
            self._typed_diagonals = [tc.GetValue() for tc in self.tc_list_diaginch]
            resized = layout_edit.fit_resized(before.with_detected_sizes())
        self.staged.layout = resized.layout
        self._typing = None
        self._show_diagonals()
        self._refresh_preview()
        if resized.rearranged_all:
            show_message_dialog(layout_edit.REARRANGED_MESSAGE, "Info")
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
        self._layout_editor.start_bezel_config()
        self.toggle_bezel_buttons(bezel_mode=True, enable_config_butt=False)

    def onConfigureBezelsSave(self, event):
        """Exit bezel config mode, staging the new bezel sizes (not saved yet)."""
        self._enable_profile_editing(True)
        self._layout_editor.bezel_config_save()
        self.toggle_bezel_buttons()
        self.update_dirty()

    def onConfigureBezelsCanc(self, event):
        """Cancel out of bezel size config mode."""
        self._enable_profile_editing(True)
        self._layout_editor.bezel_config_cancel()
        self.toggle_bezel_buttons()

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
        show_help_popup(self.GetParent(), text, evt.GetEventObject())
