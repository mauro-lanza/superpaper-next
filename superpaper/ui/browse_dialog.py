"""Choosing the image files and folders a profile shows, and their icons in source lists."""

import wx  # ty:ignore[unresolved-import]

from superpaper.render import source_icon_image
from superpaper.selection import is_folder


def source_icon(path, size):
    """Return the list icon of an image source: a folder, a thumbnail, or "missing image".

    A source can be unavailable (an unmounted drive) or unreadable; that must not stop
    the editor from listing it.
    """
    if is_folder(path):
        return wx.ArtProvider.GetBitmap(wx.ART_FOLDER, wx.ART_TOOLBAR, wx.Size(*size))
    thumbnail = source_icon_image(path, size)
    if thumbnail is None:
        return wx.ArtProvider.GetBitmap(wx.ART_MISSING_IMAGE, wx.ART_TOOLBAR, wx.Size(*size))
    width, height = thumbnail.size
    image = wx.Image(width, height)
    image.SetData(thumbnail.tobytes())
    pos = (round((size[0] - width) / 2), round((size[1] - height) / 2))
    return image.Resize(wx.Size(*size), wx.Point(pos)).ConvertToBitmap()


class BrowsePaths(wx.Dialog):
    """Path picker dialog class."""

    def __init__(self, parent, use_multi_image, defdir, update_settings, num_span_groups=None):
        wx.Dialog.__init__(
            self,
            parent,
            -1,
            "Choose image source directories or image files",
            size=wx.Size(250, 250),
            style=wx.RESIZE_BORDER | wx.DEFAULT_DIALOG_STYLE,
        )
        BMP_SIZE = 32
        self.tsize = (BMP_SIZE, BMP_SIZE)
        self.il = wx.ImageList(BMP_SIZE, BMP_SIZE)

        if num_span_groups:
            self.num_wallpaper_area = num_span_groups
            self.wp_area_name = "Group"
        else:
            self.num_wallpaper_area = len(parent.staged.layout.displays)
            self.wp_area_name = "Display"
        self.use_multi_image = use_multi_image
        self.path_list_data = []
        self.paths = []
        sizer_main = wx.BoxSizer(wx.VERTICAL)
        sizer_browse = wx.BoxSizer(wx.VERTICAL)
        self.sizer_paths_list = wx.BoxSizer(wx.VERTICAL)
        sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)

        self.defdir = defdir
        self._update_settings = update_settings  # remembers the default directory
        self.dir3 = wx.GenericDirCtrl(
            self,
            -1,
            dir=self.defdir,
            filter="Image files (*.jpg, *.png)|*.jpg;*.jpeg;*.png;*.bmp;*.gif;*.tiff;*.webp",
        )
        sizer_browse.Add(self.dir3, 1, wx.CENTER | wx.ALL | wx.EXPAND, 5)
        self.cb_showhidden = wx.CheckBox(self, -1, "Show hidden files")
        self.cb_showhidden.Bind(wx.EVT_CHECKBOX, self.onCheckboxShowHidden)
        sizer_browse.Add(self.cb_showhidden, 0, wx.ALIGN_LEFT | wx.ALL, 5)

        st_paths_list = wx.StaticText(self, -1, "Selected wallpaper source directories and files:")
        self.sizer_paths_list.Add(st_paths_list, 0, wx.ALIGN_LEFT | wx.ALL, 5)
        self.create_paths_listctrl(self.use_multi_image)

        sizer_radio = wx.BoxSizer(wx.VERTICAL)
        if self.use_multi_image:
            radio_choices_displays = [self.wp_area_name + f" {i}" for i in range(self.num_wallpaper_area)]
            self.radiobox_displays = wx.RadioBox(
                self,
                wx.ID_ANY,
                label="Select display to add sources to",
                choices=radio_choices_displays,
                style=wx.RA_HORIZONTAL,
            )
            sizer_radio.Add(self.radiobox_displays, 0, wx.CENTER | wx.ALL | wx.EXPAND, 5)

        # Buttons
        self.button_add = wx.Button(self, label="Add source")
        self.button_remove = wx.Button(self, label="Remove source")
        self.button_defdir = wx.Button(self, label="Save as browse start")
        self.button_clrdefdir = wx.Button(self, label="Clear browse start")
        self.button_ok = wx.Button(self, label="Ok")
        self.button_cancel = wx.Button(self, label="Cancel")

        self.button_add.Bind(wx.EVT_BUTTON, self.onAdd)
        self.button_remove.Bind(wx.EVT_BUTTON, self.onRemove)
        self.button_defdir.Bind(wx.EVT_BUTTON, self.onDefDir)
        self.button_clrdefdir.Bind(wx.EVT_BUTTON, self.onClrDefDir)
        self.button_ok.Bind(wx.EVT_BUTTON, self.onOk)
        self.button_cancel.Bind(wx.EVT_BUTTON, self.onCancel)

        sizer_buttons.Add(self.button_add, 0, wx.CENTER | wx.ALL, 5)
        sizer_buttons.Add(self.button_remove, 0, wx.CENTER | wx.ALL, 5)
        sizer_buttons.AddStretchSpacer()
        sizer_buttons.Add(self.button_defdir, 0, wx.CENTER | wx.ALL, 5)
        sizer_buttons.Add(self.button_clrdefdir, 0, wx.CENTER | wx.ALL, 5)
        sizer_buttons.AddStretchSpacer()
        sizer_buttons.Add(self.button_ok, 0, wx.CENTER | wx.ALL, 5)
        sizer_buttons.Add(self.button_cancel, 0, wx.CENTER | wx.ALL, 5)

        sizer_main.Add(sizer_browse, 1, wx.ALL | wx.EXPAND)
        sizer_main.Add(self.sizer_paths_list, 0, wx.ALL | wx.EXPAND)
        if self.use_multi_image:
            sizer_main.Add(sizer_radio, 0, wx.ALL | wx.EXPAND, 5)
        sizer_main.Add(sizer_buttons, 0, wx.ALL | wx.EXPAND, 5)
        self.SetSizerAndFit(sizer_main)
        self.SetSize(wx.Size(-1, 650))

    def create_paths_listctrl(self, use_multi_image):
        if use_multi_image:
            self.paths_listctrl = wx.ListCtrl(
                self,
                -1,
                size=wx.Size(-1, -1),
                style=wx.LC_REPORT | wx.BORDER_SIMPLE | wx.LC_SORT_ASCENDING,
            )
            self.paths_listctrl.InsertColumn(0, self.wp_area_name, wx.LIST_FORMAT_RIGHT, width=100)
            self.paths_listctrl.InsertColumn(1, "Source", width=620)
        else:
            # show simpler listing without header if only one wallpaper target
            self.paths_listctrl = wx.ListCtrl(
                self,
                -1,
                size=wx.Size(-1, -1),
                style=wx.LC_REPORT | wx.BORDER_SIMPLE | wx.LC_NO_HEADER,
            )
            self.paths_listctrl.InsertColumn(0, "Source", width=720)

        # Add the item list to the control
        self.paths_listctrl.SetImageList(self.il, wx.IMAGE_LIST_SMALL)

        self.sizer_paths_list.Add(self.paths_listctrl, 1, wx.CENTER | wx.ALL | wx.EXPAND, 5)

    def append_to_listctrl(self, data_row):
        if self.use_multi_image:
            img_id = self.add_to_imagelist(data_row[1])
            index = self.paths_listctrl.InsertItem(self.paths_listctrl.GetItemCount(), data_row[0], img_id)
            self.paths_listctrl.SetItem(index, 1, data_row[1])
        else:
            img_id = self.add_to_imagelist(data_row[0])
            self.paths_listctrl.InsertItem(self.paths_listctrl.GetItemCount(), data_row[0], img_id)

    def add_to_imagelist(self, path):
        return self.il.Add(source_icon(path, self.tsize))

    #
    # BUTTON methods
    #

    def onAdd(self, event):
        """Adds selected path to export field."""
        sel_path = self.dir3.GetPath()
        if self.use_multi_image:
            # Extra column in advanced mode
            disp_id = str(self.radiobox_displays.GetSelection())
            self.append_to_listctrl([disp_id, sel_path])
        else:
            self.append_to_listctrl([sel_path])

    def onRemove(self, event):
        """Removes last appended path from export field."""
        item = self.paths_listctrl.GetFocusedItem()
        if item != -1:
            self.paths_listctrl.DeleteItem(item)

    def onDefDir(self, event):
        sel_path = self.dir3.GetPath()
        if is_folder(sel_path):
            self.defdir = sel_path
            self._update_settings(browse_default_dir=self.defdir.strip())
        else:
            pass

    def onClrDefDir(self, event):
        self.defdir = ""
        self._update_settings(browse_default_dir="")

    def onCheckboxShowHidden(self, event):
        self.dir3.ShowHidden(self.cb_showhidden.GetValue())

    def onOk(self, event):
        """Exports path to parent Profile Config dialog."""
        columns = self.paths_listctrl.GetColumnCount()
        for idx in range(self.paths_listctrl.GetItemCount()):
            item_dat = []
            for col in range(columns):
                item_dat.append(self.paths_listctrl.GetItemText(idx, col))
            self.path_list_data.append(item_dat)
        # if listctrl is empty, onOk maybe could pass on the selected item? or disable OK if list is empty?
        self.EndModal(wx.ID_OK)

    def onCancel(self, event):
        """Closes path picker, throwing away selections."""
        self.Destroy()
