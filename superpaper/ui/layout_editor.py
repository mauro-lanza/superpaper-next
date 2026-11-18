"""Layout editing on the preview: dragging displays into position and setting bezels."""

import logging

import wx  # ty:ignore[unresolved-import]

from superpaper.geometry import canvas
from superpaper.paths import resource
from superpaper.ui.message import show_message_dialog
from superpaper.ui.positions_dialog import DisplayPositionEntry
from superpaper.user_input import parse_float

logger = logging.getLogger(__name__)


class LayoutEditor:
    """The display positioning and bezel tools of a WallpaperPreviewPanel.

    The editor around the preview is reached only through the callbacks:
    ``set_profile_controls_enabled(enable)`` locks the profile controls while editing,
    ``toggle_bezel_buttons(bezel_mode, enable_config_butt)`` sets the band's bezel buttons,
    ``mark_dirty()`` has the band re-check for unsaved changes, and
    ``show_help(text, button)`` pops the preview's help up at the button.
    """

    def __init__(self, preview, *, set_profile_controls_enabled, toggle_bezel_buttons, mark_dirty, show_help):
        self.preview = preview
        self._set_profile_controls_enabled = set_profile_controls_enabled
        self._toggle_bezel_buttons = toggle_bezel_buttons
        self._mark_dirty = mark_dirty
        self._show_help = show_help
        self.config_mode = False
        self.bezel_conifg_mode = False
        self.bez_buttons = []
        self.draggable_shapes = []
        self.positions_dragged = False

    #
    # Buttons
    #
    def create_buttons(self, use_ppi_px):
        """Create buttons for display preview positioning config."""
        # Buttons - show only if use_ppi_px == True
        self.button_config = wx.Button(self.preview, label="Positions")
        self.button_save = wx.Button(self.preview, label="Save")
        self.button_reset = wx.Button(self.preview, label="Reset")
        self.button_cancel = wx.Button(self.preview, label="Cancel")
        self.button_entry = wx.Button(self.preview, label="Exact entry")
        help_bmp = wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_BUTTON, wx.Size(20, 20))
        self.button_help = wx.BitmapButton(self.preview, bitmap=wx.BitmapBundle(help_bmp), name="butt_help")

        self.button_config.Bind(wx.EVT_BUTTON, self.onConfigure)
        self.button_save.Bind(wx.EVT_BUTTON, self.onSave)
        self.button_reset.Bind(wx.EVT_BUTTON, self.onReset)
        self.button_cancel.Bind(wx.EVT_BUTTON, self.onCancel)
        self.button_entry.Bind(wx.EVT_BUTTON, self.onEntry)
        self.button_help.Bind(wx.EVT_BUTTON, self.onHelp)

        self.move_buttons()

        self.button_config.Show(use_ppi_px)
        self.button_save.Show(False)
        self.button_reset.Show(False)
        self.button_entry.Show(False)
        self.button_cancel.Show(False)

    def move_buttons(self):
        """Position display config buttons in the bottom-right corner.

        Each button is right-aligned using its own width so wider labels such as
        "Positions" and "Exact entry" stay fully inside the panel. Using
        ``GetDefaultSize`` here clipped them, as it returns wx's generic button
        width and ignores the actual label.
        """
        sz_area = self.preview.GetSize()
        self.butt_gap = 10
        gap = self.butt_gap
        row_h = self.button_config.GetBestSize()[1]
        right = sz_area[0] - gap
        bottom_y = sz_area[1] - row_h - gap

        def right_aligned(button, row):
            button.SetPosition(wx.Point(right - button.GetBestSize()[0], bottom_y - row * (row_h + gap)))

        # Right column, bottom to top. Config/Cancel share the bottom row (only
        # one is ever shown at a time depending on config mode).
        right_aligned(self.button_config, 0)
        right_aligned(self.button_cancel, 0)
        right_aligned(self.button_reset, 1)
        right_aligned(self.button_entry, 2)
        # Save sits to the left of the bottom-right Cancel button.
        self.button_save.SetPosition(
            wx.Point(
                right - self.button_cancel.GetBestSize()[0] - gap - self.button_save.GetBestSize()[0],
                bottom_y,
            )
        )
        self.button_help.SetPosition(wx.Point(right - self.button_help.GetBestSize()[0], gap))

    def toggle_buttons(self, show_config, in_config):
        """Toggle visibility of display positioning config buttons."""
        self.button_config.Show(show_config)
        self.button_save.Show(in_config)
        self.button_reset.Show(in_config)
        self.button_entry.Show(in_config)
        self.button_cancel.Show(in_config)

    def onConfigure(self, evt):
        """Start diplay position config mode."""
        self.old_ppinorm_offs = self.preview.staged.layout.ppi_norm_offsets  # back up the offsets
        self._set_profile_controls_enabled(False)
        self._toggle_bezel_buttons(False, False)
        self.config_mode = True
        self.toggle_buttons(False, True)
        self.show_staticbmps(False)
        self.create_shapes()
        self.preview.Refresh()

    def onSave(self, evt):
        """Stage current Display offsets into the staged layout.

        The new positions are kept in memory (and shown in the preview) but are
        only written to disk when the system band's Save is pressed.
        """
        self.config_mode = False
        self.bind_movement_binds(False)
        self.toggle_buttons(True, False)
        staged = self.preview.staged
        if self.positions_dragged:  # only export drag positions if actually dragged
            staged.layout = self.dragged_layout(staged.layout)
        display_data = staged.layout.ppi_norm_areas()
        # Full redraw of preview with new offset data
        if self.preview.current_preview_images:
            self.preview.preview_wallpaper(self.preview.current_preview_images, "advanced", display_data=display_data)
        else:
            self.preview.display_data = display_data
            self.preview.refresh_preview(True)
            self.preview.resize_displays(True)
        self.draggable_shapes = []  # Destroys DragShapes
        self.positions_dragged = False
        self._set_profile_controls_enabled(True)
        self._toggle_bezel_buttons(False, True)
        self.preview.Refresh()
        self._mark_dirty()

    def onReset(self, evt):
        """Reset Display preview positions to the initial guess."""
        display_data = self.preview.staged.layout.with_initial_offsets().ppi_norm_areas()
        dtop_canvas_px = canvas.desktop_extent_with_bezels(display_data)
        _, dtop_canvas_pos, scaling_fac = canvas.fit_to_panel(dtop_canvas_px, self.preview.GetSize())
        placed = canvas.place_displays_with_bezels(display_data, dtop_canvas_pos, scaling_fac)
        # Move display preview draggable_shapes
        for shp, display in zip(self.draggable_shapes, placed):
            shp.pos = display.position
        self.positions_dragged = True
        self.preview.Refresh()

    def onEntry(self, evt):
        """Opens display positions accurate entry dialog."""
        DisplayPositionEntry(self.preview, self, dragged_positions=self.positions_dragged)

    def onCancel(self, evt):
        """Cancel out of diplay position config mode."""
        self.config_mode = False
        self.bind_movement_binds(False)
        self.toggle_buttons(True, False)
        self.draggable_shapes = []  # Destroys DragShapes
        staged = self.preview.staged
        staged.layout = staged.layout.with_offsets(self.old_ppinorm_offs)
        # redraw preview with restored data
        self.preview.display_data = staged.layout.ppi_norm_areas()
        self.preview.refresh_preview()
        self.preview.full_refresh_preview(True, "advanced")
        self._set_profile_controls_enabled(True)
        self._toggle_bezel_buttons(False, True)
        self.positions_dragged = False
        self.preview.Refresh()

    def onHelp(self, evt):
        """Popup a help dialog."""
        text = (
            "Preview of your wallpaper settings.\n"
            "In 'advanced span' mode you need use the 'Positions'\n"
            "tool to move the display previews by dragging to\n"
            "as accurately as possible represent the actual\n"
            "positions of you displays on your desk."
        )
        self._show_help(text, evt.GetEventObject())

    def show_staticbmps(self, show):
        """Show/Hide StaticBitmaps."""
        if self.preview.current_preview_images:
            self.preview.st_bmp_canvas.Show(show)
        else:
            self.preview.st_bmp_canvas.Show(False)
        for st_bmp in self.preview.preview_img_list:
            st_bmp.Show(show)

    def dragged_layout(self, layout):
        """``layout`` with the displays where the shapes were dragged: their positions on
        the preview, scaled up to the true canvas and anchored at (0, 0)."""
        # DragShape sizes and positions need to be scaled up by true_canvas_old_w/preview_canv_w
        prev_canv_w = self.preview.st_bmp_canvas.GetSize()[0]
        true_canv_w = canvas.desktop_extent(layout.ppi_norm_areas())[0]
        scaling = true_canv_w / prev_canv_w
        offsets = canvas.translate_to_origin([shape.pos for shape in self.draggable_shapes])
        return layout.with_offsets([(off[0] * scaling, off[1] * scaling) for off in offsets])

    #
    # DragImage methods
    #

    class DragShape:
        def __init__(self, bmp):
            self.bmp = bmp
            self.pos: tuple[int, int] = (0, 0)
            self.shown = True
            self.text = None
            self.fullscreen = False

        def HitTest(self, pt):
            rect = self.GetRect()
            return rect.Contains(pt)

        def GetRect(self):
            return wx.Rect(self.pos[0], self.pos[1], self.bmp.GetWidth(), self.bmp.GetHeight())

        def Draw(self, dc, op=wx.COPY):
            if self.bmp.IsOk():
                memDC = wx.MemoryDC()
                memDC.SelectObject(self.bmp)

                dc.Blit(
                    self.pos[0],
                    self.pos[1],
                    self.bmp.GetWidth(),
                    self.bmp.GetHeight(),
                    memDC,
                    0,
                    0,
                    op,
                    True,
                )

                return True
            else:
                return False

    def create_shapes(self, enable_movement=True):
        """Create draggable objects from display previews."""
        self.draggable_shapes = []
        self.drag_image = None
        self.drag_shape = None

        for st_bmp in self.preview.preview_img_list:
            shape = self.DragShape(st_bmp.GetBitmap())
            shape.pos = st_bmp.GetPosition()
            self.draggable_shapes.append(shape)

        self.preview.Bind(wx.EVT_PAINT, self.preview.OnPaint)
        if enable_movement:
            self.bind_movement_binds(True)

    def bind_movement_binds(self, toggle):
        """Bind or unbind DragImage dragging bindings."""
        if toggle:
            self.preview.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)
            self.preview.Bind(wx.EVT_LEFT_UP, self.OnLeftUp)
            self.preview.Bind(wx.EVT_MOTION, self.OnMotion)
            self.preview.Bind(wx.EVT_LEAVE_WINDOW, self.OnLeaveWindow)
        else:
            self.preview.Unbind(wx.EVT_LEFT_DOWN)
            self.preview.Unbind(wx.EVT_LEFT_UP)
            self.preview.Unbind(wx.EVT_MOTION)
            self.preview.Unbind(wx.EVT_LEAVE_WINDOW)

    def draw_shapes(self, dc):
        for shape in self.draggable_shapes:
            if shape.shown:
                shape.Draw(dc)

    def find_shape(self, pt):
        for shape in self.draggable_shapes:
            if shape.HitTest(pt):
                return shape
        return None

    def OnLeftDown(self, evt):
        # Did the mouse go down on one of our shapes?
        shape = self.find_shape(evt.GetPosition())

        # If a shape was 'hit', then set that as the shape we're going to
        # drag around. Get our start position. Dragging has not yet started.
        # That will happen once the mouse moves, OR the mouse is released.
        if shape:
            self.drag_shape = shape
            self.dragStartPos = evt.GetPosition()

    def OnLeftUp(self, evt):
        if not self.drag_image or not self.drag_shape:
            self.drag_image = None
            self.drag_shape = None
            return

        # Hide the image, end dragging, and nuke out the drag image.
        self.drag_image.Hide()
        self.drag_image.EndDrag()
        self.drag_image = None

        self.drag_shape.pos = (
            self.drag_shape.pos[0] + evt.GetPosition()[0] - self.dragStartPos[0],
            self.drag_shape.pos[1] + evt.GetPosition()[1] - self.dragStartPos[1],
        )

        self.drag_shape.shown = True
        self.preview.RefreshRect(self.drag_shape.GetRect())
        self.drag_shape = None
        self.positions_dragged = True

    def OnMotion(self, evt):
        # Ignore mouse movement if we're not dragging.
        if not self.drag_shape or not evt.Dragging() or not evt.LeftIsDown():
            return

        # if we have a shape, but haven't started dragging yet
        if self.drag_shape and not self.drag_image:
            # only start the drag after having moved a couple pixels
            tolerance = 2
            pt = evt.GetPosition()
            dx = abs(pt.x - self.dragStartPos.x)
            dy = abs(pt.y - self.dragStartPos.y)
            if dx <= tolerance and dy <= tolerance:
                return

            # refresh the area of the window where the shape was so it
            # will get erased.
            self.drag_shape.shown = False
            self.preview.RefreshRect(self.drag_shape.GetRect(), True)
            self.preview.Update()

            item = self.drag_shape.text or self.drag_shape.bmp
            self.drag_image = wx.DragImage(item, wx.Cursor(wx.CURSOR_HAND))

            hotspot = self.dragStartPos - self.drag_shape.pos
            self.drag_image.BeginDrag(hotspot, self.preview, self.drag_shape.fullscreen)

            self.drag_image.Move(pt)
            self.drag_image.Show()

        # if we have shape and image then move it, posibly highlighting another shape.
        elif self.drag_shape and self.drag_image:
            # now move it and show it again if needed
            self.drag_image.Move(evt.GetPosition())

    def OnLeaveWindow(self, evt):
        """On leavewindow event drop dragged image by simulating a left up event."""
        self.OnLeftUp(evt)

    #
    # Bezel Configuration mode
    #
    def start_bezel_config(self):
        """Enters bezel config mode.

        Reveals buttons on each display right and bottom edges
        to allow adding bezels. Additionally hides display
        position config button(s)."""
        # TODO Change background color?
        self.old_bezels = self.preview.staged.layout.bezels_in_mm()
        self.old_ppinorm_offs = self.preview.staged.layout.ppi_norm_offsets
        self.bezel_conifg_mode = True
        # Draw bitmaps manually, widgets can't overlap
        self.show_bezel_buttons(True)
        # Hide preview positioning config button
        self.toggle_buttons(False, False)

    def bezel_config_save(self):
        """Stage the new bezel values in the staged layout.

        Bezel sizes are kept in memory and shown in the preview; persistence to
        disk happens only when the system band's Save is pressed.
        """
        self.bezel_conifg_mode = False
        self.show_bezel_buttons(False)
        # Show preview positioning config button
        self.toggle_buttons(True, False)
        self.preview.full_refresh_preview(True, "advanced")
        self.preview.Refresh()

    def bezel_config_cancel(self):
        """Exits out of the bezel config mode without saving."""
        self.bezel_conifg_mode = False
        self.show_bezel_buttons(False)
        # Show preview positioning config button
        self.toggle_buttons(True, False)
        staged = self.preview.staged
        staged.layout = staged.layout.with_bezels(self.old_bezels).with_offsets(self.old_ppinorm_offs)
        for pops, bez_mms in zip(self.bezel_popups, self.old_bezels):
            pops[0].set_bezel_value(bez_mms[0])
            pops[1].set_bezel_value(bez_mms[1])
        self.preview.display_data = staged.layout.ppi_norm_areas()
        self.preview.full_refresh_preview(True, "advanced")
        self.preview.Refresh()

    def create_bezel_buttons(self):
        # load icons into bitmaps
        rb_png = str(resource("icons8-merge-vertical-96.png"))
        bb_png = str(resource("icons8-merge-horizontal-96.png"))
        rb_img = wx.Image(rb_png, type=wx.BITMAP_TYPE_ANY)
        bb_img = wx.Image(bb_png, type=wx.BITMAP_TYPE_ANY)
        rb_bmp = rb_img.Scale(20, 20).Resize(wx.Size(20, 20), wx.Point((0, 0))).ConvertToBitmap()
        bb_bmp = bb_img.Scale(20, 20).Resize(wx.Size(20, 20), wx.Point((0, 0))).ConvertToBitmap()

        # create bitmap buttons
        for st_bmp in self.preview.preview_img_list:
            butt_rb = wx.BitmapButton(self.preview, bitmap=rb_bmp, name="butt_bez_r", style=wx.BORDER_NONE)
            butt_bb = wx.BitmapButton(self.preview, bitmap=bb_bmp, name="butt_bez_b", style=wx.BORDER_NONE)
            bez_butt_color = wx.Colour(41, 47, 52)
            butt_rb.SetBackgroundColour(bez_butt_color)
            butt_bb.SetBackgroundColour(bez_butt_color)
            self.bez_butt_sz = butt_rb.GetSize()
            pos_rb, pos_bb = self.bezel_button_positions(st_bmp)
            butt_rb.SetPosition(wx.Point((pos_rb[0], pos_rb[1])))
            butt_bb.SetPosition(wx.Point((pos_bb[0], pos_bb[1])))
            butt_rb.Bind(wx.EVT_BUTTON, self.onBezelButton)
            butt_bb.Bind(wx.EVT_BUTTON, self.onBezelButton)
            self.bez_buttons.append((butt_rb, butt_bb))
        self.show_bezel_buttons(False)
        self.create_bezel_popups()

    def create_bezel_popups(self):
        self.bezel_popups = []
        bezel_mm = self.preview.staged.layout.bezels_in_mm()
        for butts, bez_mm in zip(self.bez_buttons, bezel_mm):
            pop_rb = self.popup_at_button(butts[0])
            pop_rb.set_bezel_value(bez_mm[0])
            pop_bb = self.popup_at_button(butts[1])
            pop_bb.set_bezel_value(bez_mm[1])
            self.bezel_popups.append((pop_rb, pop_bb))

    def popup_at_button(self, button):
        """Initialize a popup at button position."""
        try:
            pop = self.BezelEntryPopup(self.preview, wx.SIMPLE_BORDER | wx.PU_CONTAINS_CONTROLS, self)
        except AttributeError:
            pop = self.BezelEntryPopup(self.preview, wx.SIMPLE_BORDER, self)
        return pop

    def move_popup_to_button(self, pop, button):
        """Move pop next to its associated button."""
        butt_name = button.GetName()
        pos = button.ClientToScreen((0, 0))
        butt_sz = button.GetSize()
        pop_sz = pop.GetSize()
        if butt_name == "butt_bez_r":
            # Center pop vertically to button
            y_cntr = (-pop_sz[1] + butt_sz[1]) / 2
            pop.Position(pos, (-pop_sz[0], y_cntr))
        else:
            # Center pop horizontally to button
            x_cntr = (-pop_sz[0] + butt_sz[0]) / 2
            pop.Position(pos, (x_cntr, -pop_sz[1]))

    def show_bezel_buttons(self, show):
        """Show/Hide the bezel buttons."""
        for butt in self.bez_buttons:
            butt[0].Show(show)
            butt[1].Show(show)

    def bezel_button_positions(self, st_bmp):
        """Return the mid points on the screen of the right and bottom edges
        of the given StaticBitmap."""
        sz = st_bmp.GetSize()
        pos = st_bmp.GetPosition()
        bsz = self.bez_butt_sz
        pos_rb = (round(sz[0] + pos[0] - bsz[0] / 2), round(sz[1] / 2 + pos[1] - bsz[1] / 2))
        pos_bb = (round(sz[0] / 2 + pos[0] - bsz[0] / 2), round(sz[1] + pos[1] - bsz[1] / 2))
        return [pos_rb, pos_bb]

    def move_bezel_buttons(self):
        """Move bezel buttons after a resize."""
        for butts, st_bmp in zip(self.bez_buttons, self.preview.preview_img_list):
            pos_rb, pos_bb = self.bezel_button_positions(st_bmp)
            butts[0].SetPosition((pos_rb[0], pos_rb[1]))
            butts[1].SetPosition((pos_bb[0], pos_bb[1]))

    def move_bezel_popups(self):
        """Move bezel popups to their respective buttons."""
        for butts, pops in zip(self.bez_buttons, self.bezel_popups):
            self.move_popup_to_button(pops[0], butts[0])
            self.move_popup_to_button(pops[1], butts[1])

    def onBezelButton(self, event):
        for pop in self.bezel_popups:
            pop[0].Hide()
            pop[1].Hide()
        self.move_bezel_popups()
        # Get button instance and find it in list
        button = event.GetEventObject()
        button_pos = None
        for butt_pair in self.bez_buttons:
            if button in butt_pair:
                button_pos = (self.bez_buttons.index(butt_pair), butt_pair.index(button))
                break

        # Pick and show respective popup
        if button_pos is None:
            return
        pop = self.bezel_popups[button_pos[0]][button_pos[1]]
        pop.Show()

    #
    # Bezel entry pop-up
    #

    class BezelEntryPopup(wx.PopupTransientWindow):
        """Popup that is shown when a bezel button is pressed in bezel config."""

        def __init__(self, parent, style, layout_editor):
            wx.PopupWindow.__init__(self, parent, style)
            self.layout_editor = layout_editor
            pnl = wx.Panel(self)

            st = wx.StaticText(pnl, -1, "Enter the size of adjacent bezels and gap\nin millimeters:")
            self.tc_bez = wx.TextCtrl(pnl, -1, size=wx.Size(60, -1), style=wx.TE_RIGHT | wx.TE_PROCESS_ENTER)
            self.tc_bez.Bind(wx.EVT_TEXT_ENTER, self.OnEnter)
            self.current_bez_val = None
            butt_save = wx.Button(pnl, label="Apply")
            butt_canc = wx.Button(pnl, label="Cancel")
            butt_save.Bind(wx.EVT_BUTTON, self.onApply)
            butt_canc.Bind(wx.EVT_BUTTON, self.onCancel)
            butt_sizer = wx.BoxSizer(wx.HORIZONTAL)
            butt_sizer.Add(self.tc_bez, 0, wx.ALL, 5)
            butt_sizer.Add(butt_save, 0, wx.ALL, 5)
            butt_sizer.Add(butt_canc, 0, wx.ALL, 5)

            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.Add(st, 0, wx.ALL, 5)
            sizer.Add(butt_sizer, 0, wx.ALL | wx.EXPAND, 0)
            pnl.SetSizer(sizer)

            sizer.Fit(pnl)
            sizer.Fit(self)
            self.Layout()

        def ProcessLeftDown(self, event):
            return False

        def OnEnter(self, evt):
            """Bind pressing Enter in the txtctrl to apply entered value."""
            self.onApply(evt)

        def OnDismiss(self):
            self.onCancel(None)

        def onApply(self, event):
            entered_val = self.test_bezel_value()
            if entered_val is None:
                # Abort applying and alert user but don't
                # Dismiss popup to fascilitate fixing.
                msg = f"Bezel thickness must be a non-negative number, '{self.tc_bez.GetValue()}' was entered."
                logger.info(msg)
                self.Hide()
                show_message_dialog(msg, "Error", parent=self)
                self.Show()
                return -1
            self.current_bez_val = entered_val
            pops = self.layout_editor.bezel_popups
            bezel_mms = []
            for pop_pair in pops:
                bezel_mms.append((pop_pair[0].bezel_value(), pop_pair[1].bezel_value()))
            self.Hide()
            # propagate values and refresh preview
            preview = self.layout_editor.preview
            preview.staged.layout = preview.staged.layout.with_bezels(bezel_mms)
            preview.display_data = preview.staged.layout.ppi_norm_areas()
            preview.full_refresh_preview(True, "advanced")

        def onCancel(self, event):
            if self.current_bez_val:
                self.tc_bez.SetValue(str(self.current_bez_val))
            else:
                self.tc_bez.SetValue("0.0")
            self.Hide()

        def bezel_value(self):
            """Return the entered bezel thickness as a float."""
            bez = self.tc_bez.GetValue()
            return float(bez)

        def set_bezel_value(self, val):
            """Write val to TextCtrl."""
            self.tc_bez.SetValue(str(val))
            self.current_bez_val = str(val)

        def test_bezel_value(self):
            """The entered bezel thickness, or None unless it is a non-negative number."""
            value = parse_float(self.tc_bez.GetValue())
            return value if value is not None and value >= 0 else None
