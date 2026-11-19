"""The wallpaper configuration window: the profile editor, with its preview of the
displays and the display settings band."""

import logging
from dataclasses import replace
from functools import partial
from typing import assert_never

import wx  # ty:ignore[unresolved-import]

from superpaper.geometry import canvas, layout_edit
from superpaper.geometry.displays import Layout
from superpaper.geometry.perspective import Default, Disabled, choice_label, parse_choice
from superpaper.paths import resource
from superpaper.profile_actions import delete_profile, revert_profile, save_profile, saved_profile, show_draft
from superpaper.profiles import form, profile_file
from superpaper.profiles.profile_file import SPAN_MODES, SpanMode
from superpaper.profiles.profile_id import NEW_PROFILE_LABEL
from superpaper.profiles.selection import first_image, is_file
from superpaper.ui.browse_dialog import BrowsePaths, source_icon
from superpaper.ui.display_band import DisplayBand
from superpaper.ui.help import HelpFrame, image_quality_advice, show_help_popup
from superpaper.ui.message import draft_shown, show_message_dialog
from superpaper.ui.perspective_dialog import PerspectiveConfig
from superpaper.ui.preview import WallpaperPreviewPanel
from superpaper.user_input import Offset, OffsetError, Problems, parse_offsets

logger = logging.getLogger(__name__)


class StagedLayout:
    """The editor's unsaved display layout: one Layout, replaced as the user edits it.

    Nothing outside the editor sees it until Apply or Save hands the current value over, and
    a Layout never changes, so that value is safe to give to the session's worker.
    """

    def __init__(self, layout: Layout):
        self.layout = layout


class ConfigFrame(wx.Frame):
    """The wallpaper configuration window: see WallpaperSettingsPanel."""

    def __init__(self, paths, get_settings, store, session, *, update_settings, refresh_displays, rebind_hotkey):
        wx.Frame.__init__(self, parent=None, title="Superpaper Wallpaper Configuration")
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        config_panel = WallpaperSettingsPanel(
            self,
            paths,
            get_settings,
            store,
            session,
            update_settings=update_settings,
            refresh_displays=refresh_displays,
            rebind_hotkey=rebind_hotkey,
        )
        frame_sizer.Add(config_panel, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)
        self.SetIcon(wx.Icon(str(resource("superpaper.png")), wx.BITMAP_TYPE_PNG))
        self.Fit()
        self.Layout()
        self.Center()
        self.Show()
        self.SetMinSize(wx.Size(800, 600))


class WallpaperSettingsPanel(wx.Panel):
    """The profile editor, with the preview of the displays and the display band.

    It edits the saved profiles in ``store`` and tells ``session`` what became of the
    running one; drafts (Apply, the align tests) are shown by ``session`` too. The
    display settings band and the perspective dialog work on a staged display layout,
    which starts as the session's. ``get_settings()`` returns the general settings as they are now,
    ``update_settings(settings)`` saves them, ``refresh_displays()`` detects the
    displays again, for the session, and ``rebind_hotkey(before, after)`` moves a saved
    profile's hotkey along with it.
    """

    span_mode: SpanMode

    def __init__(
        self, parent, paths, get_settings, store, session, *, update_settings, refresh_displays, rebind_hotkey
    ):
        wx.Panel.__init__(self, parent)
        self.frame = parent
        self.paths = paths
        self._get_settings = get_settings
        self.update_settings = update_settings
        self.store = store
        self.session = session
        self.refresh_displays = refresh_displays
        self._rebind_hotkey = rebind_hotkey
        # The saved profile open in the editor: the store's record of it, the one the tray
        # menu offers and the session runs.
        self.loaded_profile = None
        self.sizer_main = wx.BoxSizer(wx.VERTICAL)
        self.sizer_top_half = wx.BoxSizer(wx.HORIZONTAL)  # wallpaper/monitor preview
        self.sizer_bottom_half = wx.BoxSizer(wx.VERTICAL)  # settings, buttons etc
        # bottom_half: setting sizers
        self.sizer_profiles = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_setting_sizers = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_settings_left = wx.BoxSizer(wx.VERTICAL)
        self.sizer_settings_right = wx.BoxSizer(wx.HORIZONTAL)
        # bottom_half: bottom button row
        self.sizer_bottom_buttonrow = wx.BoxSizer(wx.HORIZONTAL)

        # settings GUI properties
        self.tc_width = 160  # standard width for wx.TextCtrl etc elements.
        self.span_mode: SpanMode = "single"
        self.multi_column_listc = False
        BMP_SIZE = 32
        self.tsize = (BMP_SIZE, BMP_SIZE)
        self.image_list = wx.ImageList(BMP_SIZE, BMP_SIZE)

        # top half
        self.resized = False
        # ``_clean_serial`` is the fingerprint of the profile as last saved/loaded: Save and
        # Revert enable only when the fields differ. ``_loading`` suppresses tracking while
        # fields are populated programmatically.
        self._clean_serial = None
        self._loading = False
        # This is staged dialog state. Do not publish it until Apply/Save; live
        # field edits must not alter the layout used by background jobs. A Layout
        # never changes, so starting from the session's needs no copy.
        self.staged = StagedLayout(session.layout)
        self.wpprev_pnl = WallpaperPreviewPanel(
            self,
            self.staged,
            set_profile_controls_enabled=self.toggle_radio_and_profile_choice,
            # the band is created after the preview, so its methods are looked up when called
            toggle_bezel_buttons=lambda bezel_mode, enable_config_butt: self.display_band.toggle_bezel_buttons(
                bezel_mode, enable_config_butt
            ),
            mark_dirty=lambda: self.display_band.update_dirty(),
            show_help=self.show_preview_help,
        )
        self.sizer_top_half.Add(self.wpprev_pnl, 1, wx.CENTER | wx.EXPAND, 5)
        self.wpprev_pnl.Bind(wx.EVT_SIZE, self.onResize)
        self.wpprev_pnl.Bind(wx.EVT_IDLE, self.onIdle)

        # bottom half

        # profile sizer contents
        self.create_sizer_profiles()

        # settings sizer left contents
        self.create_sizer_settings_left()

        self.create_sizer_settings_advanced()

        # settings sizer right contents
        self.create_sizer_paths()

        # bottom button row contents
        self.create_sizer_bottom_buttonrow()

        # collapsible system (display-wide) settings band
        self.display_band = DisplayBand(
            self,
            self.staged,
            self.wpprev_pnl.layout_editor,
            field_width=int(self.tc_width * 2 / 5),
            relayout=self.sizer_main.Layout,
            refresh_preview=self.refresh_layout_preview,
            enable_profile_editing=self.toggle_radio_and_profile_choice,
            save_layout=lambda layout: layout_edit.save_display_settings(paths.config, layout),
            on_saved=self.refresh_displays,  # the slideshow uses them from now on
        )

        # Add sub-sizers to bottom_half
        #    Note: horizontal sizer needs children to have proportion = 1
        #    in order to expand them horizontally instead of vertically.
        self.sizer_setting_sizers.Add(self.sizer_settings_left, 0, wx.CENTER | wx.EXPAND | wx.TOP | wx.LEFT, 5)
        self.sizer_setting_sizers.Add(self.sizer_settings_right, 1, wx.CENTER | wx.EXPAND | wx.TOP | wx.LEFT, 0)
        self.sizer_setting_sizers.Add(self.sizer_setting_adv, 0, wx.CENTER | wx.EXPAND | wx.TOP | wx.RIGHT, 5)

        # System band sits above the profile selector, visually separating the
        # display-wide settings (top) from the per-profile settings (below).
        self.sizer_bottom_half.Add(self.display_band, 0, wx.EXPAND | wx.ALL, 5)
        self.sizer_bottom_half.Add(wx.StaticLine(self, style=wx.LI_HORIZONTAL), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        self.sizer_bottom_half.Add(self.sizer_profiles, 0, wx.CENTER | wx.EXPAND | wx.ALL, 0)
        self.sizer_bottom_half.Add(self.sizer_setting_sizers, 1, wx.CENTER | wx.EXPAND | wx.ALL, 0)
        self.sizer_bottom_half.Add(self.sizer_bottom_buttonrow, 0, wx.CENTER | wx.EXPAND | wx.ALL, 0)

        # Collect items at main sizer
        self.sizer_main.Add(self.sizer_top_half, 1, wx.CENTER | wx.EXPAND | wx.BOTTOM, 5)
        self.sizer_main.Add(self.sizer_bottom_half, 0, wx.CENTER | wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, 0)

        self.SetSizer(self.sizer_main)
        self.sizer_main.Fit(self.frame)

        self.sizer_setting_sizers.Hide(self.sizer_setting_adv)

        # Controls with their own handler (checkboxes, span radio, sliders, the path list)
        # call _update_dirty_state() from it; text fields and choices are caught here.
        self.Bind(wx.EVT_TEXT, self._on_field_changed)
        self.Bind(wx.EVT_COMBOBOX, self._on_field_changed)

        running = self.session.running
        if running:
            active_id = self.choice_profiles.FindString(running.profile.name)
            self.choice_profiles.SetSelection(active_id)
            self.populate_fields(running)
        else:
            # No active profile: start from a clean, empty new-profile baseline.
            self._set_clean_baseline()

        # Record the loaded display-wide settings as the system clean baseline.
        self.display_band.set_baseline()

        ### End __init__.

    #
    # Sizer creation methods
    #
    def create_sizer_profiles(self):
        # choice menu
        self.choice_profiles = wx.ComboBox(
            self, -1, name="ProfileChoice", choices=self._profile_choices(), style=wx.CB_READONLY
        )
        self.choice_profiles.Bind(wx.EVT_COMBOBOX, self.onSelect)
        st_choice_profiles = wx.StaticText(self, -1, "Setting profiles:")
        # name txt ctrl
        st_name = wx.StaticText(self, -1, "Profile name:")
        self.tc_name = wx.TextCtrl(self, -1, size=wx.Size(self.tc_width, -1))
        # buttons
        self.button_save = wx.Button(self, label="Save")
        self.button_revert = wx.Button(self, label="Revert")
        self.button_delete = wx.Button(self, label="Delete")
        self.button_save.Bind(wx.EVT_BUTTON, self.onSave)
        self.button_revert.Bind(wx.EVT_BUTTON, self.onRevert)
        self.button_delete.Bind(wx.EVT_BUTTON, self.onDeleteProfile)
        self.button_save.SetToolTip(wx.ToolTip("Save the current changes permanently to the profile."))
        self.button_revert.SetToolTip(wx.ToolTip("Discard unsaved changes and reload the saved profile."))
        # Save/Revert start disabled; they enable only when there are unsaved
        # changes to the profile configuration.
        self.button_save.Disable()
        self.button_revert.Disable()

        # Add elements to the sizer
        self.sizer_profiles.Add(st_choice_profiles, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_profiles.Add(self.choice_profiles, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_profiles.Add(st_name, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_profiles.Add(self.tc_name, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_profiles.Add(self.button_save, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_profiles.Add(self.button_revert, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_profiles.Add(self.button_delete, 0, wx.CENTER | wx.ALL, 5)

    def create_sizer_settings_left(self):
        # span mode sizer
        radio_choices_spanmode = [
            "Simple span",
            "Advanced span",
            "Separate image for every display",
        ]
        self.radiobox_spanmode = wx.RadioBox(
            self, wx.ID_ANY, label="Span mode", choices=radio_choices_spanmode, style=wx.RA_VERTICAL
        )
        self.radiobox_spanmode.Bind(wx.EVT_RADIOBOX, self.onSpanRadio)

        # slideshow sizer
        self.sizer_setting_slideshow = wx.StaticBoxSizer(wx.VERTICAL, self, "Wallpaper slideshow")
        statbox_parent_sshow = self.sizer_setting_slideshow.GetStaticBox()
        sizer_sshow_subsettings = wx.GridSizer(2, 5, 5)
        self.st_sshow_sort = wx.StaticText(statbox_parent_sshow, -1, "Slideshow order:")
        self.ch_sshow_sort = wx.ComboBox(
            statbox_parent_sshow,
            -1,
            name="SortChoice",
            choices=list(form.SORT_LABELS.values()),
            style=wx.CB_READONLY,
        )
        self.st_sshow_delay = wx.StaticText(statbox_parent_sshow, -1, "Delay (minutes):")
        self.tc_sshow_delay = wx.TextCtrl(
            statbox_parent_sshow,
            -1,
            style=wx.TE_RIGHT,
        )
        self.cb_slideshow = wx.CheckBox(statbox_parent_sshow, -1, "Slideshow")
        self.st_sshow_sort.Disable()
        self.st_sshow_delay.Disable()
        self.tc_sshow_delay.Disable()
        self.ch_sshow_sort.Disable()
        self.cb_slideshow.Bind(wx.EVT_CHECKBOX, self.onCheckboxSlideshow)
        self.sizer_setting_slideshow.Add(self.cb_slideshow, 0, wx.ALIGN_LEFT | wx.ALL, 5)
        sizer_sshow_subsettings.Add(self.st_sshow_delay, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 0)
        sizer_sshow_subsettings.Add(self.tc_sshow_delay, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.ALIGN_LEFT, 3)
        sizer_sshow_subsettings.Add(self.st_sshow_sort, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 0)
        sizer_sshow_subsettings.Add(self.ch_sshow_sort, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT | wx.ALIGN_LEFT, 5)
        self.sizer_setting_slideshow.Add(sizer_sshow_subsettings, 0, wx.ALIGN_LEFT | wx.LEFT | wx.BOTTOM, 10)

        # hotkey sizer
        self.sizer_setting_hotkey = wx.StaticBoxSizer(wx.VERTICAL, self, "Hotkey")
        statbox_parent_hkey = self.sizer_setting_hotkey.GetStaticBox()
        self.cb_hotkey = wx.CheckBox(statbox_parent_hkey, -1, "Bind a hotkey to this profile")
        st_hotkey_bind = wx.StaticText(statbox_parent_hkey, -1, "Hotkey to bind:")
        st_hotkey_bind.Disable()
        self.tc_hotkey_bind = wx.TextCtrl(statbox_parent_hkey, -1, size=wx.Size(self.tc_width, -1))
        self.tc_hotkey_bind.Disable()
        self.tc_hotkey_bind.SetToolTip(wx.ToolTip("Modifiers: control, alt, shift, super.\nExample: control+super+x"))
        self.hotkey_bind_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.hotkey_bind_sizer.Add(st_hotkey_bind, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.hotkey_bind_sizer.Add(self.tc_hotkey_bind, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        help_bmp = wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_BUTTON, wx.Size(20, 20))
        self.button_help_hotkey = wx.BitmapButton(
            statbox_parent_hkey, bitmap=wx.BitmapBundle(help_bmp), name="butt_help_hk"
        )
        self.button_help_hotkey.Bind(wx.EVT_BUTTON, self.onHelpHotkey)
        self.hotkey_bind_sizer.Add(self.button_help_hotkey, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.sizer_setting_hotkey.Add(self.cb_hotkey, 0, wx.ALIGN_LEFT | wx.ALL, 5)
        self.sizer_setting_hotkey.Add(self.hotkey_bind_sizer, 0, wx.CENTER | wx.EXPAND | wx.ALL, 5)
        self.cb_hotkey.Bind(wx.EVT_CHECKBOX, self.onCheckboxHotkey)

        # image scaling & position sizer
        self.sizer_setting_zoom = wx.StaticBoxSizer(wx.VERTICAL, self, "Image scaling & position")
        statbox_parent_zoom = self.sizer_setting_zoom.GetStaticBox()
        zoom_grid = wx.FlexGridSizer(3, 3, 5, 5)
        zoom_grid.AddGrowableCol(1, 1)
        # Zoom
        st_zoom = wx.StaticText(statbox_parent_zoom, -1, "Zoom:")
        self.sld_zoom = wx.Slider(statbox_parent_zoom, -1, 100, 100, 400, style=wx.SL_HORIZONTAL)
        self.st_zoom_val = wx.StaticText(statbox_parent_zoom, -1, "100%", size=wx.Size(40, -1), style=wx.ALIGN_RIGHT)
        # Horizontal position
        st_offx = wx.StaticText(statbox_parent_zoom, -1, "Horizontal:")
        self.sld_offx = wx.Slider(statbox_parent_zoom, -1, 0, -100, 100, style=wx.SL_HORIZONTAL)
        self.st_offx_val = wx.StaticText(statbox_parent_zoom, -1, "0", size=wx.Size(40, -1), style=wx.ALIGN_RIGHT)
        # Vertical position
        st_offy = wx.StaticText(statbox_parent_zoom, -1, "Vertical:")
        self.sld_offy = wx.Slider(statbox_parent_zoom, -1, 0, -100, 100, style=wx.SL_HORIZONTAL)
        self.st_offy_val = wx.StaticText(statbox_parent_zoom, -1, "0", size=wx.Size(40, -1), style=wx.ALIGN_RIGHT)
        self.sld_zoom.SetToolTip(wx.ToolTip("Zoom further into the image. The wallpaper always fills the screen."))
        self.sld_offx.SetToolTip(wx.ToolTip("Move the visible area left or right within the image."))
        self.sld_offy.SetToolTip(wx.ToolTip("Move the visible area up or down within the image."))
        for sld in (self.sld_zoom, self.sld_offx, self.sld_offy):
            sld.Bind(wx.EVT_SLIDER, self.onZoomOffsetChange)
        zoom_grid.Add(st_zoom, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        zoom_grid.Add(self.sld_zoom, 1, wx.EXPAND)
        zoom_grid.Add(self.st_zoom_val, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        zoom_grid.Add(st_offx, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        zoom_grid.Add(self.sld_offx, 1, wx.EXPAND)
        zoom_grid.Add(self.st_offx_val, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        zoom_grid.Add(st_offy, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        zoom_grid.Add(self.sld_offy, 1, wx.EXPAND)
        zoom_grid.Add(self.st_offy_val, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.sizer_setting_zoom.Add(zoom_grid, 0, wx.EXPAND | wx.ALL, 5)

        # Small undo button to reset scaling & position to defaults without
        # touching the rest of the profile configuration.
        undo_bmp = wx.ArtProvider.GetBitmap(wx.ART_UNDO, wx.ART_BUTTON, wx.Size(16, 16))
        self.button_zoom_reset = wx.BitmapButton(
            statbox_parent_zoom, bitmap=wx.BitmapBundle(undo_bmp), name="butt_reset_zoom"
        )
        self.button_zoom_reset.SetToolTip(wx.ToolTip("Reset scaling & position to defaults"))
        self.button_zoom_reset.Bind(wx.EVT_BUTTON, self.onResetZoom)
        reset_row = wx.BoxSizer(wx.HORIZONTAL)
        reset_row.AddStretchSpacer()
        reset_row.Add(self.button_zoom_reset, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.sizer_setting_zoom.Add(reset_row, 0, wx.EXPAND | wx.BOTTOM, 3)

        # Add subsizers to the left column sizer
        self.sizer_settings_left.Add(self.radiobox_spanmode, 0, wx.EXPAND, 5)
        self.sizer_settings_left.Add(self.sizer_setting_slideshow, 0, wx.EXPAND, 5)
        self.sizer_settings_left.Add(self.sizer_setting_hotkey, 0, wx.EXPAND, 5)
        self.sizer_settings_left.Add(self.sizer_setting_zoom, 0, wx.EXPAND, 5)

    def _new_path_listctrl(self, multi_column, target_label="Display"):
        """A source list: with a display or group column for ``multi_column``, else a bare list."""
        if multi_column:
            path_listctrl = wx.ListCtrl(
                self.statbox_parent_paths, -1, style=wx.LC_REPORT | wx.BORDER_SIMPLE | wx.LC_SORT_ASCENDING
            )
            path_listctrl.InsertColumn(0, target_label, wx.LIST_FORMAT_RIGHT, width=100)
            path_listctrl.InsertColumn(1, "Source", width=400)
        else:
            path_listctrl = wx.ListCtrl(
                self.statbox_parent_paths, -1, style=wx.LC_REPORT | wx.BORDER_SIMPLE | wx.LC_NO_HEADER
            )
            path_listctrl.InsertColumn(0, "Source", width=500)
        path_listctrl.SetImageList(self.image_list, wx.IMAGE_LIST_SMALL)
        path_listctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.onWallpaperItemSelected)
        return path_listctrl

    def create_sizer_paths(self):
        self.sizer_setting_paths = wx.StaticBoxSizer(wx.VERTICAL, self, "Wallpaper paths")
        self.statbox_parent_paths = self.sizer_setting_paths.GetStaticBox()
        st_paths_info = wx.StaticText(
            self.statbox_parent_paths,
            -1,
            "Browse to add your wallpaper files or source folders here:",
        )
        self.path_listctrl = self._new_path_listctrl(self.span_mode == "multi")

        self.sizer_setting_paths.Add(st_paths_info, 0, wx.ALIGN_LEFT | wx.ALL, 5)
        self.sizer_setting_paths.Add(self.path_listctrl, 1, wx.CENTER | wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, 5)
        # Buttons
        self.sizer_setting_paths_buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.button_browse = wx.Button(self.statbox_parent_paths, label="Browse")
        self.button_remove_source = wx.Button(self.statbox_parent_paths, label="Remove selected source")
        self.button_browse.Bind(wx.EVT_BUTTON, self.onBrowsePaths)
        self.button_remove_source.Bind(wx.EVT_BUTTON, self.onRemoveSource)
        self.sizer_setting_paths_buttons.Add(self.button_browse, 0, wx.CENTER | wx.ALL, 5)
        self.sizer_setting_paths_buttons.Add(self.button_remove_source, 0, wx.CENTER | wx.ALL, 5)
        # add button sizer to parent paths sizer
        self.sizer_setting_paths.Add(self.sizer_setting_paths_buttons, 0, wx.CENTER | wx.EXPAND | wx.ALL, 0)

        self.sizer_settings_right.Add(
            self.sizer_setting_paths, 1, wx.CENTER | wx.EXPAND | wx.TOP | wx.LEFT | wx.RIGHT, 5
        )
        self.path_listctrl.InvalidateBestSize()

    def create_sizer_settings_advanced(self):
        """Create sizer for advanced spanning settings.

        Display-wide settings (diagonal sizes, bezels) live in the separate
        collapsible system band; this box holds only profile-scoped advanced
        adjustments (manual offsets, span groups, perspective selection).
        """
        self.sizer_setting_adv = wx.StaticBoxSizer(wx.VERTICAL, self, "Advanced wallpaper adjustment")
        help_bmp = wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_BUTTON, wx.Size(20, 20))

        # Offsets
        self.sizer_setting_offsets = wx.BoxSizer(wx.VERTICAL)
        statbox_parent_offsets = self
        self.cb_offsets = wx.CheckBox(statbox_parent_offsets, -1, "Apply manual offsets")
        self.cb_offsets.Bind(wx.EVT_CHECKBOX, self.onCheckboxOffsets)
        st_offsets = wx.StaticText(statbox_parent_offsets, -1, "Manual offsets in pixels (x,y=px,px):")
        st_offsets.Disable()
        self.sizer_setting_offsets.Add(self.cb_offsets, 0, wx.ALIGN_LEFT | wx.BOTTOM, 5)
        self.sizer_setting_offsets.Add(st_offsets, 0, wx.ALIGN_LEFT | wx.LEFT, 10)
        tc_list_sizer_offs = wx.WrapSizer(wx.HORIZONTAL)
        num_displays = len(self.staged.layout.displays)
        self.tc_list_offsets = [
            wx.TextCtrl(statbox_parent_offsets, -1, size=wx.Size(self.tc_width // 2, -1), style=wx.TE_RIGHT)
            for _ in range(num_displays)
        ]
        for idx, tc in enumerate(self.tc_list_offsets):
            st = wx.StaticText(statbox_parent_offsets, -1, f"{idx}:")
            tc_st_sizer = wx.BoxSizer(wx.HORIZONTAL)
            tc_st_sizer.Add(st, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.TOP | wx.BOTTOM, 5)
            tc_st_sizer.Add(tc, 0, wx.ALIGN_LEFT | wx.ALL, 5)
            tc_list_sizer_offs.Add(tc_st_sizer, 0, wx.ALIGN_LEFT | wx.ALL, 0)
            tc.SetValue("0,0")
            st.Disable()
            tc.Disable()
        self.sizer_setting_offsets.Add(tc_list_sizer_offs, 0, wx.ALIGN_LEFT | wx.LEFT, 5)

        # Span groups
        self.sizer_setting_spangroups = wx.BoxSizer(wx.VERTICAL)
        sizer_spangroups_cb = wx.BoxSizer(wx.HORIZONTAL)
        self.cb_spangroups = wx.CheckBox(self, -1, "Use multiple span areas")
        self.cb_spangroups.Bind(wx.EVT_CHECKBOX, self.onCheckboxSpanGroups)
        self.button_help_spang = wx.BitmapButton(self, bitmap=wx.BitmapBundle(help_bmp), name="butt_help_spang")
        self.button_help_spang.Bind(wx.EVT_BUTTON, self.onHelpSpanGroups)
        sizer_spangroups_cb.Add(self.cb_spangroups, 0, wx.ALIGN_LEFT | wx.LEFT, 5)
        sizer_spangroups_cb.AddStretchSpacer()
        sizer_spangroups_cb.Add(self.button_help_spang, 0, wx.RIGHT, 5)
        sizer_spangroups_data = wx.WrapSizer(wx.HORIZONTAL)
        self.ch_list_spangroups = [
            wx.ComboBox(self, -1, size=wx.Size(int(self.tc_width * 0.4), -1), style=wx.CB_READONLY)
            for _ in range(num_displays)
        ]
        for idx, ch in enumerate(self.ch_list_spangroups):
            st = wx.StaticText(self, -1, f"{idx}:")
            ch_st_sizer = wx.BoxSizer(wx.HORIZONTAL)
            ch_st_sizer.Add(st, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.TOP | wx.BOTTOM, 5)
            ch_st_sizer.Add(ch, 0, wx.ALIGN_LEFT | wx.ALL, 5)
            sizer_spangroups_data.Add(ch_st_sizer, 0, wx.ALIGN_LEFT | wx.ALL, 0)
            ch.SetItems([str(group) for group in range(idx + 1)])
            ch.SetSelection(0)
            st.Disable()
            ch.Disable()
        self.sizer_setting_spangroups.Add(sizer_spangroups_cb, 1, wx.EXPAND, 5)
        self.sizer_setting_spangroups.Add(sizer_spangroups_data, 0, wx.ALIGN_LEFT | wx.LEFT, 5)

        # Perspective profile
        self.sizer_setting_persp = wx.BoxSizer(wx.HORIZONTAL)
        st_perspprof = wx.StaticText(self, -1, "Perspective profile:")
        persp_choices = self._perspective_labels()
        self.ch_persp = wx.ComboBox(
            self,
            -1,
            name="PerspChoice",
            size=wx.Size(165, -1),
            choices=persp_choices,
            style=wx.CB_READONLY,
        )
        self.sizer_setting_persp.Add(st_perspprof, 0, wx.ALIGN_LEFT | wx.ALL | wx.ALIGN_CENTER_VERTICAL, 0)
        self.sizer_setting_persp.Add(self.ch_persp, 0, wx.ALIGN_LEFT | wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)

        # Add setting subsizers to the adv settings sizer
        self.sizer_setting_adv.Add(self.sizer_setting_offsets, 0, wx.CENTER | wx.EXPAND | wx.ALL, 5)
        self.sizer_setting_adv.Add(self.sizer_setting_spangroups, 0, wx.CENTER | wx.EXPAND | wx.ALL, 5)
        self.sizer_setting_adv.Add(self.sizer_setting_persp, 0, wx.CENTER | wx.EXPAND | wx.ALL, 5)

    def create_sizer_bottom_buttonrow(self):
        self.button_help = wx.Button(self, label="Help")
        self.button_align_test = wx.Button(self, label="Align Test")
        self.button_perspectives = wx.Button(self, label="Perspectives")
        self.button_apply = wx.Button(self, label="Apply")
        self.button_close = wx.Button(self, label="Close")

        self.button_apply.Bind(wx.EVT_BUTTON, self.onApply)
        self.button_align_test.Bind(wx.EVT_BUTTON, self.onAlignTest)
        self.button_perspectives.Bind(wx.EVT_BUTTON, self.onPerspectives)
        self.button_help.Bind(wx.EVT_BUTTON, self.onHelp)
        self.button_close.Bind(wx.EVT_BUTTON, self.onClose)

        self.sizer_bottom_buttonrow.Add(self.button_help, 0, wx.ALIGN_LEFT | wx.ALL, 5)
        self.sizer_bottom_buttonrow.Add(self.button_align_test, 0, wx.ALIGN_LEFT | wx.ALL, 5)
        self.sizer_bottom_buttonrow.Hide(self.button_align_test)
        self.sizer_bottom_buttonrow.Add(self.button_perspectives, 0, wx.ALIGN_LEFT | wx.ALL, 5)
        self.sizer_bottom_buttonrow.Hide(self.button_perspectives)
        self.sizer_bottom_buttonrow.Layout()
        self.sizer_bottom_buttonrow.AddStretchSpacer()
        self.sizer_bottom_buttonrow.Add(self.button_apply, 0, wx.ALL, 5)
        self.sizer_bottom_buttonrow.Add(self.button_close, 0, wx.ALL, 5)

    #
    # Profile loading and display methods
    #
    def populate_fields(self, stored):
        """Populates config dialog fields with a saved profile's settings."""
        self._loading = True
        profile = stored.profile
        self.loaded_profile = stored
        shown = form.form_from(profile, self.staged.layout)
        self._write_form(shown)
        self.wpprev_pnl.zoom = profile.zoom
        self.wpprev_pnl.offset = profile.pan

        # Update wallpaper preview from selected profile
        display_data = self._display_areas()
        # Preview the store's current record: its selection follows the slideshow.
        self.wpprev_pnl.preview_wallpaper(
            (self.store.get(stored.profile_id) or stored).selection.current(),
            self.span_mode,
            display_data,
            self.preview_spangroups(),
        )
        self.wpprev_pnl.layout_editor.toggle_buttons(show_config=self.span_mode == "advanced", in_config=False)

        # Loaded data is the new clean baseline. Slideshow normalization in
        # parse_form means the later (posted) checkbox events produce
        # the same serialization, so this stays clean without a deferred call.
        self._loading = False
        self._set_clean_baseline()

    def _write_form(self, shown: form.ProfileForm):
        """Show ``shown`` in the fields."""
        self.tc_name.ChangeValue(shown.name)

        self.span_mode = shown.span_mode
        self.radiobox_spanmode.SetSelection(SPAN_MODES.index(self.span_mode))

        if shown.slideshow:
            self.cb_slideshow.SetValue(True)
            wx.PostEvent(self.cb_slideshow, wx.CommandEvent(commandEventType=wx.EVT_CHECKBOX.typeId))
            self.tc_sshow_delay.ChangeValue(shown.delay_minutes)
            if shown.sort_label is None:
                self.ch_sshow_sort.SetSelection(wx.NOT_FOUND)
            else:
                self.ch_sshow_sort.SetSelection(list(form.SORT_LABELS.values()).index(shown.sort_label))
        else:
            self.cb_slideshow.SetValue(False)
            wx.PostEvent(self.cb_slideshow, wx.CommandEvent(commandEventType=wx.EVT_CHECKBOX.typeId))
            self.tc_sshow_delay.Clear()
            self.ch_sshow_sort.SetSelection(wx.NOT_FOUND)

        if shown.hotkey_enabled:
            self.cb_hotkey.SetValue(True)
            self.tc_hotkey_bind.ChangeValue(shown.hotkey)
        else:
            self.cb_hotkey.SetValue(False)
            self.tc_hotkey_bind.Clear()
        wx.PostEvent(self.cb_hotkey, wx.CommandEvent(commandEventType=wx.EVT_CHECKBOX.typeId))

        # Advanced settings
        self.show_adv_setting_sizer(self.span_mode == "advanced")
        self.cb_offsets.SetValue(shown.offsets_applied)
        for tc, offstr in zip(self.tc_list_offsets, shown.offsets, strict=True):
            tc.SetValue(offstr)
        wx.PostEvent(self.cb_offsets, wx.CommandEvent(commandEventType=wx.EVT_CHECKBOX.typeId))
        persp_label = choice_label(shown.perspective)
        if persp_label:
            self.ch_persp.SetSelection(self.ch_persp.FindString(persp_label, False))
        else:
            self.ch_persp.SetSelection(0)
        self.cb_spangroups.SetValue(shown.spangroups_enabled)
        self.toggle_spangroup_widgets(shown.spangroups_enabled)
        for ch, group in zip(self.ch_list_spangroups, shown.spangroup_choices, strict=True):
            ch.SetSelection(group)

        # Paths displays: get number to show from profile.
        self.sources_to_listctrl(shown.sources)

        # Image scaling & position
        zoom_pct = shown.zoom_pct
        offx_pct, offy_pct = shown.pan_pct
        self.sld_zoom.SetValue(zoom_pct)
        self.sld_offx.SetValue(offx_pct)
        self.sld_offy.SetValue(offy_pct)
        self.st_zoom_val.SetLabel(f"{zoom_pct}%")
        self.st_offx_val.SetLabel(str(offx_pct))
        self.st_offy_val.SetLabel(str(offy_pct))

    def sources_to_listctrl(self, rows):
        """Show the source ``rows`` of a form: (display or group, path)."""
        multi_img = self.has_sources_per_target()
        self.refresh_path_listctrl(multi_img)
        for target, path in rows:
            self.append_to_listctrl([target, path] if multi_img else [path])

    #
    # Helper methods
    #
    def _current_serial(self):
        """The fingerprint of the current field state, for change comparison."""
        return form.fingerprint(self._read_form())

    def _read_form(self) -> form.ProfileForm:
        """What the fields hold now."""
        sort_sel = self.ch_sshow_sort.GetSelection()
        columns = self.path_listctrl.GetColumnCount()
        rows = tuple(
            (self.path_listctrl.GetItemText(idx, 0), self.path_listctrl.GetItemText(idx, 1))
            if columns == 2
            else ("", self.path_listctrl.GetItemText(idx, 0))
            for idx in range(self.path_listctrl.GetItemCount())
        )
        return form.ProfileForm(
            name=self.tc_name.GetLineText(0),
            span_mode=self.span_mode,
            slideshow=self.cb_slideshow.GetValue(),
            delay_minutes=self.tc_sshow_delay.GetLineText(0),
            # GetString(-1) raises in wx, so only read the dropdown when a sort order is chosen.
            sort_label=self.ch_sshow_sort.GetString(sort_sel) if sort_sel != wx.NOT_FOUND else None,
            hotkey_enabled=self.cb_hotkey.GetValue(),
            hotkey=self.tc_hotkey_bind.GetLineText(0),
            offsets_applied=self.cb_offsets.GetValue(),
            offsets=tuple(self._offset_fields()),
            spangroups_enabled=self.cb_spangroups.GetValue(),
            spangroup_choices=self._spangroup_choices(),
            perspective=self._selected_perspective(),
            zoom_pct=self.sld_zoom.GetValue(),
            pan_pct=(self.sld_offx.GetValue(), self.sld_offy.GetValue()),
            per_target_sources=columns != 1,
            sources=rows,
        )

    def _set_clean_baseline(self):
        """Record the current field state as the saved/clean baseline."""
        self._clean_serial = self._current_serial()
        self.button_save.Enable(False)
        self.button_revert.Enable(False)

    def _update_dirty_state(self):
        """Enable/disable Save and Revert based on unsaved profile changes."""
        if self._loading or self._clean_serial is None:
            return
        dirty = self._current_serial() != self._clean_serial
        if dirty != self.button_save.IsEnabled():
            self.button_save.Enable(dirty)
            self.button_revert.Enable(dirty)

    def _on_field_changed(self, event):
        """Panel-level handler: re-evaluate dirty state when a field changes."""
        event.Skip()
        self._update_dirty_state()

    def _display_areas(self):
        """The displays as the preview shows them."""
        return form.display_areas(self.staged.layout, self.span_mode)

    def _perspective_labels(self):
        """The choices of the perspective dropdown: the default, each saved perspective, and none."""
        return [choice_label(Default()), *self.staged.layout.perspective_names(), choice_label(Disabled())]

    def _selected_perspective(self):
        """The perspective the dropdown has chosen; the default if nothing is."""
        selection = self.ch_persp.GetSelection()
        if selection == wx.NOT_FOUND:
            return Default()
        return parse_choice(self.ch_persp.GetString(selection))

    def _read_offsets(self, parse) -> tuple[Offset, ...] | None:
        """``parse`` applied to the offset fields; tells the user and returns None if one can't be read."""
        try:
            return parse(self._offset_fields())
        except OffsetError as error:
            show_message_dialog(str(error), "Error")
            return None

    def _typed_offsets(self) -> tuple[Offset, ...] | None:
        """The offsets typed in the fields, applied or not; None if a field can't be read."""
        return self._read_offsets(parse_offsets)

    def _applied_offsets(self) -> tuple[Offset, ...] | None:
        """The manual offsets of the displays: none (0,0) unless they are applied, when the
        fields are read; None if a field can't be."""
        return self._read_offsets(partial(form.applied_offsets, self.cb_offsets.GetValue()))

    def _offset_fields(self):
        return [tc.GetLineText(0) for tc in self.tc_list_offsets]

    def refresh_layout_preview(self):
        """Show the staged display layout in the preview: after the display band changed
        it."""
        self.wpprev_pnl.update_display_data(self._display_areas(), self.span_mode)

    def _profile_choices(self):
        """The profile dropdown's entries: the saved profiles, then starting a new one."""
        self.list_of_profiles = self.store.profiles
        return [prof.profile.name for prof in self.list_of_profiles] + [NEW_PROFILE_LABEL]

    def update_choiceprofile(self):
        """Reload profile list into the choice box."""
        self.choice_profiles.SetItems(self._profile_choices())

    def sizer_toggle_children(self, sizer, bool_state, toggle_cb=False):
        for child in sizer.GetChildren():
            if child.IsSizer():
                self.sizer_toggle_children(child.GetSizer(), bool_state)
            else:
                widget = child.GetWindow()
                # Help/note buttons stay clickable even when their section is
                # disabled, so the explanation is always available to the user.
                if widget is not None and widget.GetName().startswith("butt_help"):
                    continue
                if isinstance(widget, (wx.TextCtrl, wx.StaticText, wx.Choice, wx.ComboBox, wx.Button)) or (
                    isinstance(widget, wx.CheckBox) and toggle_cb
                ):
                    widget.Enable(bool_state)

    def toggle_radio_and_profile_choice(self, enable):
        """Enable the span mode radiobox, the profile row and the display band's diagonal
        sizes, or disable them while display positions or bezels are being set."""
        self.radiobox_spanmode.Enable(enable)
        self.sizer_toggle_children(self.sizer_profiles, enable)
        self.display_band.enable_diagonals(enable)

    def show_adv_setting_sizer(self, show_bool):
        """Show/Hide the sizer for advanced spanning settings."""
        self.sizer_setting_sizers.Show(self.sizer_setting_adv, show=show_bool)
        self.display_band.toggle_bezel_buttons(enable_config_butt=True)
        # To only reveal sizer sit no frame resize
        self.path_listctrl.InvalidateBestSize()
        self.sizer_main.Layout()
        self.sizer_bottom_buttonrow.Show(self.button_align_test, show=show_bool)
        self.sizer_bottom_buttonrow.Show(self.button_perspectives, show=show_bool)
        self.sizer_bottom_buttonrow.Layout()

    def refresh_path_listctrl(self, multi_column, migrate_paths=False):
        if multi_column == self.multi_column_listc and migrate_paths:
            self.sizer_main.Layout()
        else:
            if migrate_paths and self.path_listctrl.GetItemCount():
                # warn that paths can't be migrated
                msg = (
                    "Wallpaper sources cannot be migrated between single span,"
                    " span groups, or multi image, continue?"
                    "\n"
                    "Saved sources are not affected until you overwrite."
                )
                res = show_message_dialog(msg, style="YES_NO")
                if not res:
                    # user canceled
                    return False
            self.path_listctrl.Destroy()
            self.image_list.RemoveAll()
            self.multi_column_listc = bool(multi_column)
            self.path_listctrl = self._new_path_listctrl(multi_column, "Group" if self.use_spangroups() else "Display")
            self.sizer_setting_paths.Insert(1, self.path_listctrl, 1, wx.CENTER | wx.EXPAND | wx.ALL, 5)
            self.path_listctrl.InvalidateBestSize()
            self.sizer_main.Layout()
        return True

    def _spangroup_choices(self):
        return tuple(ch.GetSelection() for ch in self.ch_list_spangroups)

    def preview_spangroups(self) -> tuple[tuple[int, ...], ...] | None:
        """The span groups for the preview: none unless there are at least two."""
        return form.preview_spangroups(self._spangroup_choices())

    def use_spangroups(self):
        """Check UI if spangroups are in use."""
        return form.uses_spangroups(self.span_mode, self.cb_spangroups.GetValue())

    def has_sources_per_target(self):
        """Whether the sources are listed for each display or span group."""
        return form.sources_per_target(self.span_mode, self.cb_spangroups.GetValue())

    def toggle_spangroup_widgets(self, enable):
        sizer = self.sizer_setting_spangroups
        self.sizer_toggle_children(sizer, enable)
        for ch in self.ch_list_spangroups:
            ch.Enable(enable)

    #
    # Event methods
    #
    def onZoomOffsetChange(self, event):
        """Live-update the preview as zoom/position sliders move."""
        zoom_pct = self.sld_zoom.GetValue()
        offx_pct = self.sld_offx.GetValue()
        offy_pct = self.sld_offy.GetValue()
        self.st_zoom_val.SetLabel(f"{zoom_pct}%")
        self.st_offx_val.SetLabel(str(offx_pct))
        self.st_offy_val.SetLabel(str(offy_pct))
        self.wpprev_pnl.update_zoom_offset(zoom_pct / 100.0, (offx_pct / 100.0, offy_pct / 100.0))
        self._update_dirty_state()

    def onResize(self, event):
        self.resized = True
        self.wpprev_pnl.refresh_preview()

    def onIdle(self, event):
        leftdown = wx.GetMouseState().LeftIsDown()
        update = bool(self.resized and not leftdown)
        if update:
            self.wpprev_pnl.full_refresh_preview(update, self.span_mode, spangroups=self.preview_spangroups())
            self.resized = False
        else:
            event.Skip()

    def onSpanRadio(self, event):
        previous = self.span_mode
        self.span_mode = SPAN_MODES[self.radiobox_spanmode.GetSelection()]
        if not self.refresh_path_listctrl(self.span_mode == "multi", migrate_paths=True):
            self.span_mode = previous
            self.radiobox_spanmode.SetSelection(SPAN_MODES.index(previous))
            return
        self.show_adv_setting_sizer(self.span_mode == "advanced")
        display_data = self._display_areas()
        spangroups = self.preview_spangroups() if self.cb_spangroups.GetValue() else None
        self.wpprev_pnl.update_display_data(display_data, self.span_mode, spangroups=spangroups)
        self.wpprev_pnl.layout_editor.toggle_buttons(show_config=self.span_mode == "advanced", in_config=False)
        self._update_dirty_state()

    def onCheckboxSlideshow(self, event):
        cb_state = self.cb_slideshow.GetValue()
        sizer = self.sizer_setting_slideshow
        self.sizer_toggle_children(sizer, cb_state)
        # Slideshow needs a sort order; default to Shuffle when enabling so the
        # dropdown isn't left empty (an unselected dropdown also broke the
        # dirty-state tracking that reads its current value).
        if cb_state and self.ch_sshow_sort.GetSelection() == wx.NOT_FOUND:
            self.ch_sshow_sort.SetSelection(0)
        # Zoom/pan is tuned to a single image's framing. In a slideshow the same
        # crop would be forced onto every (differently composed) image, so reset
        # the controls to defaults and disable them while slideshow is enabled.
        if cb_state:
            self.reset_zoom_offset()
        self.toggle_zoom_widgets(not cb_state)
        self._update_dirty_state()

    def reset_zoom_offset(self):
        """Return the zoom/position sliders to their no-op defaults."""
        self.sld_zoom.SetValue(100)
        self.sld_offx.SetValue(0)
        self.sld_offy.SetValue(0)
        self.onZoomOffsetChange(None)

    def onResetZoom(self, event):
        """Reset the image scaling & position to defaults, leaving the rest of the profile as is."""
        self.reset_zoom_offset()

    def toggle_zoom_widgets(self, enable):
        """Enable/disable the image scaling & position controls."""
        self.sizer_toggle_children(self.sizer_setting_zoom, enable)
        for sld in (self.sld_zoom, self.sld_offx, self.sld_offy):
            sld.Enable(enable)

    def onCheckboxHotkey(self, event):
        cb_state = self.cb_hotkey.GetValue()
        sizer = self.hotkey_bind_sizer
        self.sizer_toggle_children(sizer, cb_state)
        self._update_dirty_state()

    def onCheckboxOffsets(self, event):
        cb_state = self.cb_offsets.GetValue()
        sizer = self.sizer_setting_offsets
        self.sizer_toggle_children(sizer, cb_state)
        self._update_dirty_state()

    def onCheckboxSpanGroups(self, event):
        cb_state = self.cb_spangroups.GetValue()
        cont = self.refresh_path_listctrl(cb_state, migrate_paths=True)
        if not cont:
            self.cb_spangroups.SetValue(not cb_state)
            return
        self.toggle_spangroup_widgets(cb_state)
        self._update_dirty_state()

    #
    # ListCtrl methods
    #

    def append_to_listctrl(self, data_row):
        if self.has_sources_per_target() and len(data_row) == 2:
            img_id = self.add_to_imagelist(data_row[1])
            index = self.path_listctrl.InsertItem(self.path_listctrl.GetItemCount(), data_row[0], img_id)
            self.path_listctrl.SetItem(index, 1, data_row[1])
        elif self.span_mode != "multi" and len(data_row) == 1:
            img_id = self.add_to_imagelist(data_row[0])
            self.path_listctrl.InsertItem(self.path_listctrl.GetItemCount(), data_row[0], img_id)
        else:
            logger.info("Span mode: %s. Bad data_row: %s", self.span_mode, data_row)

    def add_to_imagelist(self, path):
        return self.image_list.Add(source_icon(path, self.tsize))

    def populate_lc_browse(self, pathslist):
        for path_item in pathslist:
            self.append_to_listctrl(path_item)
        self._update_dirty_state()

    #
    # Top level button definitions
    #
    def onWallpaperItemSelected(self, event):
        """Preview the selected wallpaper image in the preview panel."""
        item_idx = event.GetIndex()
        columns = self.path_listctrl.GetColumnCount()
        if columns == 2:
            path = self.path_listctrl.GetItemText(item_idx, 1)
        else:
            path = self.path_listctrl.GetItemText(item_idx, 0)

        if not path:
            return

        # Resolve folder to first image inside it
        preview_file = first_image(path)

        if not preview_file:
            return

        display_data = self._display_areas()
        self.wpprev_pnl.preview_wallpaper([preview_file], self.span_mode, display_data, self.preview_spangroups())

    @property
    def settings(self):
        """The general settings as they are now, whichever window saved them."""
        return self._get_settings()

    def adopt_perspectives(self, saved):
        """Use the perspective choice of the layout ``saved``: the preview holds this layout."""
        self.staged.layout = self.staged.layout.with_perspectives_of(saved)

    def onBrowsePaths(self, event):
        """Opens the pick paths dialog."""
        if self.use_spangroups():
            num_wallpaper_area = len(form.spangroups_of(self._spangroup_choices()))
        else:
            num_wallpaper_area = len(self.staged.layout.displays)
        dlg = BrowsePaths(
            self,
            self.has_sources_per_target(),
            self.settings.browse_default_dir,
            lambda path: self.update_settings(replace(self.settings, browse_default_dir=path)),
            num_wallpaper_area,
            "Group" if self.use_spangroups() else "Display",
        )
        if dlg.ShowModal() == wx.ID_OK:
            self.populate_lc_browse(dlg.path_list_data)
        dlg.Destroy()

    def onRemoveSource(self, event):
        """Removes selection from wallpaper source ListCtrl."""
        item = self.path_listctrl.GetFocusedItem()
        if item != -1:
            self.path_listctrl.DeleteItem(item)
            self._update_dirty_state()

    def onClose(self, event):
        """Closes the profile config panel."""
        self.frame.Close(True)

    def onSelect(self, event):
        """Acts once a profile is picked in the dropdown menu."""
        if event.GetEventObject().GetName() == "ProfileChoice":
            if event.GetString() == NEW_PROFILE_LABEL:
                self.onCreateNewProfile(event)
            else:
                self.populate_fields(self.list_of_profiles[event.GetSelection()])

    def onRevert(self, event):
        """Discards unsaved changes and loads the saved profile from disk again, with any
        changes made to its file outside the editor."""
        selection = self.choice_profiles.GetSelection()
        name = self.choice_profiles.GetString(selection) if selection != wx.NOT_FOUND else ""
        profile = revert_profile(name, store=self.store, session=self.session)
        if profile is not None:
            self.update_choiceprofile()
            self.choice_profiles.SetSelection(self.choice_profiles.FindString(profile.profile.name))
            self.populate_fields(profile)
            return
        # No saved profile to revert to: reset to an empty new profile.
        self.onCreateNewProfile(None)

    def onApply(self, event):
        """Render the current edits as a one-off preview without saving.

        The wallpaper is set using the settings exactly as shown in the dialog,
        but the stored ``.profile`` on disk and the daemon's active/running
        profile are left untouched. Use Save to persist the changes.
        """
        draft = form.prepare_draft(self._read_form(), self._focused_path(), self.loaded_profile)
        if isinstance(draft, Problems):
            self._show_problems(draft)
            return
        wx.BeginBusyCursor()
        # The staged layout, so unsaved display settings — bezels, sizes, positions — are
        # reflected; it is a value, so the worker thread renders exactly what is staged now.
        show_draft(
            draft,
            loaded=self.loaded_profile,
            layout=self.staged.layout,
            session=self.session,
            post=wx.CallAfter,
            on_shown=draft_shown,
        )

    def _show_problems(self, problems: Problems):
        """Tell the user what keeps the profile from being saved or applied."""
        show_message_dialog("\n\n".join(problems.messages), "Error")

    def _focused_path(self):
        """The path of the focused item of the wallpaper list, if any."""
        item_idx = self.path_listctrl.GetFocusedItem()
        if item_idx == -1:
            return None
        columns = self.path_listctrl.GetColumnCount()
        return self.path_listctrl.GetItemText(item_idx, 1 if columns == 2 else 0)

    def onSave(self, event):
        """Saves the profile the fields describe, if it is valid."""
        with wx.BusyCursor():
            current = self._read_form()
            result = save_profile(
                current,
                focused_path=self._focused_path(),
                loaded=self.loaded_profile,
                store=self.store,
                session=self.session,
                rebind_hotkey=self._rebind_hotkey,
            )
            if isinstance(result, Problems):
                self._show_problems(result)
                return
            self.update_choiceprofile()
            self.choice_profiles.SetSelection(self.choice_profiles.FindString(current.name))
            # The editor goes on with the store's record of the saved profile.
            self.loaded_profile = result.stored
            self.wpprev_pnl.preview_wallpaper(
                result.stored.selection.current(),
                self.span_mode,
                self._display_areas(),
                form.applied_spangroups(current),
            )
            self.list_of_profiles = self.store.profiles
            self._set_clean_baseline()

    def onCreateNewProfile(self, event):
        """Empties the wallpaper profile config fields."""
        self._loading = True
        self.loaded_profile = None
        self.choice_profiles.SetSelection(self.choice_profiles.FindString(NEW_PROFILE_LABEL))

        self.refresh_path_listctrl(False, migrate_paths=False)

        self._write_form(form.blank_form(self.staged.layout))
        self.onSpanRadio(None)

        # refresh wallpaper preview back to black previews
        self.wpprev_pnl.draw_displays()
        self.Refresh()
        self.Update()

        # A fresh (empty) profile starts clean.
        self._loading = False
        self._set_clean_baseline()

    def onDeleteProfile(self, event):
        """Deletes the currently selected profile after getting confirmation."""
        selection = self.choice_profiles.GetSelection()
        selected_name = self.choice_profiles.GetString(selection) if selection != wx.NOT_FOUND else ""
        profile = saved_profile(self.store, selected_name)
        if profile is None:
            show_message_dialog("Selected profile is not saved.", "Error")
            return
        if not show_message_dialog(
            f"Do you want to delete profile: {selected_name}?", "Confirm Delete", style="YES_NO"
        ):
            return
        problems = delete_profile(profile, store=self.store, session=self.session, rebind_hotkey=self._rebind_hotkey)
        if problems is not None:
            self._show_problems(problems)
            return
        self.update_choiceprofile()
        self.onCreateNewProfile(None)

    def onAlignTest(self, event):
        """Align test, takes alignment settings from open profile and sets a test image wp."""
        # Use the settings currently written out in the fields!
        testimage = [str(resource("test.png"))]
        if not is_file(testimage[0]):
            show_message_dialog(f"Test image not found in {testimage}.", "Error")
            return
        offsets = self._typed_offsets()
        if offsets is None:
            return

        perspective = self._selected_perspective()

        wx.BeginBusyCursor()
        # With the saved display settings, detected again before the draft is rendered.
        self.refresh_displays()
        profile = profile_file.draft(testimage, spanmode="advanced", perspective=perspective, offsets=offsets)
        self.session.apply_draft(profile, testimage, on_done=lambda problem: wx.CallAfter(draft_shown, problem))

    def onPerspectives(self, event):
        """Open perspective configuration dialog."""
        typed_offsets = self._typed_offsets()
        if typed_offsets is None:
            return
        applied_offsets = typed_offsets if self.cb_offsets.GetValue() else len(typed_offsets) * ((0, 0),)
        dlg = PerspectiveConfig(self, applied_offsets, typed_offsets)
        dlg.ShowModal()
        dlg.Destroy()
        # Update perspective profile choices
        current_label = choice_label(self._selected_perspective())
        persp_choices = self._perspective_labels()
        self.ch_persp.SetItems(persp_choices)
        if current_label in persp_choices:
            self.ch_persp.SetSelection(self.ch_persp.FindString(current_label))
        else:
            # The form had picked a perspective that no longer exists; fall
            # back to default and surface it as an unsaved change rather than
            # silently writing to disk (Save is the only thing that persists).
            self.ch_persp.SetSelection(0)
        # SetItems clears the selection and fires text events that judge the form
        # while it has none, so the restored one is judged here.
        self._update_dirty_state()

    def onHelp(self, event):
        """Open help dialog."""
        HelpFrame(self._get_settings, self.update_settings, self)

    def show_preview_help(self, text, button):
        """Popup the preview's help below button, with the size the wallpapers should have
        for the current settings, unless each display has its own image."""
        layout = self.staged.layout
        match self.span_mode:
            case "multi":
                quality_text = None
            case "single":
                quality_text = image_quality_advice(layout.desktop_size())
            case "advanced":
                offsets = self._applied_offsets()
                if offsets is None:
                    return
                perspective = layout.perspective_for(self._selected_perspective()) if layout.use_perspective else None
                quality_text = image_quality_advice(canvas.source_size(layout.ppi_norm_crops(offsets), perspective))
            case _:
                assert_never(self.span_mode)
        show_help_popup(self.wpprev_pnl, text, button, quality_text)

    def onHelpHotkey(self, evt):
        """Popup hotkey help."""
        text = (
            "Bind a hotkey to start this profile. Choose max 3\n"
            "modifiers out of: control, alt, shift, super(=win).\n"
            "Example: control+super+x"
        )
        show_help_popup(self, text, evt.GetEventObject())

    def onHelpSpanGroups(self, evt):
        """Popup span group config help."""
        text = (
            "You can span wallpapers on groups of displays.\n"
            "To configure this, select a group number for\n"
            "each display. By default each display belongs\n"
            "to the first group, group 0.\n"
            "Once you have selected your groups, add at least\n"
            "one wallpaper source for each group."
        )
        show_help_popup(self, text, evt.GetEventObject())
