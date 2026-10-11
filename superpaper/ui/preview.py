"""The editor's preview of the displays and the wallpaper on them, where display
positions and bezels are also set."""

from typing import Literal, overload

import wx  # pyright: ignore[reportMissingImports]  # ty:ignore[unresolved-import]
from PIL import ImageEnhance

import superpaper.sp_logging as sp_logging
from superpaper.paths import resource
from superpaper.render import SourceImageError, open_source_image, resize_to_fill
from superpaper.ui.help import HelpPopup
from superpaper.ui.positions_dialog import DisplayPositionEntry


class WallpaperPreviewPanel(wx.Panel):
    """
    Wallpaper & monitor preview panel.

    Previews wallpaper settings as applied to the input image.
    In the advanced mode allows the user to enter their monitor
    setup, which will then be saved into a file as a monitor
    configuration. Method looks up saved setups to see if one
    exists that matches the given resolutions, offsets and sizes.
    """

    def __init__(self, parent, display_sys, image_list=None, use_ppi_px=False, use_multi_image=False):
        self.preview_size = (1080, 400)
        wx.Panel.__init__(self, parent, size=wx.Size(*self.preview_size))
        self.frame = parent

        # Buttons
        self.config_mode = False
        self.bezel_conifg_mode = False
        self.create_buttons(use_ppi_px)

        # Colour definitions
        self.clr_prw_mntr = wx.Colour(0, 0, 0, alpha=wx.ALPHA_OPAQUE)
        self.clr_prw_bkg = wx.Colour(30, 30, 30, alpha=wx.ALPHA_OPAQUE)
        self.SetBackgroundColour(self.clr_prw_bkg)

        # Display data and sizes
        self.display_sys = display_sys
        self.display_data = self.display_sys.get_disp_list()
        self.dtop_canvas_px = self.get_canvas(self.display_data)
        self.dtop_canvas_relsz, self.dtop_canvas_pos, scaling_fac = self.fit_canvas_wrkarea(self.dtop_canvas_px)
        self.display_rel_sizes = self.displays_on_canvas(self.display_data, self.dtop_canvas_pos, scaling_fac)

        # bitmaps to be shown
        self.use_multi_image = use_multi_image
        self.current_preview_images = []
        self.preview_img_list = []
        self.bmp_list = []

        # Image zoom & positioning (whole-viewport, applied in resize_to_fill)
        self.zoom = 1.0
        self.offset = (0.0, 0.0)
        self._last_use_ppi = use_ppi_px
        self._last_use_multi = use_multi_image
        self._last_spangroups = None

        # Draw preview
        self.draw_displays()

        # Create bezel buttons for displays in preview
        self.bez_buttons = []
        self.create_bezel_buttons()

        self.draggable_shapes = []
        self.positions_dragged = False
        self.Bind(wx.EVT_PAINT, self.OnPaint)

    #
    # UI drawing methods
    #
    def draw_displays(self, use_ppi_px=False, use_multi_image=False):
        # draw canvas
        bmp_canv = wx.Bitmap.FromRGBA(
            self.dtop_canvas_relsz[0], self.dtop_canvas_relsz[1], red=0, green=0, blue=0, alpha=255
        )
        if not self.preview_img_list:
            # preview StaticBitmaps don't exist yet
            self.bmp_list.append(bmp_canv)
            self.st_bmp_canvas = wx.StaticBitmap(self, wx.ID_ANY, wx.BitmapBundle(bmp_canv))
            self.st_bmp_canvas.SetPosition(wx.Point(self.dtop_canvas_pos))
            self.st_bmp_canvas.Hide()

            # draw monitor previews
            for disp in self.display_rel_sizes:
                size = disp[0]
                offs = disp[1]
                bmp = wx.Bitmap.FromRGBA(size[0], size[1], red=0, green=0, blue=0, alpha=255)
                self.bmp_list.append(bmp)
                st_bmp = wx.StaticBitmap(self, wx.ID_ANY, wx.BitmapBundle(bmp))
                st_bmp.Hide()
                # st_bmp.SetScaleMode(wx.Scale_AspectFill)  # New in wxpython 4.1
                st_bmp.SetPosition(offs)
                self.preview_img_list.append(st_bmp)
        else:
            # previews exist and should be blanked
            self.current_preview_images = []  # drop chached image list

            self.st_bmp_canvas.SetBitmap(wx.BitmapBundle(bmp_canv))
            self.st_bmp_canvas.SetPosition(wx.Point(self.dtop_canvas_pos))
            # self.st_bmp_canvas.Hide()

            # blank monitor previews
            for disp, st_bmp in zip(self.display_rel_sizes, self.preview_img_list):
                size = disp[0]
                offs = disp[1]
                bmp = wx.Bitmap.FromRGBA(size[0], size[1], red=0, green=0, blue=0, alpha=255)
                st_bmp.SetBitmap(bmp)
                st_bmp.SetPosition(offs)
                # st_bmp.Hide()
        self.draw_monitor_numbers(use_ppi_px)
        self.Refresh()

    def resize_displays(self, use_ppi_px):
        if use_ppi_px:
            for disp, img_sz, bez_szs, st_bmp in zip(
                self.display_rel_sizes, self.img_rel_sizes, self.bz_rel_sizes, self.preview_img_list
            ):
                size, offs = disp
                bmp = wx.Bitmap.FromRGBA(img_sz[0], img_sz[1], red=0, green=0, blue=0, alpha=255)
                bmp_w_bez = self.bezels_to_bitmap(bmp, size, bez_szs)
                st_bmp.SetSize(size)
                st_bmp.SetPosition(offs)
                st_bmp.SetBitmap(bmp_w_bez)
        else:
            for disp, st_bmp in zip(self.display_rel_sizes, self.preview_img_list):
                size = disp[0]
                offs = disp[1]
                bmp = wx.Bitmap.FromRGBA(size[0], size[1], red=0, green=0, blue=0, alpha=255)
                st_bmp.SetBitmap(bmp)
                st_bmp.SetPosition(offs)
                st_bmp.SetSize(size)
        self.draw_monitor_numbers(use_ppi_px)

    def draw_monitor_numbers(self, use_ppi_px):
        font = wx.Font(24, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        font_clr = wx.Colour(60, 60, 60, alpha=wx.ALPHA_OPAQUE)

        for st_bmp in self.preview_img_list:
            bmp = st_bmp.GetBitmap()
            dc = wx.MemoryDC(bmp)
            text = str(self.preview_img_list.index(st_bmp))
            dc.SetTextForeground(font_clr)
            dc.SetFont(font)
            dc.DrawText(text, 5, 5)
            del dc
            st_bmp.SetBitmap(bmp)

        if use_ppi_px:
            self.draw_monitor_sizes()

    def draw_monitor_sizes(self):
        font = wx.Font(24, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_LIGHT)
        font_clr = wx.Colour(60, 60, 60, alpha=wx.ALPHA_OPAQUE)

        for st_bmp, img_sz, dsp in zip(self.preview_img_list, self.img_rel_sizes, self.display_sys.disp_list):
            bmp = st_bmp.GetBitmap()
            dc = wx.MemoryDC(bmp)
            text = str(dsp.diagonal_size()[1]) + '"'
            dc.SetTextForeground(font_clr)
            dc.SetFont(font)
            # bmp_w, bmp_h = dc.GetSize()
            bmp_w, bmp_h = img_sz
            text_w, text_h = dc.GetTextExtent(text)
            pos_w = bmp_w - text_w - 5
            pos_h = 5
            dc.DrawText(text, pos_w, pos_h)
            del dc
            st_bmp.SetBitmap(bmp)

    def refresh_preview(self, use_ppi_px=False, force_refresh=False):
        if force_refresh or (not self.config_mode or not self.bezel_conifg_mode):
            self.dtop_canvas_px = self.get_canvas(self.display_data, use_ppi_px)
            self.dtop_canvas_relsz, self.dtop_canvas_pos, scaling_fac = self.fit_canvas_wrkarea(self.dtop_canvas_px)
            self.st_bmp_canvas.SetPosition(wx.Point(self.dtop_canvas_pos))
            self.st_bmp_canvas.SetSize(wx.Size(*self.dtop_canvas_relsz))

            if use_ppi_px:
                (self.display_rel_sizes, self.img_rel_sizes, self.bz_rel_sizes) = self.displays_on_canvas(
                    self.display_data, self.dtop_canvas_pos, scaling_fac, use_ppi_px
                )
            else:
                self.display_rel_sizes = self.displays_on_canvas(self.display_data, self.dtop_canvas_pos, scaling_fac)
            for disp, st_bmp in zip(self.display_rel_sizes, self.preview_img_list):
                size = disp[0]
                offs = disp[1]
                st_bmp.SetPosition(offs)
                st_bmp.SetSize(size)
        # if self.bezel_conifg_mode:
        # pass
        # self.st_bmp_canvas.Hide()

        self.move_buttons()
        self.move_bezel_buttons()

    def full_refresh_preview(self, is_resized, use_ppi_px, use_multi_image, spangroups=None):
        self.use_multi_image = use_multi_image
        if is_resized and not self.config_mode:
            dtop_canvas_relsz, dtop_canvas_pos, scaling_fac = self.fit_canvas_wrkarea(self.dtop_canvas_px)
            # if (self.current_preview_images and dtop_canvas_relsz is not self.dtop_canvas_relsz):
            if self.current_preview_images:
                self.preview_wallpaper(self.current_preview_images, use_ppi_px, use_multi_image, spangroups=spangroups)
                self.move_bezel_buttons()
                # self.st_bmp_canvas.Hide()
            else:
                self.refresh_preview(use_ppi_px)
                self.resize_displays(use_ppi_px)
                self.move_bezel_buttons()
                self.Refresh()
                # self.st_bmp_canvas.Hide()

    def preview_wallpaper(
        self,
        image_list,
        use_ppi_px=False,
        use_multi_image=False,
        display_data=None,
        spangroups=None,
    ):
        self.use_multi_image = use_multi_image
        if display_data:
            self.display_data = display_data
        self._last_use_ppi = use_ppi_px
        self._last_use_multi = use_multi_image
        self._last_spangroups = spangroups
        self.refresh_preview(use_ppi_px)
        self.current_preview_images = image_list
        if not image_list:
            # Nothing to show, e.g. the profile's images are on an unmounted drive.
            self.draw_displays(use_ppi_px)
            return

        def safe_sub_bitmap(bm, rect):
            if rect.GetBottom() >= bm.GetHeight():
                rect.SetBottom(bm.GetHeight() - 1)
            if rect.GetRight() >= bm.GetWidth():
                rect.SetRight(bm.GetWidth() - 1)
            return bm.GetSubBitmap(rect)

        if use_multi_image:
            while len(image_list) < len(self.preview_img_list):
                image_list.append(image_list[0])
            for img_nm, st_bmp in zip(image_list, self.preview_img_list):
                prev_sz = st_bmp.GetSize()
                st_bmp.SetBitmap(self.resize_and_bitmap(img_nm, prev_sz))
        elif use_ppi_px and spangroups:
            self.use_multi_image = True  # disables canvas drawing
            # for each group of displays, run span wallpaper preview
            for grp_id, img_nm in zip(spangroups, image_list):
                grp = spangroups[grp_id]
                display_rel_sizes = [self.display_rel_sizes[i] for i in grp]
                img_rel_sizes = [self.img_rel_sizes[i] for i in grp]
                bz_rel_sizes = [self.bz_rel_sizes[i] for i in grp]
                preview_img_list = [self.preview_img_list[i] for i in grp]

                canv_sz, canvas_pos = self.canvas_display_group(display_rel_sizes, (0, 0))
                bmp_clr, bmp_bw = self.resize_and_bitmap(img_nm, canv_sz, True)
                for disp, img_sz, bez_szs, st_bmp in zip(
                    display_rel_sizes, img_rel_sizes, bz_rel_sizes, preview_img_list
                ):
                    sz = disp[0]
                    pos = (disp[1][0] - canvas_pos[0], disp[1][1] - canvas_pos[1])
                    crop = safe_sub_bitmap(bmp_clr, wx.Rect(pos, img_sz))
                    crop_w_bez = self.bezels_to_bitmap(crop, sz, bez_szs)
                    st_bmp.SetBitmap(crop_w_bez)
        elif use_ppi_px and not spangroups:
            img = image_list[0]
            # set canvas to fit with keeping aspect the image, with dim/blur
            # and crop pieces to show on monitor previews unaltered.
            # With use_ppi_px any provided bezels will be drawn.
            canv_sz = self.st_bmp_canvas.GetSize()
            bmp_clr, bmp_bw = self.resize_and_bitmap(img, canv_sz, True)
            self.st_bmp_canvas.SetBitmap(wx.BitmapBundle(bmp_bw))
            # self.st_bmp_canvas.Show()

            canvas_pos = self.dtop_canvas_pos
            for disp, img_sz, bez_szs, st_bmp in zip(
                self.display_rel_sizes, self.img_rel_sizes, self.bz_rel_sizes, self.preview_img_list
            ):
                sz = disp[0]
                pos = (disp[1][0] - canvas_pos[0], disp[1][1] - canvas_pos[1])
                crop = safe_sub_bitmap(bmp_clr, wx.Rect(pos, img_sz))
                crop_w_bez = self.bezels_to_bitmap(crop, sz, bez_szs)
                st_bmp.SetBitmap(crop_w_bez)
                # st_bmp.Show()
        else:
            img = image_list[0]
            # set canvas to fit with keeping aspect the image, with dim/blur
            # and crop pieces to show on monitor previews unaltered.
            canv_sz = self.st_bmp_canvas.GetSize()
            bmp_clr, bmp_bw = self.resize_and_bitmap(img, canv_sz, True)
            self.st_bmp_canvas.SetBitmap(wx.BitmapBundle(bmp_bw))
            # self.st_bmp_canvas.Show()

            canvas_pos = self.dtop_canvas_pos
            for disp, st_bmp in zip(self.display_rel_sizes, self.preview_img_list):
                sz = disp[0]
                pos = (disp[1][0] - canvas_pos[0], disp[1][1] - canvas_pos[1])
                crop = safe_sub_bitmap(bmp_clr, wx.Rect(pos, sz))
                st_bmp.SetBitmap(crop)
                # st_bmp.Show()
        self.draw_monitor_numbers(use_ppi_px)
        self.Refresh()

    def update_zoom_offset(self, zoom, offset):
        """Re-render the current preview with new zoom & offset values."""
        self.zoom = zoom
        self.offset = offset
        if not self.current_preview_images:
            return
        self.preview_wallpaper(
            list(self.current_preview_images),
            self._last_use_ppi,
            self._last_use_multi,
            self.display_data,
            self._last_spangroups,
        )

    @overload
    def resize_and_bitmap(self, fname, size, enhance_color: Literal[False] = False) -> wx.Bitmap: ...
    @overload
    def resize_and_bitmap(self, fname, size, enhance_color: Literal[True]) -> tuple[wx.Bitmap, wx.Bitmap]: ...

    def resize_and_bitmap(self, fname, size, enhance_color=False):
        """Take filename of an image and resize and crop it to size."""
        try:
            # Opened as the renderer opens it, so the preview matches the result.
            pil = resize_to_fill(open_source_image(fname), size, quality="fast", zoom=self.zoom, offset=self.offset)
        except SourceImageError as error:  # unreadable, truncated, too large, or no longer there
            sp_logging.G_LOGGER.info("Cannot preview image '%s': %s", fname, error)
            black_bmp = wx.Bitmap.FromRGBA(size[0], size[1], red=0, green=0, blue=0, alpha=255)
            if enhance_color:
                return (black_bmp, black_bmp)
            return black_bmp
        img = wx.Image(pil.size[0], pil.size[1])
        img.SetData(pil.convert("RGB").tobytes())
        if enhance_color:
            converter = ImageEnhance.Color(pil)
            pilenh_bw = converter.enhance(0.25)
            brightns = ImageEnhance.Brightness(pilenh_bw)
            pilenh = brightns.enhance(0.45)
            imgenh = wx.Image(pil.size[0], pil.size[1])
            imgenh.SetData(pilenh.convert("RGB").tobytes())
            return (img.ConvertToBitmap(), imgenh.ConvertToBitmap())
        return img.ConvertToBitmap()

    def bezels_to_bitmap(self, bmp, disp_sz, bez_rects):
        """Add bezel rectangles ( right_bez , bottom_bez ) to given bitmap."""
        # sp_logging.G_LOGGER.info("bezels_to_bitmap: bez_rects: %s", bez_rects)
        right_bez, bottom_bez = bez_rects
        if right_bez == (0, 0) and bottom_bez == (0, 0):
            return bmp
        # bmp into wx.Image and new output
        img = bmp.ConvertToImage()
        img_sz = img.GetSize()
        img_out = wx.Image(disp_sz[0], disp_sz[1])
        img_out.Paste(img, 0, 0)

        # Add bezels sequentially to the Image
        # bottom bez
        if bottom_bez != (0, 0):
            b_bez_bmp = wx.Bitmap.FromRGBA(bottom_bez[0], bottom_bez[1], red=5, green=5, blue=5, alpha=100)
            b_bez_img = b_bez_bmp.ConvertToImage()
            img_out.Paste(b_bez_img, 0, img_sz[1])

        # right bez: is longer if bottom bez is present
        if right_bez != (0, 0):
            r_bez_bmp = wx.Bitmap.FromRGBA(right_bez[0], right_bez[1], red=5, green=5, blue=5, alpha=100)
            r_bez_img = r_bez_bmp.ConvertToImage()
            img_out.Paste(r_bez_img, img_sz[0], 0)

        # Convert Image back to wx.Bitmap
        return img_out.ConvertToBitmap()

    def update_display_data(self, display_data, use_ppi_px, use_multi_image, spangroups=None):
        self.display_data = display_data
        self.refresh_preview()
        self.full_refresh_preview(True, use_ppi_px, use_multi_image, spangroups=spangroups)

    #
    # Data analysis methods
    #
    def get_canvas(self, disp_data, use_ppi_px=False):
        """Returns a size tuple for the desktop are in pixels or millimeters."""
        if use_ppi_px:
            rightmost_edge = max(
                [disp.resolution[0] + disp.digital_offset[0] + disp.ppi_norm_bezels[0] for disp in disp_data]
            )
            bottommost_edge = max(
                [disp.resolution[1] + disp.digital_offset[1] + disp.ppi_norm_bezels[1] for disp in disp_data]
            )
        else:
            rightmost_edge = max([disp.resolution[0] + disp.digital_offset[0] for disp in disp_data])
            bottommost_edge = max([disp.resolution[1] + disp.digital_offset[1] for disp in disp_data])
        return (rightmost_edge, bottommost_edge)

    def fit_canvas_wrkarea(self, canvas_px):
        """Compute canvas size relative to the background panel size.

        Returns a size tuple in so that along the longer
        edge of the canvas, at most 90% of the panel dimensions are used.

        Input is either canvas size in true pixels or in PPI normalized
        pixels."""
        rel_factor = 0.9
        rel_achor_gap = (1 - rel_factor) / 2
        work_sz = self.GetSize()
        w2h_ratio_worksz = work_sz[0] / work_sz[1]
        w2h_ratio = canvas_px[0] / canvas_px[1]
        if w2h_ratio > w2h_ratio_worksz:
            # canvas is wider than working area
            # limit width to 90% of working area
            new_width = rel_factor * work_sz[0]
            scaling_fac = new_width / canvas_px[0]
            new_height = scaling_fac * canvas_px[1]
            anchor_left = rel_achor_gap * work_sz[0]
            anchor_top = (work_sz[1] - new_height) / 2
        else:
            # canvas is taller than working area
            new_height = rel_factor * work_sz[1]
            scaling_fac = new_height / canvas_px[1]
            new_width = scaling_fac * canvas_px[0]
            anchor_left = (work_sz[0] - new_width) / 2
            anchor_top = rel_achor_gap * work_sz[1]
        canvas_rel = (round(new_width), round(new_height))
        canvas_rel_pos = (round(anchor_left), round(anchor_top))
        return (canvas_rel, canvas_rel_pos, scaling_fac)

    def displays_on_canvas(self, disp_data, canvas_pos, scaling_fac, use_ppi_px=False):
        """Return sizes and positions of displays in disp_data on the working area.

        if use_ppi_px == True, returned display sizes contain bezels and lists of
        image sizes and bezel rectangles are returned separately.
        bz_szs is a list of size tuples pairs, each in pair for each possible bezel.
        """
        if use_ppi_px:
            display_szs_pos = []
            image_szs = []
            bz_szs = []
            for disp in disp_data:
                res = disp.resolution
                doff = disp.digital_offset
                off = canvas_pos
                bez = disp.ppi_norm_bezels
                display_szs_pos.append(
                    (
                        # tuple 1: size = res + bez
                        (
                            round(scaling_fac * (res[0] + bez[0])),
                            round(scaling_fac * (res[1] + bez[1])),
                        ),
                        # tuple 2: pos
                        (
                            round(scaling_fac * doff[0]) + off[0],
                            round(scaling_fac * doff[1]) + off[1],
                        ),
                    )
                )
                image_szs.append((round(scaling_fac * res[0]), round(scaling_fac * res[1])))
                if bez[0] != 0:
                    right_bez = (
                        round(scaling_fac * bez[0]),
                        round(scaling_fac * (res[1] + bez[1])),
                    )
                else:
                    right_bez = (0, 0)
                if bez[1] != 0:
                    bottom_bez = (round(scaling_fac * res[0]), round(scaling_fac * bez[1]))
                else:
                    bottom_bez = (0, 0)
                bz_szs.append((right_bez, bottom_bez))
            return [display_szs_pos, image_szs, bz_szs]
        else:
            display_szs_pos = []
            for disp in disp_data:
                doff = disp.digital_offset
                off = canvas_pos
                display_szs_pos.append(
                    (
                        tuple([round(px * scaling_fac) for px in disp.resolution]),
                        (
                            round(doff[0] * scaling_fac) + off[0],
                            round(doff[1] * scaling_fac) + off[1],
                        ),
                    )
                )
            return display_szs_pos

    def canvas_display_group(self, disp_szs_pos, major_canv_pos):
        """Compute canvas size and positions for a subset of displays."""
        canv_pos = (
            round(min([sz_pos[1][0] for sz_pos in disp_szs_pos]) + major_canv_pos[0]),
            round(min([sz_pos[1][1] for sz_pos in disp_szs_pos]) + major_canv_pos[1]),
        )
        canv_sz = (
            round(max([sz_pos[0][0] + sz_pos[1][0] for sz_pos in disp_szs_pos]) - canv_pos[0]),
            round(max([sz_pos[0][1] + sz_pos[1][1] for sz_pos in disp_szs_pos]) - canv_pos[1]),
        )
        return (canv_sz, canv_pos)

    #
    # Buttons
    #
    def create_buttons(self, use_ppi_px):
        """Create buttons for display preview positioning config."""
        # Buttons - show only if use_ppi_px == True
        self.button_config = wx.Button(self, label="Positions")
        self.button_save = wx.Button(self, label="Save")
        self.button_reset = wx.Button(self, label="Reset")
        self.button_cancel = wx.Button(self, label="Cancel")
        self.button_entry = wx.Button(self, label="Exact entry")
        help_bmp = wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_BUTTON, wx.Size(20, 20))
        self.button_help = wx.BitmapButton(self, bitmap=wx.BitmapBundle(help_bmp), name="butt_help")

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
        sz_area = self.GetSize()
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
        self.old_ppinorm_offs = self.display_sys.get_ppinorm_offsets()  # back up the offsets
        self.frame.toggle_radio_and_profile_choice(False)
        self.frame.toggle_bezel_buttons(False, False)
        self.config_mode = True
        self.toggle_buttons(False, True)
        self.show_staticbmps(False)
        self.create_shapes()
        self.Refresh()

    def onSave(self, evt):
        """Stage current Display offsets into DisplaySystem.

        The new positions are kept in memory (and shown in the preview) but are
        only written to disk when the system band's Save is pressed.
        """
        self.config_mode = False
        self.bind_movement_binds(False)
        self.toggle_buttons(True, False)
        # Export offsets to DisplaySystem (staged, not persisted here)
        if self.positions_dragged:  # only export drag positions if actually dragged
            self.export_offsets(self.display_sys)
        display_data = self.display_sys.get_disp_list(use_ppi_norm=True)
        # Full redraw of preview with new offset data
        if self.current_preview_images:
            self.preview_wallpaper(self.current_preview_images, True, False, display_data=display_data)
        else:
            self.display_data = display_data
            self.refresh_preview(True)
            self.resize_displays(True)
            # self.show_staticbmps(True)
        self.draggable_shapes = []  # Destroys DragShapes
        self.positions_dragged = False
        self.frame.toggle_radio_and_profile_choice(True)
        self.frame.toggle_bezel_buttons(False, True)
        self.Refresh()
        self.frame._update_system_dirty()

    def onReset(self, evt):
        """Reset Display preview positions to the initial guess."""
        # Back up current offsets
        ppinorm_offs = self.display_sys.get_ppinorm_offsets()
        # Compute and get reset offsets
        self.display_sys.compute_initial_preview_offsets()
        display_data = self.display_sys.get_disp_list(use_ppi_norm=True)
        dtop_canvas_px = self.get_canvas(display_data, True)
        dtop_canvas_relsz, dtop_canvas_pos, scaling_fac = self.fit_canvas_wrkarea(dtop_canvas_px)
        (display_rel_sizes, img_rel_sizes, bz_rel_sizes) = self.displays_on_canvas(
            display_data, dtop_canvas_pos, scaling_fac, True
        )
        # Move display preview draggable_shapes
        for shp, off in zip(self.draggable_shapes, display_rel_sizes):
            shp.pos = off[1]
        # Restore backed up offsets
        self.display_sys.update_ppinorm_offsets(ppinorm_offs)
        self.positions_dragged = True
        self.Refresh()

    def onEntry(self, evt):
        """Opens display positions accurate entry dialog."""
        DisplayPositionEntry(self, dragged_positions=self.positions_dragged)

    def onCancel(self, evt):
        """Cancel out of diplay position config mode."""
        self.config_mode = False
        self.bind_movement_binds(False)
        self.toggle_buttons(True, False)
        self.draggable_shapes = []  # Destroys DragShapes
        self.display_sys.update_ppinorm_offsets(self.old_ppinorm_offs)
        # redraw preview with restored data
        self.display_data = self.display_sys.get_disp_list(True)
        self.refresh_preview()
        self.full_refresh_preview(True, True, False)
        # self.show_staticbmps(True)
        self.frame.toggle_radio_and_profile_choice(True)
        self.frame.toggle_bezel_buttons(False, True)
        self.positions_dragged = False
        self.Refresh()

    def onHelp(self, evt):
        """Popup a help dialog."""
        text = (
            "Preview of your wallpaper settings.\n"
            "In 'advanced span' mode you need use the 'Positions'\n"
            "tool to move the display previews by dragging to\n"
            "as accurately as possible represent the actual\n"
            "positions of you displays on your desk."
        )
        use_per = self.display_sys.use_perspective
        persp_sel = self.frame.ch_persp.GetSelection()
        if persp_sel != wx.NOT_FOUND:
            persname = self.frame.ch_persp.GetString(persp_sel)
        else:
            persname = "default"
        pop = HelpPopup(self, text, show_image_quality=True, use_perspective=use_per, persp_name=persname)
        btn = evt.GetEventObject()
        pos = btn.ClientToScreen((0, 0))
        sz = btn.GetSize()
        pop.Position(pos, wx.Size(0, sz[1]))
        pop.Popup()

    def show_staticbmps(self, show):
        """Show/Hide StaticBitmaps."""
        if self.current_preview_images:
            self.st_bmp_canvas.Show(show)
        else:
            self.st_bmp_canvas.Show(False)
        for st_bmp in self.preview_img_list:
            st_bmp.Show(show)

    def export_offsets(self, display_sys):
        """Read dragged preview positions, normalize them to be positive,
        and scale sizes up to old canvas size."""
        # DragShape sizes and positions need to be scaled up by true_canvas_old_w/preview_canv_w
        prev_canv_w = self.st_bmp_canvas.GetSize()[0]
        true_canv_w = self.get_canvas(display_sys.get_disp_list(True))[0]
        scaling = true_canv_w / prev_canv_w
        sanitzed_offs = self.sanitize_shape_offs()
        ppi_norm_offsets = []
        for off in sanitzed_offs:
            ppi_norm_offsets.append((off[0] * scaling, off[1] * scaling))
        display_sys.update_ppinorm_offsets(ppi_norm_offsets, bezels_included=False)

    def sanitize_shape_offs(self):
        """Return shapes' relative offsets, anchoring to (0,0)."""
        sanitized_offs = []
        leftmost_offset = min([shape.pos[0] for shape in self.draggable_shapes])
        topmost_offset = min([shape.pos[1] for shape in self.draggable_shapes])
        for shape in self.draggable_shapes:
            sanitized_offs.append((shape.pos[0] - leftmost_offset, shape.pos[1] - topmost_offset))
        return sanitized_offs

    #
    # DragImage methods
    #

    class DragShape:
        def __init__(self, bmp):
            self.bmp = bmp
            self.pos = (0, 0)
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

        for st_bmp in self.preview_img_list:
            shape = self.DragShape(st_bmp.GetBitmap())
            shape.pos = st_bmp.GetPosition()
            self.draggable_shapes.append(shape)

        self.Bind(wx.EVT_PAINT, self.OnPaint)
        if enable_movement:
            self.bind_movement_binds(True)

    def bind_movement_binds(self, toggle):
        """Bind or unbind DragImage dragging bindings."""
        if toggle:
            self.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)
            self.Bind(wx.EVT_LEFT_UP, self.OnLeftUp)
            self.Bind(wx.EVT_MOTION, self.OnMotion)
            self.Bind(wx.EVT_LEAVE_WINDOW, self.OnLeaveWindow)
        else:
            self.Unbind(wx.EVT_LEFT_DOWN)
            self.Unbind(wx.EVT_LEFT_UP)
            self.Unbind(wx.EVT_MOTION)
            self.Unbind(wx.EVT_LEAVE_WINDOW)

    def draw_shapes(self, dc):
        for shape in self.draggable_shapes:
            if shape.shown:
                shape.Draw(dc)

    def draw_canvas(self, dc, draw=True):
        if self.st_bmp_canvas:
            pos = self.st_bmp_canvas.GetPosition()
            bmp = self.st_bmp_canvas.GetBitmap()
            bmp_sz = bmp.GetSize()
            if not draw:
                bmp = wx.Bitmap.FromRGBA(bmp_sz[0], bmp_sz[1], red=30, green=30, blue=30, alpha=255)
            op = wx.COPY
            if bmp.IsOk():
                memDC = wx.MemoryDC()
                # memDC.SelectObject(wx.NullBitmap)
                memDC.SelectObject(bmp)

                dc.Blit(pos[0], pos[1], bmp_sz[0], bmp_sz[1], memDC, 0, 0, op, True)

                return True
            else:
                return False

    def draw_st_bmps(self, dc):
        for st_bmp in self.preview_img_list:
            pos = st_bmp.GetPosition()
            bmp = st_bmp.GetBitmap()
            self.draw_bmp(dc, pos, bmp)

    def draw_bmp(self, dc, pos, bmp):
        bmp_sz = bmp.GetSize()
        op = wx.COPY
        if bmp.IsOk():
            memDC = wx.MemoryDC()
            memDC.SelectObject(bmp)

            dc.Blit(pos[0], pos[1], bmp_sz[0], bmp_sz[1], memDC, 0, 0, op, True)
            return True
        else:
            return False

    def find_shape(self, pt):
        for shape in self.draggable_shapes:
            if shape.HitTest(pt):
                return shape
        return None

    def OnPaint(self, evt):
        dc = wx.PaintDC(self)
        # Hiding bitmap widgets, probably unnecessary
        # for st_bmp in self.preview_img_list:
        # st_bmp.Hide()

        # Canvas drawing
        if not self.config_mode and not self.use_multi_image and self.current_preview_images:
            self.draw_canvas(dc)
        else:
            self.draw_canvas(dc, False)

        # Display drawing
        if self.config_mode:
            self.draw_shapes(dc)
        else:
            self.draw_st_bmps(dc)

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
        self.RefreshRect(self.drag_shape.GetRect())
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
            self.RefreshRect(self.drag_shape.GetRect(), True)
            self.Update()

            item = self.drag_shape.text or self.drag_shape.bmp
            self.drag_image = wx.DragImage(item, wx.Cursor(wx.CURSOR_HAND))

            hotspot = self.dragStartPos - self.drag_shape.pos
            self.drag_image.BeginDrag(hotspot, self, self.drag_shape.fullscreen)

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
        self.old_bezels = self.display_sys.bezels_in_mm()
        self.old_ppinorm_offs = self.display_sys.get_ppinorm_offsets()
        self.bezel_conifg_mode = True
        # Draw bitmaps manually, widgets can't overlap
        # self.show_staticbmps(False)
        # self.create_shapes(enable_movement=False)
        self.show_bezel_buttons(True)
        # Hide preview positioning config button
        self.toggle_buttons(False, False)

    def bezel_config_save(self):
        """Stage the new bezel values for the active DisplaySystem.

        Bezel sizes are kept in memory and shown in the preview; persistence to
        disk happens only when the system band's Save is pressed.
        """
        self.bezel_conifg_mode = False
        self.show_bezel_buttons(False)
        # Show preview positioning config button
        self.toggle_buttons(True, False)
        # self.draggable_shapes = []  # Destroys DragShapes / manually drawn previews
        self.full_refresh_preview(True, True, False)
        # self.show_staticbmps(True)
        self.Refresh()

    def bezel_config_cancel(self):
        """Exits out of the bezel config mode without saving."""
        self.bezel_conifg_mode = False
        self.show_bezel_buttons(False)
        # Show preview positioning config button
        self.toggle_buttons(True, False)
        self.display_sys.update_bezels(self.old_bezels)
        self.display_sys.update_ppinorm_offsets(self.old_ppinorm_offs)
        for pops, bez_mms in zip(self.bezel_popups, self.old_bezels):
            pops[0].set_bezel_value(bez_mms[0])
            pops[1].set_bezel_value(bez_mms[1])
        self.display_data = self.display_sys.get_disp_list(True)
        # self.draggable_shapes = []  # Destroys DragShapes / manually drawn previews
        self.full_refresh_preview(True, True, False)
        # self.show_staticbmps(True)
        self.Refresh()

    def create_bezel_buttons(self):
        # load icons into bitmaps
        rb_png = str(resource("icons8-merge-vertical-96.png"))
        bb_png = str(resource("icons8-merge-horizontal-96.png"))
        rb_img = wx.Image(rb_png, type=wx.BITMAP_TYPE_ANY)
        bb_img = wx.Image(bb_png, type=wx.BITMAP_TYPE_ANY)
        rb_bmp = rb_img.Scale(20, 20).Resize(wx.Size(20, 20), wx.Point((0, 0))).ConvertToBitmap()
        bb_bmp = bb_img.Scale(20, 20).Resize(wx.Size(20, 20), wx.Point((0, 0))).ConvertToBitmap()

        # create bitmap buttons
        for st_bmp in self.preview_img_list:
            butt_rb = wx.BitmapButton(self, bitmap=rb_bmp, name="butt_bez_r", style=wx.BORDER_NONE)
            butt_bb = wx.BitmapButton(self, bitmap=bb_bmp, name="butt_bez_b", style=wx.BORDER_NONE)
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
        bezel_mm = self.display_sys.bezels_in_mm()
        for butts, bez_mm in zip(self.bez_buttons, bezel_mm):
            pop_rb = self.popup_at_button(butts[0])
            pop_rb.set_bezel_value(bez_mm[0])
            pop_bb = self.popup_at_button(butts[1])
            pop_bb.set_bezel_value(bez_mm[1])
            self.bezel_popups.append((pop_rb, pop_bb))

    def popup_at_button(self, button):
        """Initialize a popup at button position."""
        try:
            pop = self.BezelEntryPopup(self, wx.SIMPLE_BORDER | wx.PU_CONTAINS_CONTROLS)
        except AttributeError:
            pop = self.BezelEntryPopup(self, wx.SIMPLE_BORDER)
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
        for butts, st_bmp in zip(self.bez_buttons, self.preview_img_list):
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
        # pop.Popup()
        pop.Show()

    #
    # Bezel entry pop-up
    #

    class BezelEntryPopup(wx.PopupTransientWindow):
        # class BezelEntryPopup(wx.PopupWindow):
        """Popup that is shown when a bezel button is pressed in bezel config."""

        def __init__(self, parent, style):
            # wx.PopupTransientWindow.__init__(self, parent, style)
            wx.PopupWindow.__init__(self, parent, style)
            self.preview = parent
            pnl = wx.Panel(self)
            # pnl.SetBackgroundColour("CADET BLUE")

            st = wx.StaticText(pnl, -1, "Enter the size of adjacent bezels and gap\nin millimeters:")
            # self.tc_bez = wx.TextCtrl(pnl, -1, size=(100, -1))
            self.tc_bez = wx.TextCtrl(pnl, -1, size=wx.Size(60, -1), style=wx.TE_RIGHT | wx.TE_PROCESS_ENTER)
            self.tc_bez.Bind(wx.EVT_TEXT_ENTER, self.OnEnter)
            self.current_bez_val = None
            butt_save = wx.Button(pnl, label="Apply")
            butt_canc = wx.Button(pnl, label="Cancel")
            butt_save.Bind(wx.EVT_BUTTON, self.onApply)
            butt_canc.Bind(wx.EVT_BUTTON, self.onCancel)
            butt_sizer = wx.BoxSizer(wx.HORIZONTAL)
            # butt_sizer.AddStretchSpacer()
            butt_sizer.Add(self.tc_bez, 0, wx.ALL, 5)
            butt_sizer.Add(butt_save, 0, wx.ALL, 5)
            butt_sizer.Add(butt_canc, 0, wx.ALL, 5)

            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.Add(st, 0, wx.ALL, 5)
            # sizer.Add(self.tc_bez, 0, wx.ALL, 5)
            sizer.Add(butt_sizer, 0, wx.ALL | wx.EXPAND, 0)
            pnl.SetSizer(sizer)

            sizer.Fit(pnl)
            sizer.Fit(self)
            self.Layout()

        def ProcessLeftDown(self, event):
            # return wx.PopupTransientWindow.ProcessLeftDown(self, event)
            return False

        def OnEnter(self, evt):
            """Bind pressing Enter in the txtctrl to apply entered value."""
            self.onApply(evt)

        def OnDismiss(self):
            self.onCancel(None)

        def onApply(self, event):
            entered_val = self.test_bezel_value()
            if entered_val is False:
                # Abort applying and alert user but don't
                # Dismiss popup to fascilitate fixing.
                msg = f"Bezel thickness must be a non-negative number, '{self.tc_bez.GetValue()}' was entered."
                sp_logging.G_LOGGER.info(msg)
                self.Hide()
                dial = wx.MessageDialog(self, msg, "Error", wx.OK | wx.STAY_ON_TOP | wx.CENTRE)
                dial.ShowModal()
                self.Show()
                return -1
            self.current_bez_val = entered_val
            pops = self.preview.bezel_popups
            bezel_mms = []
            for pop_pair in pops:
                bezel_mms.append((pop_pair[0].bezel_value(), pop_pair[1].bezel_value()))
            # self.Dismiss()
            self.Hide()
            # propagate values and refresh preview
            self.preview.display_sys.update_bezels(bezel_mms)
            self.preview.display_data = self.preview.display_sys.get_disp_list(True)
            self.preview.full_refresh_preview(True, True, False)
            # self.preview.show_staticbmps(False) # Use PaintDC drawing separately from staticbitmaps
            # self.preview.draggable_shapes = []
            # self.preview.create_shapes(enable_movement=False)

        def onCancel(self, event):
            if self.current_bez_val:
                self.tc_bez.SetValue(str(self.current_bez_val))
            else:
                self.tc_bez.SetValue("0.0")
            # self.Dismiss()
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
            """Test that entered value in tc_bez is valid and return it."""
            val = self.tc_bez.GetValue()
            try:
                num = float(val)
                if num >= 0:
                    return num
                else:
                    return False
            except ValueError:
                return False
