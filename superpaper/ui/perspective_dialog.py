"""Creating, editing, deleting and testing perspectives."""

import os

import wx  # ty:ignore[unresolved-import]

from superpaper.geometry import perspective_form
from superpaper.geometry.display_store import SaveFailed
from superpaper.geometry.perspective import Named
from superpaper.paths import resource
from superpaper.profiles import profile_file
from superpaper.profiles.profile_id import NEW_PROFILE_LABEL
from superpaper.profiles.selection import real_file
from superpaper.ui.help import show_help_popup
from superpaper.ui.message import draft_shown, show_message_dialog
from superpaper.user_input import Problems


class PerspectiveConfig(wx.Dialog):
    """Perspective data configuration dialog.

    It works on its own ``layout``: the session's saved geometry with the editor's perspective
    choice, never the editor's unsaved band edits. ``offsets`` are the editor's applied manual
    offsets, which the image size check uses; ``typed_offsets`` are those typed in its fields,
    applied or not, which the align test uses.
    """

    def __init__(self, parent, offsets, typed_offsets):
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Configure wallpaper perspective rotations",
        )
        self.tc_width = 150
        self.frame = parent
        self.offsets = offsets
        self.typed_offsets = typed_offsets
        self.layout = parent.session.layout
        self._load_choice()
        self.test_image = None
        self.help_bmp = wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_BUTTON, wx.Size(20, 20))
        self.warn_large_img = parent.settings.warn_large_img

        sizer_main = wx.BoxSizer(wx.VERTICAL)

        # Master options
        sizer_top = wx.BoxSizer(wx.HORIZONTAL)
        self.cb_master = wx.CheckBox(self, -1, "Use perspective corrections")
        self.cb_master.SetValue(self.layout.use_perspective)
        self.button_help_persp = wx.BitmapButton(self, bitmap=wx.BitmapBundle(self.help_bmp))
        self.button_help_persp.Bind(wx.EVT_BUTTON, self.onHelpPerspective)
        sizer_top.Add(self.cb_master, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer_top.AddStretchSpacer()
        sizer_top.Add(self.button_help_persp, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)

        # Profile options
        self.create_profile_opts()

        # Display perspective config
        self.create_display_opts(len(self.layout.displays))

        # Bottom row buttons
        self.create_bottom_butts()

        sizer_main.Add(sizer_top, 0, wx.ALL | wx.EXPAND, 0)
        sizer_main.Add(self.sizer_prof_opts, 0, wx.ALL | wx.EXPAND, 5)
        sizer_main.Add(self.sizer_disp_opts, 0, wx.ALL | wx.EXPAND, 5)
        sizer_main.Add(self.sizer_buttons, 0, wx.ALL | wx.EXPAND, 5)
        self.SetSizer(sizer_main)
        self.Fit()
        if self.layout.default_perspective:
            self.populate_fields(self.layout.default_perspective)
            self.choice_profiles.SetSelection(self.choice_profiles.FindString(self.layout.default_perspective))

    def create_profile_opts(self):
        """Create sizer for perspective profile options."""
        self.sizer_prof_opts = wx.StaticBoxSizer(wx.VERTICAL, self, "Perspective profile")
        statbox_profs = self.sizer_prof_opts.GetStaticBox()

        self.sizer_prof_bar = wx.BoxSizer(wx.HORIZONTAL)
        self.profnames = self.layout.perspective_names()
        self.profnames.append(NEW_PROFILE_LABEL)
        self.choice_profiles = wx.ComboBox(
            statbox_profs, -1, name="ProfileChoice", choices=self.profnames, style=wx.CB_READONLY
        )
        self.choice_profiles.Bind(wx.EVT_COMBOBOX, self.onSelect)
        st_choice_profiles = wx.StaticText(statbox_profs, -1, "Perspective profiles:")
        # name txt ctrl
        st_name = wx.StaticText(statbox_profs, -1, "Profile name:")
        self.tc_name = wx.TextCtrl(statbox_profs, -1, size=wx.Size(self.tc_width, -1))
        # buttons
        self.button_new = wx.Button(statbox_profs, label="New")
        self.button_save = wx.Button(statbox_profs, label="Save")
        self.button_delete = wx.Button(statbox_profs, label="Delete")
        self.button_help_perspprof = wx.BitmapButton(statbox_profs, bitmap=wx.BitmapBundle(self.help_bmp))
        self.button_new.Bind(wx.EVT_BUTTON, self.onCreateNewProfile)
        self.button_save.Bind(wx.EVT_BUTTON, self.onSave)
        self.button_delete.Bind(wx.EVT_BUTTON, self.onDeleteProfile)
        self.button_help_perspprof.Bind(wx.EVT_BUTTON, self.onHelpPersProfile)

        # Add profile bar items to the sizer
        self.sizer_prof_bar.Add(st_choice_profiles, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(self.choice_profiles, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(st_name, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(self.tc_name, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(self.button_new, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(self.button_save, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(self.button_delete, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.AddStretchSpacer()
        self.sizer_prof_bar.Add(self.button_help_perspprof, 0, wx.CENTER | wx.LEFT, 5)

        self.sizer_prof_opts.Add(self.sizer_prof_bar, 0, wx.EXPAND | wx.ALL, 5)
        sline = wx.StaticLine(statbox_profs, -1, style=wx.LI_HORIZONTAL)
        self.sizer_prof_opts.Add(sline, 0, wx.EXPAND | wx.ALL, 5)

        # Profile related options
        self.cb_dispsys_def = wx.CheckBox(statbox_profs, -1, "Default for this display setup")
        sizer_centr_disp = wx.BoxSizer(wx.HORIZONTAL)
        st_centr_disp = wx.StaticText(statbox_profs, -1, "Central display:")
        disp_ids = [str(idx) for idx in range(len(self.layout.displays))]
        self.choice_centr_disp = wx.ComboBox(
            statbox_profs, -1, name="CentDispChoice", choices=disp_ids, style=wx.CB_READONLY
        )
        self.choice_centr_disp.SetSelection(0)
        sizer_centr_disp.Add(st_centr_disp, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer_centr_disp.Add(self.choice_centr_disp, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        sizer_viewer_off = wx.BoxSizer(wx.HORIZONTAL)
        st_vwroffs = wx.StaticText(statbox_profs, -1, "Viewer offset from central display center [mm]:")
        self.stlist_vieweroffs = [
            wx.StaticText(statbox_profs, -1, "hor:"),
            wx.StaticText(statbox_profs, -1, "ver:"),
            wx.StaticText(statbox_profs, -1, "dist:"),
        ]
        self.tclist_vieweroffs = [
            wx.TextCtrl(statbox_profs, -1, size=wx.Size(int(self.tc_width * 0.69), -1), style=wx.TE_RIGHT),
            wx.TextCtrl(statbox_profs, -1, size=wx.Size(int(self.tc_width * 0.69), -1), style=wx.TE_RIGHT),
            wx.TextCtrl(statbox_profs, -1, size=wx.Size(int(self.tc_width * 0.69), -1), style=wx.TE_RIGHT),
        ]
        for tc in self.tclist_vieweroffs:
            if isinstance(tc, wx.TextCtrl):
                tc.SetValue("0")
        szr_stlist = [(item, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5) for item in self.stlist_vieweroffs]
        szr_tclist = [(item, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5) for item in self.tclist_vieweroffs]
        sizer_viewer_off.Add(st_vwroffs, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        for st, tc in zip(szr_stlist, szr_tclist, strict=True):
            sizer_viewer_off.Add(st[0], st[1], st[2], st[3])
            sizer_viewer_off.Add(tc[0], tc[1], tc[2], tc[3])

        self.button_help_centrald = wx.BitmapButton(statbox_profs, bitmap=wx.BitmapBundle(self.help_bmp))
        self.button_help_centrald.Bind(wx.EVT_BUTTON, self.onHelpCentralDisp)
        sizer_viewer_off.AddStretchSpacer()
        sizer_viewer_off.Add(self.button_help_centrald, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        # Add remaining options to persp profile sizer
        self.sizer_prof_opts.Add(self.cb_dispsys_def, 0, wx.ALL, 5)
        self.sizer_prof_opts.Add(sizer_centr_disp, 0, wx.LEFT, 5)
        self.sizer_prof_opts.Add(sizer_viewer_off, 0, wx.LEFT | wx.EXPAND, 5)

    def create_display_opts(self, num_disps):
        """Create sizer for display perspective options."""
        self.sizer_disp_opts = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Display perspective configuration")
        statbox_disp_opts = self.sizer_disp_opts.GetStaticBox()
        cols = 8
        gap = 5
        self.grid = wx.FlexGridSizer(cols, gap, gap)

        # header
        hd_id = wx.StaticText(statbox_disp_opts, -1, "Display")
        hd_sax = wx.StaticText(statbox_disp_opts, -1, "Swivel axis")
        hd_san = wx.StaticText(statbox_disp_opts, -1, "Swivel angle")
        hd_sol = wx.StaticText(statbox_disp_opts, -1, "Sw. ax. lat. off.")
        hd_sod = wx.StaticText(statbox_disp_opts, -1, "Sw. ax. dep. off.")
        hd_tan = wx.StaticText(statbox_disp_opts, -1, "Tilt angle")
        hd_tov = wx.StaticText(statbox_disp_opts, -1, "Ti. ax. ver. off.")
        hd_tod = wx.StaticText(statbox_disp_opts, -1, "Ti. ax. dep. off.")
        self.grid.Add(hd_id, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(hd_sax, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(hd_san, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(hd_sol, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(hd_sod, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(hd_tan, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(hd_tov, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)
        self.grid.Add(hd_tod, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)

        # Fill grid rows
        self.grid_rows = []
        for i in range(num_disps):
            row = self.display_opt_widget_row(i)
            self.grid_rows.append(row)
            sizer_row = [(item, 0, wx.ALL | wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL, 1) for item in row]
            self.grid.AddMany(sizer_row)

        # Build sizer
        self.sizer_disp_opts.Add(self.grid, 0, wx.ALL | wx.EXPAND, 5)

        # help
        self.button_help_data = wx.BitmapButton(statbox_disp_opts, bitmap=wx.BitmapBundle(self.help_bmp))
        self.button_help_data.Bind(wx.EVT_BUTTON, self.onHelpData)
        self.sizer_disp_opts.AddStretchSpacer()
        self.sizer_disp_opts.Add(self.button_help_data, 0, wx.ALIGN_TOP | wx.RIGHT, 5)

    def display_opt_widget_row(self, row_id):
        """Return a display option widget row."""
        statbox_disp_opts = self.sizer_disp_opts.GetStaticBox()
        row_id = wx.StaticText(statbox_disp_opts, -1, str(row_id))
        row_sax = wx.ComboBox(
            statbox_disp_opts,
            -1,
            name="SwivelAxisChoice",
            size=wx.Size(int(self.tc_width * 0.7), -1),
            choices=["No swivel", "Left", "Right"],
            style=wx.CB_READONLY,
        )
        row_san = wx.TextCtrl(statbox_disp_opts, -1, size=wx.Size(int(self.tc_width * 0.69), -1), style=wx.TE_RIGHT)
        row_sol = wx.TextCtrl(statbox_disp_opts, -1, size=wx.Size(int(self.tc_width * 0.69), -1), style=wx.TE_RIGHT)
        row_sod = wx.TextCtrl(statbox_disp_opts, -1, size=wx.Size(int(self.tc_width * 0.69), -1), style=wx.TE_RIGHT)
        row_tan = wx.TextCtrl(statbox_disp_opts, -1, size=wx.Size(int(self.tc_width * 0.69), -1), style=wx.TE_RIGHT)
        row_tov = wx.TextCtrl(statbox_disp_opts, -1, size=wx.Size(int(self.tc_width * 0.69), -1), style=wx.TE_RIGHT)
        row_tod = wx.TextCtrl(statbox_disp_opts, -1, size=wx.Size(int(self.tc_width * 0.69), -1), style=wx.TE_RIGHT)
        # Prefill neutral data
        row_sax.SetSelection(0)
        row_san.SetValue("0")
        row_sol.SetValue("0")
        row_sod.SetValue("0")
        row_tan.SetValue("0")
        row_tov.SetValue("0")
        row_tod.SetValue("0")

        row = [row_id, row_sax, row_san, row_sol, row_sod, row_tan, row_tov, row_tod]
        return row

    def create_bottom_butts(self):
        """Create sizer for bottom row buttons."""
        self.sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)

        self.button_align_test = wx.Button(self, label="Align test")
        self.button_test_pick = wx.Button(self, label="Pick image")
        self.button_test_imag = wx.Button(self, label="Test image")
        self.button_ok = wx.Button(self, label="OK")
        self.button_cancel = wx.Button(self, label="Close")

        self.button_align_test.Bind(wx.EVT_BUTTON, self.onAlignTest)
        self.button_test_pick.Bind(wx.EVT_BUTTON, self.onChooseTestImage)
        self.button_test_imag.Bind(wx.EVT_BUTTON, self.onTestWallpaper)
        self.button_ok.Bind(wx.EVT_BUTTON, self.onOk)
        self.button_cancel.Bind(wx.EVT_BUTTON, self.onCancel)

        self.sizer_buttons.Add(self.button_align_test, 0, wx.CENTER | wx.ALL, 5)
        sline = wx.StaticLine(self, -1, style=wx.LI_VERTICAL)
        self.sizer_buttons.Add(sline, 0, wx.EXPAND | wx.ALL, 5)
        self.tc_testimage = wx.TextCtrl(self, -1, size=wx.Size(self.tc_width, -1))
        self.sizer_buttons.Add(self.tc_testimage, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_buttons.Add(self.button_test_pick, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_buttons.Add(self.button_test_imag, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_buttons.AddStretchSpacer()
        self.sizer_buttons.Add(self.button_ok, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_buttons.Add(self.button_cancel, 0, wx.CENTER | wx.ALL, 5)

    def populate_fields(self, persp_name):
        """Populate config fields from the layout's perspective ``persp_name``."""
        perspective = self.layout.perspective(persp_name)
        if perspective is None:
            # The layout's default names a perspective with no stored settings
            # (its .persp file is gone, say). Offer it as a new profile to fill in:
            # inventing settings here would let the next save of any perspective
            # persist them.
            self.onCreateNewProfile(None)
            self.tc_name.SetValue(persp_name)
            self.cb_dispsys_def.SetValue(True)
            return
        self.show_form(perspective_form.form_from(perspective, self.layout))

    def show_form(self, form):
        """Write ``form`` into the fields."""
        self.cb_master.SetValue(form.use_perspective)
        self.tc_name.SetValue(form.name)
        self.cb_dispsys_def.SetValue(form.is_default)
        self.choice_centr_disp.SetSelection(form.central_display)
        for tc, text in zip(self.tclist_vieweroffs, form.viewer_offsets, strict=True):
            tc.SetValue(text)
        for index, (row, axis, cells) in enumerate(
            zip(self.grid_rows, form.swivel_axes, form.rotation_cells, strict=True)
        ):
            row[0].SetLabel(str(index))
            row[1].SetSelection(axis)
            for tc, text in zip(row[2:], cells, strict=True):
                tc.SetValue(text)

    def update_choiceprofile(self):
        """Reload profile list into the choice box."""
        self.profnames = self.layout.perspective_names()
        self.profnames.append(NEW_PROFILE_LABEL)
        self.choice_profiles.SetItems(self.profnames)

    #
    # Button methods
    #
    def checkCbmaster(self, event=None):
        """Save master checkbox state into the layout."""
        master = self.cb_master.GetValue()
        if master != self.layout.use_perspective:
            self._save_choice(self.layout.with_use_perspective(master))

    def _load_choice(self):
        """Start from the editor's perspective choice. The geometry the perspectives are
        converted with is the saved layout's, as the session held it when the dialog opened,
        never the editor's unsaved band edits."""
        self.layout = self.layout.with_perspectives_of(self.frame.staged.layout)

    def _save_choice(self, layout):
        """Save the perspective choice of ``layout`` alone, without the editor's unsaved
        layout; the editor and the session then use it. Returns False, with the dialog back
        at the editor's choice, if it could not be saved."""
        failure = perspective_form.save_choice(self.frame.paths.config, layout)
        if failure is not None:
            self._show_save_failure(failure)
            return False
        self._adopt_saved(layout)
        return True

    def _adopt_saved(self, layout):
        self.layout = layout
        self.frame.adopt_perspectives(self.layout)
        self.frame.refresh_displays()

    def _show_save_failure(self, failure):
        show_message_dialog(failure.message, "Error")
        self._load_choice()
        self.cb_master.SetValue(self.layout.use_perspective)
        self.update_choiceprofile()

    def onSelect(self, event):
        """Acts once a profile is picked in the dropdown menu."""
        event_object = event.GetEventObject()
        if event_object.GetName() == "ProfileChoice":
            item_str = event.GetString()
            if item_str == NEW_PROFILE_LABEL:
                self.onCreateNewProfile(event)
            else:
                self.populate_fields(item_str)
        else:
            pass

    def onSave(self, evt=None):
        """Save perspective config to file and update display system state."""
        persp_name = self.tc_name.GetLineText(0)
        form = perspective_form.PerspectiveForm(
            name=persp_name,
            use_perspective=self.cb_master.GetValue(),
            is_default=self.cb_dispsys_def.GetValue(),
            central_display=int(self.choice_centr_disp.GetSelection()),
            viewer_offsets=tuple(tc.GetLineText(0) for tc in self.tclist_vieweroffs),
            swivel_axes=tuple(row[1].GetSelection() for row in self.grid_rows),
            rotation_cells=tuple(tuple(tc.GetLineText(0) for tc in row[2:]) for row in self.grid_rows),
        )

        def save(*, confirmed):
            return perspective_form.save_perspective(
                form,
                layout=self.layout,
                offsets=self.offsets,
                warn_large=self.warn_large_img,
                confirmed=confirmed,
                config_dir=self.frame.paths.config,
            )

        result = save(confirmed=False)
        if isinstance(result, perspective_form.NeedsConfirm):
            if not show_message_dialog(result.message, "Info", style="YES_NO"):
                return 0
            result = save(confirmed=True)
        match result:
            case Problems():
                show_message_dialog(result.messages[0])
                return 0
            case SaveFailed():
                self._show_save_failure(result)
                return 0
            case perspective_form.Saved():
                self._adopt_saved(result.layout)

        # update dialog profile list
        self.update_choiceprofile()
        self.choice_profiles.SetSelection(self.choice_profiles.FindString(persp_name))
        return 1

    def onDeleteProfile(self, evt):
        """Delete selected perspective profile."""
        selection = self.choice_profiles.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        persp_name = self.choice_profiles.GetString(selection)
        if not self._save_choice(self.layout.without_perspective(persp_name)):
            return
        # update dialog profile list
        self.update_choiceprofile()
        self.onCreateNewProfile(None)

    def onCreateNewProfile(self, evt):
        """Reset profile settings options to neutral state."""
        self.choice_profiles.SetSelection(self.choice_profiles.FindString(NEW_PROFILE_LABEL))
        self.show_form(perspective_form.blank_form(self.layout))

    def onOk(self, event):
        """Apply/save perspective settings and close dialog."""
        # Persist the master enable/disable toggle even when no named perspective
        # profile is being saved, so simply unchecking "Use perspective
        # corrections" and pressing OK actually sticks.
        self.checkCbmaster()
        if self.tc_name.GetValue() and not self.onSave():
            return
        self.EndModal(wx.ID_OK)

    def onCancel(self, event):
        """Closes perspective config, throwing away unsaved contents."""
        self.Destroy()

    def onAlignTest(self, event=None, image=None):
        """Sets a test image wallpaper using the current perspectve config."""
        use_persp = self.cb_master.GetValue()
        if not use_persp:
            msg = "Perspective corrections are disabled. Enable them to test?"
            res = show_message_dialog(msg, style="YES_NO")
            if res:
                self.cb_master.SetValue(True)
                self.checkCbmaster()  # update & save the layout
            else:
                # Don't enable, stop testing.
                msg = "Perspective corrections are disabled, abort test."
                res = show_message_dialog(msg)
                return 0

        wanted = image or str(resource("test.png"))
        found = real_file(wanted)
        if found is None:
            msg = f"Test image not found in {[wanted]}."
            show_message_dialog(msg, "Error")
            return 0
        testimage = [found]

        # Save entered perspective values and get its name
        save_succ = self.onSave()
        if save_succ == 0:
            # Save failed or canceled, abort test.
            return 0
        perspective = Named(self.choice_profiles.GetString(self.choice_profiles.GetSelection()))

        # The session takes the layout onSave reloaded, then shows the draft.
        profile = profile_file.draft(
            testimage, spanmode="advanced", perspective=perspective, offsets=self.typed_offsets
        )
        wx.BeginBusyCursor()
        self.frame.session.apply_draft(profile, testimage, on_done=lambda problem: wx.CallAfter(draft_shown, problem))
        return 1

    def onChooseTestImage(self, event):
        """Open a file dialog to choose a test image."""
        with wx.FileDialog(
            self,
            "Choose a test image",
            wildcard=(
                "Image files (*.jpg;*.jpeg;*.png;*.bmp;*.gif;*.tiff;*.webp)"
                "|*.jpg;*.jpeg;*.png;*.bmp;*.gif;*.tiff;*.webp"
            ),
            defaultDir=self.frame.settings.browse_default_dir,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as file_dialog:
            if file_dialog.ShowModal() == wx.ID_CANCEL:
                return  # the user changed their mind

            # Proceed loading the file chosen by the user
            self.test_image = file_dialog.GetPath()
            self.tc_testimage.SetValue(os.path.basename(self.test_image))
        return

    def onTestWallpaper(self, event):
        """Test the current perspective options by triggering a new wallpaper
        from the active wallpaper profile, if any."""
        if self.test_image:
            self.onAlignTest(image=self.test_image)
        else:
            msg = "Choose a test image first."  # .format(testimage)
            show_message_dialog(msg, "Error")
            return 0
        return 1

    def onHelpPerspective(self, evt):
        """Popup perspectives main help."""
        text = (
            "Perspective corrections were created to fix the\n"
            "wallpaper misalignment that arises when your diplays\n"
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
        show_help_popup(self, text, evt.GetEventObject())

    def onHelpPersProfile(self, evt):
        """Popup perspective profile help."""
        text = (
            "Perspective corrections do not work equally well\n"
            "with different kinds of images so you can create\n"
            "separate profiles, such as 'tilts_only' or 'swivel+tilt'"
        )
        show_help_popup(self, text, evt.GetEventObject())

    def onHelpCentralDisp(self, evt):
        """Popup central display & viewer position help."""
        text = (
            "To compute the perspective transforms the (rough)\n"
            "position of your eyes relative to your displays\n"
            "needs to be known. This is entered by selecting\n"
            "one display as the central display and entering\n"
            "distance offsets relative to that display's center.\n"
            "\n"
            "Distance must be entered and non-zero, horizontal\n"
            "and vertical offsets are optional. Lenghts are\n"
            "in millimeters."
        )
        show_help_popup(self, text, evt.GetEventObject())

    def onHelpData(self, evt):
        """Popup central display & viewer position help."""
        text = (
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
        show_help_popup(self, text, evt.GetEventObject())
