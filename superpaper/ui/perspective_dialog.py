"""Creating, editing, deleting and testing perspectives."""

import os
from collections.abc import Callable, Sequence

import wx  # ty:ignore[unresolved-import]

from superpaper.geometry import perspective_form
from superpaper.geometry.displays import Layout
from superpaper.geometry.perspective import Named
from superpaper.paths import resource
from superpaper.profile_actions import align_test_profile, find_test_image
from superpaper.profiles.profile_file import Profile
from superpaper.profiles.profile_id import NEW_PROFILE_LABEL
from superpaper.ui.help import (
    CENTRAL_DISPLAY_HELP,
    DISPLAY_ROTATION_HELP,
    PERSPECTIVE_HELP,
    PERSPECTIVE_PROFILE_HELP,
    help_button,
)
from superpaper.ui.message import confirm, show_message
from superpaper.user_input import Offset, Problems


class PerspectiveConfig(wx.Dialog):
    """Perspective data configuration dialog.

    It works on the editor's staged layout, and stages every perspective change into it
    (``stage_perspectives``); the display band's Save writes them. ``offsets`` are the
    editor's applied manual offsets, which the image size check uses; ``typed_offsets`` are
    those typed in its fields, applied or not, which the align test uses.
    """

    def __init__(
        self,
        parent,
        offsets: Sequence[Offset],
        typed_offsets: Sequence[Offset],
        *,
        staged_layout: Callable[[], Layout],
        warn_large_img: bool,
        browse_default_dir: str,
        stage_perspectives: Callable[[Layout], None],
        show_test_profile: Callable[[Profile, list[str]], None],
    ):
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Configure wallpaper perspective rotations",
        )
        self.tc_width = 150
        self.offsets = offsets
        self.typed_offsets = typed_offsets
        self.layout = staged_layout()
        self._browse_default_dir = browse_default_dir
        self._stage_perspectives = stage_perspectives
        self._show_test_profile = show_test_profile
        self.test_image = None
        self.warn_large_img = warn_large_img

        sizer_main = wx.BoxSizer(wx.VERTICAL)

        # Master options
        sizer_top = wx.BoxSizer(wx.HORIZONTAL)
        self.cb_master = wx.CheckBox(self, -1, "Use perspective corrections")
        self.cb_master.SetValue(self.layout.use_perspective)
        sizer_top.Add(self.cb_master, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer_top.AddStretchSpacer()
        sizer_top.Add(help_button(self, PERSPECTIVE_HELP), 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10)

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
            self._select_profile(self.layout.default_perspective)

    def _select_profile(self, name: str) -> None:
        """Select ``name`` in the dropdown; names differing only in case are different profiles."""
        self.choice_profiles.SetSelection(self.choice_profiles.FindString(name, True))

    def create_profile_opts(self):
        """Create sizer for perspective profile options."""
        self.sizer_prof_opts = wx.StaticBoxSizer(wx.VERTICAL, self, "Perspective profile")
        statbox_profs = self.sizer_prof_opts.GetStaticBox()

        self.sizer_prof_bar = wx.BoxSizer(wx.HORIZONTAL)
        self.choice_profiles = wx.ComboBox(statbox_profs, -1, style=wx.CB_READONLY)
        self.update_choiceprofile()
        self.choice_profiles.Bind(wx.EVT_COMBOBOX, self.onSelect)
        st_choice_profiles = wx.StaticText(statbox_profs, -1, "Perspective profiles:")
        # name txt ctrl
        st_name = wx.StaticText(statbox_profs, -1, "Profile name:")
        self.tc_name = wx.TextCtrl(statbox_profs, -1, size=wx.Size(self.tc_width, -1))
        # buttons
        self.button_new = wx.Button(statbox_profs, label="New")
        self.button_save = wx.Button(statbox_profs, label="Save")
        self.button_delete = wx.Button(statbox_profs, label="Delete")
        self.button_new.Bind(wx.EVT_BUTTON, self.onCreateNewProfile)
        self.button_save.Bind(wx.EVT_BUTTON, self.onSave)
        self.button_delete.Bind(wx.EVT_BUTTON, self.onDeleteProfile)

        # Add profile bar items to the sizer
        self.sizer_prof_bar.Add(st_choice_profiles, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(self.choice_profiles, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(st_name, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(self.tc_name, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(self.button_new, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(self.button_save, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.Add(self.button_delete, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_prof_bar.AddStretchSpacer()
        self.sizer_prof_bar.Add(help_button(statbox_profs, PERSPECTIVE_PROFILE_HELP), 0, wx.CENTER | wx.LEFT, 5)

        self.sizer_prof_opts.Add(self.sizer_prof_bar, 0, wx.EXPAND | wx.ALL, 5)
        sline = wx.StaticLine(statbox_profs, -1, style=wx.LI_HORIZONTAL)
        self.sizer_prof_opts.Add(sline, 0, wx.EXPAND | wx.ALL, 5)

        # Profile related options
        self.cb_dispsys_def = wx.CheckBox(statbox_profs, -1, "Default for this display setup")
        sizer_centr_disp = wx.BoxSizer(wx.HORIZONTAL)
        st_centr_disp = wx.StaticText(statbox_profs, -1, "Central display:")
        disp_ids = [str(idx) for idx in range(len(self.layout.displays))]
        self.choice_centr_disp = wx.ComboBox(statbox_profs, -1, choices=disp_ids, style=wx.CB_READONLY)
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
        self.tclist_vieweroffs = [self._number_ctrl(statbox_profs) for _ in self.stlist_vieweroffs]
        sizer_viewer_off.Add(st_vwroffs, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        for st, tc in zip(self.stlist_vieweroffs, self.tclist_vieweroffs, strict=True):
            sizer_viewer_off.Add(st, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
            sizer_viewer_off.Add(tc, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        sizer_viewer_off.AddStretchSpacer()
        sizer_viewer_off.Add(help_button(statbox_profs, CENTRAL_DISPLAY_HELP), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        # Add remaining options to persp profile sizer
        self.sizer_prof_opts.Add(self.cb_dispsys_def, 0, wx.ALL, 5)
        self.sizer_prof_opts.Add(sizer_centr_disp, 0, wx.LEFT, 5)
        self.sizer_prof_opts.Add(sizer_viewer_off, 0, wx.LEFT | wx.EXPAND, 5)

    def _number_ctrl(self, parent):
        """Return a right-aligned text field prefilled with 0."""
        tc = wx.TextCtrl(parent, -1, size=wx.Size(int(self.tc_width * 0.69), -1), style=wx.TE_RIGHT)
        tc.SetValue("0")
        return tc

    def create_display_opts(self, num_disps):
        """Create sizer for display perspective options."""
        self.sizer_disp_opts = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Display perspective configuration")
        statbox_disp_opts = self.sizer_disp_opts.GetStaticBox()
        cols = 8
        gap = 5
        self.grid = wx.FlexGridSizer(cols, gap, gap)

        # header
        headers = (
            "Display",
            "Swivel axis",
            "Swivel angle",
            "Sw. ax. lat. off.",
            "Sw. ax. dep. off.",
            "Tilt angle",
            "Ti. ax. ver. off.",
            "Ti. ax. dep. off.",
        )
        for header in headers:
            self.grid.Add(wx.StaticText(statbox_disp_opts, -1, header), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 1)

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
        self.sizer_disp_opts.AddStretchSpacer()
        self.sizer_disp_opts.Add(help_button(statbox_disp_opts, DISPLAY_ROTATION_HELP), 0, wx.ALIGN_TOP | wx.RIGHT, 5)

    def display_opt_widget_row(self, row_id):
        """Return a display option widget row."""
        statbox_disp_opts = self.sizer_disp_opts.GetStaticBox()
        row_id = wx.StaticText(statbox_disp_opts, -1, str(row_id))
        row_sax = wx.ComboBox(
            statbox_disp_opts,
            -1,
            size=wx.Size(int(self.tc_width * 0.7), -1),
            choices=["No swivel", "Left", "Right"],
            style=wx.CB_READONLY,
        )
        row_sax.SetSelection(0)
        numbers = [self._number_ctrl(statbox_disp_opts) for _ in range(6)]
        return [row_id, row_sax, *numbers]

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
            self._show_blank()
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
        self.choice_profiles.SetItems([*self.layout.perspective_names(), NEW_PROFILE_LABEL])

    #
    # Button methods
    #
    def checkCbmaster(self):
        """Stage the master checkbox state."""
        master = self.cb_master.GetValue()
        if master != self.layout.use_perspective:
            self._stage(self.layout.with_use_perspective(master))

    def _stage(self, layout):
        """Stage the perspective choice of ``layout`` into the editor's layout."""
        self.layout = layout
        self._stage_perspectives(layout)

    def onSelect(self, event):
        """Acts once a profile is picked in the dropdown menu."""
        item_str = event.GetString()
        if item_str == NEW_PROFILE_LABEL:
            self._show_blank()
        else:
            self.populate_fields(item_str)

    def onSave(self, evt=None) -> str | None:
        """Stage the perspective config into the editor's layout; the name it was saved
        under, or None if it was not valid."""
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

        def stage(*, confirmed):
            return perspective_form.stage_perspective(
                form,
                layout=self.layout,
                offsets=self.offsets,
                warn_large=self.warn_large_img,
                confirmed=confirmed,
            )

        result = stage(confirmed=False)
        if isinstance(result, perspective_form.NeedsConfirm):
            if not confirm(result.message, "Info"):
                return None
            result = stage(confirmed=True)
        match result:
            case Problems():
                show_message(result.messages[0])
                return None
            case perspective_form.Staged():
                self._stage(result.layout)

        # update dialog profile list
        self.update_choiceprofile()
        self._select_profile(persp_name)
        return persp_name

    def onDeleteProfile(self, evt):
        """Delete selected perspective profile."""
        selection = self.choice_profiles.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        persp_name = self.choice_profiles.GetString(selection)
        self._stage(self.layout.without_perspective(persp_name))
        # update dialog profile list
        self.update_choiceprofile()
        self._show_blank()

    def _show_blank(self):
        """Select "new profile" and reset the fields to a neutral state."""
        self._select_profile(NEW_PROFILE_LABEL)
        self.show_form(perspective_form.blank_form(self.layout))

    def onCreateNewProfile(self, evt):
        self._show_blank()

    def onOk(self, event):
        """Apply/save perspective settings and close dialog."""
        # Persist the master enable/disable toggle even when no named perspective
        # profile is being saved, so simply unchecking "Use perspective
        # corrections" and pressing OK actually sticks.
        self.checkCbmaster()
        if self.tc_name.GetValue() and self.onSave() is None:
            return
        self.EndModal(wx.ID_OK)

    def onCancel(self, event):
        """Closes perspective config, throwing away unsaved contents."""
        self.EndModal(wx.ID_CANCEL)

    def onAlignTest(self, event):
        self._align_test(None)

    def _align_test(self, image: str | None) -> None:
        """Sets a test image wallpaper using the current perspective config."""
        if not self.cb_master.GetValue():
            msg = "Perspective corrections are disabled. Enable them to test?"
            if confirm(msg):
                self.cb_master.SetValue(True)
                self.checkCbmaster()  # stage it
            else:
                # Don't enable, stop testing.
                show_message("Perspective corrections are disabled, abort test.")
                return

        found = find_test_image(image, str(resource("test.png")))
        if isinstance(found, Problems):
            show_message(found.messages[0], "Error")
            return

        # The test is rendered with the layout onSave just staged.
        name = self.onSave()
        if name is None:
            return
        self._show_test_profile(align_test_profile(found, Named(name), self.typed_offsets), [found])

    def onChooseTestImage(self, event):
        """Open a file dialog to choose a test image."""
        with wx.FileDialog(
            self,
            "Choose a test image",
            wildcard=(
                "Image files (*.jpg;*.jpeg;*.png;*.bmp;*.gif;*.tiff;*.webp)"
                "|*.jpg;*.jpeg;*.png;*.bmp;*.gif;*.tiff;*.webp"
            ),
            defaultDir=self._browse_default_dir,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as file_dialog:
            if file_dialog.ShowModal() == wx.ID_CANCEL:
                return  # the user changed their mind

            # Proceed loading the file chosen by the user
            self.test_image = file_dialog.GetPath()
            self.tc_testimage.SetValue(os.path.basename(self.test_image))

    def onTestWallpaper(self, event):
        """Test the current perspective options by triggering a new wallpaper
        from the active wallpaper profile, if any."""
        if self.test_image:
            self._align_test(self.test_image)
        else:
            show_message("Choose a test image first.", "Error")
