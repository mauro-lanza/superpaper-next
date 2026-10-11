"""Creating, editing, deleting and testing perspectives."""

import os
import sys

import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]

import superpaper.perspective as persp
import superpaper.render as render
from superpaper import profiles
from superpaper.paths import resource
from superpaper.settings import read_settings
from superpaper.ui.help import HelpPopup
from superpaper.ui.message import draft_shown, show_message_dialog


class PerspectiveConfig(wx.Dialog):
    """Perspective data configuration dialog."""

    def __init__(self, parent):
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Configure wallpaper perspective rotations",
            #    size=(750, 850)
        )
        self.tc_width = 150
        self.frame = parent
        self.display_sys = parent.display_sys
        self.persp_dict = self.display_sys.perspective_dict
        self.test_image = None
        self.help_bmp = wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_BUTTON, wx.Size(20, 20))
        self.warn_large_img = read_settings(parent.parent_tray_obj.settings_path, sys.platform).warn_large_img

        sizer_main = wx.BoxSizer(wx.VERTICAL)

        # Master options
        sizer_top = wx.BoxSizer(wx.HORIZONTAL)
        self.cb_master = wx.CheckBox(self, -1, "Use perspective corrections")
        self.cb_master.SetValue(self.display_sys.use_perspective)
        # self.cb_master.Bind(wx.EVT_CHECKBOX, self.onCbmaster)
        self.button_help_persp = wx.BitmapButton(self, bitmap=wx.BitmapBundle(self.help_bmp))
        self.button_help_persp.Bind(wx.EVT_BUTTON, self.onHelpPerspective)
        sizer_top.Add(self.cb_master, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer_top.AddStretchSpacer()
        sizer_top.Add(self.button_help_persp, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)

        # Profile options
        self.create_profile_opts()

        # Display perspective config
        self.create_display_opts(len(self.display_sys.disp_list))

        # Bottom row buttons
        self.create_bottom_butts()

        # sizer_main.Add(self.cb_master, 0, wx.ALL|wx.ALIGN_LEFT, 5)
        sizer_main.Add(sizer_top, 0, wx.ALL | wx.EXPAND, 0)
        sizer_main.Add(self.sizer_prof_opts, 0, wx.ALL | wx.EXPAND, 5)
        sizer_main.Add(self.sizer_disp_opts, 0, wx.ALL | wx.EXPAND, 5)
        sizer_main.Add(self.sizer_buttons, 0, wx.ALL | wx.EXPAND, 5)
        self.SetSizer(sizer_main)
        self.Fit()
        if self.display_sys.default_perspective:
            self.populate_fields(self.display_sys.default_perspective)
            self.choice_profiles.SetSelection(self.choice_profiles.FindString(self.display_sys.default_perspective))

    def create_profile_opts(self):
        """Create sizer for perspective profile options."""
        self.sizer_prof_opts = wx.StaticBoxSizer(wx.VERTICAL, self, "Perspective profile")
        statbox_profs = self.sizer_prof_opts.GetStaticBox()

        self.sizer_prof_bar = wx.BoxSizer(wx.HORIZONTAL)
        self.profnames = list(self.persp_dict.keys())
        self.profnames.append("Create a new profile")
        self.choice_profiles = wx.ComboBox(
            statbox_profs, -1, name="ProfileChoice", choices=self.profnames, style=wx.CB_READONLY
        )
        self.choice_profiles.Bind(wx.EVT_COMBOBOX, self.onSelect)
        st_choice_profiles = wx.StaticText(statbox_profs, -1, "Perspective profiles:")
        # name txt ctrl
        st_name = wx.StaticText(statbox_profs, -1, "Profile name:")
        self.tc_name = wx.TextCtrl(statbox_profs, -1, size=wx.Size(self.tc_width, -1))
        self.tc_name.SetMaxLength(14)
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
        disp_ids = [str(idx) for idx in range(len(self.display_sys.disp_list))]
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
        for st, tc in zip(szr_stlist, szr_tclist):
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
        """Populate config fields from DisplaySystem perspective dict."""
        persd = self.persp_dict.get(persp_name)
        if persd is None:
            # The display system's default names a perspective with no stored settings
            # (its .persp file is gone, say). Offer it as a new profile to fill in:
            # inventing settings here would let the next save of any perspective
            # persist them.
            self.onCreateNewProfile(None)
            self.tc_name.SetValue(persp_name)
            self.cb_dispsys_def.SetValue(True)
            return
        self.cb_master.SetValue(self.display_sys.use_perspective)
        self.tc_name.SetValue(persp_name)
        self.cb_dispsys_def.SetValue(persp_name == self.display_sys.default_perspective)
        self.choice_centr_disp.SetSelection(persd["central_disp"])
        px_per_mm = self.display_sys.max_ppi() / 25.4
        for tc, offs in zip(self.tclist_vieweroffs, persd["viewer_pos"]):
            tc.SetValue(str(offs / px_per_mm))
        self.populate_grid(persd["swivels"], persd["tilts"], px_per_mm)

    def populate_grid(self, swivels, tilts, px_per_mm):
        """Fill data grid from lists."""
        for row, sw, ti in zip(self.grid_rows, swivels, tilts):
            row[0].SetLabel(str(self.grid_rows.index(row)))
            row[1].SetSelection(sw[0])
            row[2].SetValue(str(sw[1]))
            row[3].SetValue(str(round(sw[2] / px_per_mm, 1)))
            row[4].SetValue(str(round(sw[3] / px_per_mm, 1)))
            row[5].SetValue(str(ti[0]))
            row[6].SetValue(str(round(ti[1] / px_per_mm, 1)))
            row[7].SetValue(str(round(ti[2] / px_per_mm, 1)))

    def collect_data_column(self, column):
        """Collect data from display data grid, returns a column as a list.

        Column ids are
            0   display id
            1   swivel axis
            2   swivel angle
            3   swivel lat offset
            4   swivel dep offset
            5   tilt angle
            6   tilt vert offset
            7   tilt dep offset
        """
        data = []

        for row in self.grid_rows:
            if column == 0 or column == 1:
                datum = row[column].GetSelection()
                try:
                    data.append(int(datum))
                except ValueError:
                    pass
            else:
                datum = row[column].GetLineText(0)
                try:
                    data.append(float(datum))
                except ValueError:
                    pass
        return data

    def update_choiceprofile(self):
        """Reload profile list into the choice box."""
        self.profnames = list(self.persp_dict.keys())
        self.profnames.append("Create a new profile")
        self.choice_profiles.SetItems(self.profnames)

    def check_for_large_image_size(self, persp_data):
        """How large an image the perspective ``persp_data`` would produce as an
        intermediate step: (whether that is too large, its size)."""
        if self.frame.cb_offsets.GetValue():
            offsets = []
            for tc in self.frame.tc_list_offsets:
                off_str = tc.GetValue().split(",")
                try:
                    offsets.append((int(off_str[0]), int(off_str[1])))
                except ValueError, IndexError:
                    offsets.append((0, 0))
        else:
            offsets = len(self.display_sys.disp_list) * [(0, 0)]
        crops = self.display_sys.get_ppi_norm_crops(offsets)
        proj_plane_crops, persp_coeffs = persp.get_backprojected_display_system(crops, persp_data)
        # Canvas containing back-projected displays
        canv = render.compute_working_canvas(proj_plane_crops)
        max_size = 12000
        if canv[0] > max_size or canv[1] > max_size:
            return (True, canv)
        return (False, canv)

    #
    # Button methods
    #
    def checkCbmaster(self, event=None):
        """Save master checkbox state into display system."""
        master = self.cb_master.GetValue()
        if master != self.display_sys.use_perspective:
            self.display_sys.use_perspective = master
            self.display_sys.save_system()
            self.frame.parent_tray_obj.refresh_displays()

    def onSelect(self, event):
        """Acts once a profile is picked in the dropdown menu."""
        event_object = event.GetEventObject()
        if event_object.GetName() == "ProfileChoice":
            item_str = event.GetString()
            if item_str == "Create a new profile":
                self.onCreateNewProfile(event)
            else:
                self.populate_fields(item_str)
        else:
            pass

    def onSave(self, evt=None):
        """Save perspective config to file and update display system state."""
        persp_name = self.tc_name.GetLineText(0)
        if not persp_name:
            msg = "Profile name is required."
            show_message_dialog(msg)
            return 0
        toggle = self.cb_master.GetValue()
        is_ds_def = self.cb_dispsys_def.GetValue()
        centr_disp = int(self.choice_centr_disp.GetSelection())
        px_per_mm = self.display_sys.max_ppi() / 25.4
        try:
            # covert lenghts to ppi norm res
            viewer_offset = [px_per_mm * float(tc.GetLineText(0)) for tc in self.tclist_vieweroffs]
        except ValueError:
            msg = "Viewer offsets should be lenghts in millimeters, separate decimals with a point."
            show_message_dialog(msg)
            return 0
        if viewer_offset[2] <= 0:
            msg = "Viewer distance must be entered and positive."
            show_message_dialog(msg)
            return 0
        viewer_data = (centr_disp, viewer_offset)
        swivels = []
        sw_axii = self.collect_data_column(1)
        sw_angl = self.collect_data_column(2)
        sw_lato = self.collect_data_column(3)
        sw_depo = self.collect_data_column(4)
        for ax, an, lo, do in zip(sw_axii, sw_angl, sw_lato, sw_depo):
            swivels.append((ax, an, px_per_mm * lo, px_per_mm * do))
        tilts = []
        ti_angl = self.collect_data_column(5)
        ti_vero = self.collect_data_column(6)
        ti_depo = self.collect_data_column(7)
        for an, vo, do in zip(ti_angl, ti_vero, ti_depo):
            tilts.append((an, px_per_mm * vo, px_per_mm * do))

        # Warn before saving settings that would need huge intermediate images. They are
        # checked as they are, so the layout is only changed once they are accepted.
        if self.warn_large_img:
            candidate = {"central_disp": centr_disp, "viewer_pos": viewer_offset, "swivels": swivels, "tilts": tilts}
            too_large, canvas = self.check_for_large_image_size(candidate)
            if too_large:
                msg = (
                    "These perspective settings will produce large intermediate images "
                    "which might use a large amount of system memory during processing. "
                    "Take care not to set the perspective so that you would see arbitrarily "
                    "far into the projected image as this will produce unboundedly large "
                    "images and will cause problems, even a system crash."
                    "\n\n"
                    f"Intermediate resolution with these settings is {canvas[0]}x{canvas[1]}"
                    "\n\n"
                    "Do you want to continue?\n"
                    "\n"
                    "This warning may be disabled from settings."
                )
                if not show_message_dialog(msg, "Info", style="YES_NO"):
                    return 0
        self.display_sys.update_perspectives(persp_name, toggle, is_ds_def, viewer_data, swivels, tilts)
        # Persist the perspective file first, then the display system that names the
        # default; the tray then reloads both as one layout.
        self.display_sys.save_perspectives()
        self.display_sys.save_system()
        self.frame.parent_tray_obj.refresh_displays()

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
        if self.display_sys.default_perspective == persp_name:
            self.display_sys.default_perspective = None
        self.persp_dict.pop(persp_name, None)
        self.display_sys.save_perspectives()
        self.display_sys.save_system()
        self.frame.parent_tray_obj.refresh_displays()
        # update dialog profile list
        self.update_choiceprofile()
        self.onCreateNewProfile(None)

    def onCreateNewProfile(self, evt):
        """Reset profile settings options to neutral state."""
        self.cb_master.SetValue(self.display_sys.use_perspective)
        self.choice_profiles.SetSelection(self.choice_profiles.FindString("Create a new profile"))
        self.tc_name.SetValue("")
        self.cb_dispsys_def.SetValue(False)
        self.choice_centr_disp.SetSelection(0)
        for tc in self.tclist_vieweroffs:
            tc.SetValue(str(0))
        swivels = len(self.display_sys.disp_list) * [(0, 0.0, 0.0, 0.0)]
        tilts = len(self.display_sys.disp_list) * [(0.0, 0.0, 0.0)]
        self.populate_grid(swivels, tilts, 1)

    def onOk(self, event):
        """Apply/save perspective settings and close dialog."""
        # Persist the master enable/disable toggle even when no named perspective
        # profile is being saved, so simply unchecking "Use perspective
        # corrections" and pressing OK actually sticks.
        self.checkCbmaster()
        if self.tc_name.GetValue():
            self.onSave()
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
                self.checkCbmaster()  # update & save display_sys
            else:
                # Don't enable, stop testing.
                msg = "Perspective corrections are disabled, abort test."
                res = show_message_dialog(msg)
                return 0

        if image:
            testimage = [os.path.realpath(image)]
        else:
            testimage = [str(resource("test.png"))]
        if not os.path.isfile(testimage[0]):
            msg = f"Test image not found in {testimage}."
            show_message_dialog(msg, "Error")
            return 0

        # Use the settings currently written out in the fields!
        offsets = []
        for off_tc in self.frame.tc_list_offsets:
            off = off_tc.GetLineText(0).split(",")
            try:
                offsets.append((int(off[0]), int(off[1])))
            except IndexError, ValueError:
                show_message_dialog(
                    f"Offsets must be integer pairs separated with a comma!\nProblematic offset is {off}"
                )
                return 0

        # Save entered perspective values and get its name
        save_succ = self.onSave()
        if save_succ == 0:
            # Save failed or canceled, abort test.
            return 0
        perspective = self.choice_profiles.GetString(self.choice_profiles.GetSelection())

        # onSave has asked the tray to reload its layout, which happens before the draft.
        profile = profiles.draft(testimage, spanmode="advanced", perspective=perspective, offsets=offsets)
        wx.BeginBusyCursor()
        self.frame.parent_tray_obj.apply_draft(
            profile, testimage, on_done=lambda problem: wx.CallAfter(draft_shown, problem)
        )
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
            defaultDir=self.frame.defdir,
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
        # use_per = self.cb_master.GetValue()
        # persname = self.choice_profiles.GetString(self.choice_profiles.GetSelection())
        pop = HelpPopup(
            self,
            text,
            show_image_quality=False,
            # use_perspective=use_per,
            # persp_name=persname
        )
        btn = evt.GetEventObject()
        pos = btn.ClientToScreen((0, 0))
        sz = btn.GetSize()
        pop.Position(pos, wx.Size(0, sz[1]))
        pop.Popup()

    def onHelpPersProfile(self, evt):
        """Popup perspective profile help."""
        text = (
            "Perspective corrections do not work equally well\n"
            "with different kinds of images so you can create\n"
            "separate profiles, such as 'tilts_only' or 'swivel+tilt'"
        )
        pop = HelpPopup(self, text)
        btn = evt.GetEventObject()
        pos = btn.ClientToScreen((0, 0))
        sz = btn.GetSize()
        pop.Position(pos, wx.Size(0, sz[1]))
        pop.Popup()

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
        pop = HelpPopup(self, text)
        btn = evt.GetEventObject()
        pos = btn.ClientToScreen((0, 0))
        sz = btn.GetSize()
        pop.Position(pos, wx.Size(0, sz[1]))
        pop.Popup()

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
        pop = HelpPopup(self, text)
        btn = evt.GetEventObject()
        pos = btn.ClientToScreen((0, 0))
        sz = btn.GetSize()
        pop.Position(pos, wx.Size(0, sz[1]))
        pop.Popup()
