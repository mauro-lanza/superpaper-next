"""The editor's preview of the displays and the wallpaper on them."""

import logging
from typing import Literal, assert_never, overload

import wx  # ty:ignore[unresolved-import]
from PIL import Image, ImageEnhance

from superpaper.geometry import canvas
from superpaper.profiles.profile_file import SpanMode
from superpaper.rendering.render import resize_to_fill
from superpaper.rendering.source_image import SourceImageError, open_preview_image
from superpaper.ui.layout_editor import LayoutEditor

logger = logging.getLogger(__name__)

LABEL_FONT_SIZE = 24
LABEL_COLOUR = wx.Colour(60, 60, 60, alpha=wx.ALPHA_OPAQUE)


def black_bitmap(size):
    return wx.Bitmap.FromRGBA(size[0], size[1], red=0, green=0, blue=0, alpha=255)


def clamped_sub_bitmap(bmp, rect):
    """The part of ``bmp`` inside ``rect``, which may reach past its right and bottom edges."""
    right = min(rect.GetRight(), bmp.GetWidth() - 1)
    bottom = min(rect.GetBottom(), bmp.GetHeight() - 1)
    return bmp.GetSubBitmap(wx.Rect(rect.GetTopLeft(), wx.Point(right, bottom)))


class WallpaperPreviewPanel(wx.Panel):
    """Wallpaper & monitor preview panel; ``staged`` is the editor's StagedLayout, which it shows and
    its layout editor changes."""

    def __init__(
        self,
        parent,
        staged,
        *,
        set_profile_controls_enabled,
        toggle_bezel_buttons,
        mark_dirty,
        show_help,
    ):
        self.preview_size = (1080, 400)
        wx.Panel.__init__(self, parent, size=wx.Size(*self.preview_size))
        self.layout_editor = LayoutEditor(
            self,
            set_profile_controls_enabled=set_profile_controls_enabled,
            toggle_bezel_buttons=toggle_bezel_buttons,
            mark_dirty=mark_dirty,
            show_help=show_help,
        )

        # Buttons
        self.layout_editor.create_buttons(use_ppi_px=False)

        # Colour definitions
        self.clr_prw_bkg = wx.Colour(30, 30, 30, alpha=wx.ALPHA_OPAQUE)
        self.SetBackgroundColour(self.clr_prw_bkg)

        # Display data and sizes
        self.staged = staged
        self.display_data = self.staged.layout.real_areas()
        self.dtop_canvas_px = canvas.desktop_extent(self.display_data)
        self.dtop_canvas_relsz, self.dtop_canvas_pos, scaling_fac = canvas.fit_to_panel(
            self.dtop_canvas_px, self.GetSize()
        )
        self.display_rel_sizes = canvas.place_displays(self.display_data, self.dtop_canvas_pos, scaling_fac)

        # bitmaps to be shown
        self.use_multi_image = False
        self.current_preview_images = []
        self.preview_img_list = []

        # Image zoom & positioning (whole-viewport, applied in resize_to_fill)
        self.zoom = 1.0
        self.offset = (0.0, 0.0)
        self._last_span_mode: SpanMode = "single"
        self._last_spangroups = None

        # Draw preview
        self.draw_displays()

        # Create bezel buttons for displays in preview
        self.layout_editor.create_bezel_buttons()

        self.Bind(wx.EVT_PAINT, self.OnPaint)

    #
    # UI drawing methods
    #
    def draw_displays(self, use_ppi_px=False):
        bmp_canv = black_bitmap(self.dtop_canvas_relsz)
        if not self.preview_img_list:
            self.st_bmp_canvas = wx.StaticBitmap(self, wx.ID_ANY, wx.BitmapBundle(bmp_canv))
            self.st_bmp_canvas.SetPosition(wx.Point(self.dtop_canvas_pos))
            self.st_bmp_canvas.Hide()

            for size, offs in self.display_rel_sizes:
                st_bmp = wx.StaticBitmap(self, wx.ID_ANY, wx.BitmapBundle(black_bitmap(size)))
                st_bmp.Hide()
                st_bmp.SetPosition(wx.Point(*offs))
                self.preview_img_list.append(st_bmp)
        else:
            self.current_preview_images = []

            self.st_bmp_canvas.SetBitmap(wx.BitmapBundle(bmp_canv))
            self.st_bmp_canvas.SetPosition(wx.Point(self.dtop_canvas_pos))

            for (size, offs), st_bmp in zip(self.display_rel_sizes, self.preview_img_list, strict=True):
                st_bmp.SetBitmap(black_bitmap(size))
                st_bmp.SetPosition(offs)
        self.draw_monitor_numbers(use_ppi_px)
        self.Refresh()

    def resize_displays(self, use_ppi_px):
        if use_ppi_px:
            for disp, img_sz, bez_szs, st_bmp in zip(
                self.display_rel_sizes, self.img_rel_sizes, self.bz_rel_sizes, self.preview_img_list, strict=True
            ):
                size, offs = disp
                bmp_w_bez = self.bezels_to_bitmap(black_bitmap(img_sz), size, bez_szs)
                st_bmp.SetSize(size)
                st_bmp.SetPosition(offs)
                st_bmp.SetBitmap(bmp_w_bez)
        else:
            for (size, offs), st_bmp in zip(self.display_rel_sizes, self.preview_img_list, strict=True):
                st_bmp.SetBitmap(black_bitmap(size))
                st_bmp.SetPosition(offs)
                st_bmp.SetSize(size)
        self.draw_monitor_numbers(use_ppi_px)

    def draw_monitor_numbers(self, use_ppi_px):
        font = wx.Font(LABEL_FONT_SIZE, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)

        for index, st_bmp in enumerate(self.preview_img_list):
            bmp = st_bmp.GetBitmap()
            dc = wx.MemoryDC(bmp)
            dc.SetTextForeground(LABEL_COLOUR)
            dc.SetFont(font)
            dc.DrawText(str(index), 5, 5)
            del dc
            st_bmp.SetBitmap(bmp)

        if use_ppi_px:
            self.draw_monitor_sizes()

    def draw_monitor_sizes(self):
        font = wx.Font(LABEL_FONT_SIZE, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_LIGHT)

        diagonals = self.staged.layout.diagonal_inches()
        for st_bmp, img_sz, diagonal in zip(self.preview_img_list, self.img_rel_sizes, diagonals, strict=True):
            bmp = st_bmp.GetBitmap()
            dc = wx.MemoryDC(bmp)
            text = str(diagonal) + '"'
            dc.SetTextForeground(LABEL_COLOUR)
            dc.SetFont(font)
            bmp_w, _ = img_sz
            text_w, _ = dc.GetTextExtent(text)
            pos_w = bmp_w - text_w - 5
            pos_h = 5
            dc.DrawText(text, pos_w, pos_h)
            del dc
            st_bmp.SetBitmap(bmp)

    def refresh_preview(self, use_ppi_px=False):
        if 0 in self.GetSize():  # not laid out yet; the resize that follows draws it
            return
        if use_ppi_px:
            self.dtop_canvas_px = canvas.desktop_extent_with_bezels(self.display_data)
        else:
            self.dtop_canvas_px = canvas.desktop_extent(self.display_data)
        self.dtop_canvas_relsz, self.dtop_canvas_pos, scaling_fac = canvas.fit_to_panel(
            self.dtop_canvas_px, self.GetSize()
        )
        self.st_bmp_canvas.SetPosition(wx.Point(self.dtop_canvas_pos))
        self.st_bmp_canvas.SetSize(wx.Size(*self.dtop_canvas_relsz))

        if use_ppi_px:
            placed = canvas.place_displays_with_bezels(self.display_data, self.dtop_canvas_pos, scaling_fac)
            self.display_rel_sizes = [(display.size, display.position) for display in placed]
            self.img_rel_sizes = [display.image_size for display in placed]
            self.bz_rel_sizes = [display.bezel_rects for display in placed]
        else:
            self.display_rel_sizes = canvas.place_displays(self.display_data, self.dtop_canvas_pos, scaling_fac)
        for (size, offs), st_bmp in zip(self.display_rel_sizes, self.preview_img_list, strict=True):
            st_bmp.SetPosition(offs)
            st_bmp.SetSize(size)

        self.layout_editor.move_buttons()
        self.layout_editor.move_bezel_buttons()

    def full_refresh_preview(self, span_mode, spangroups=None):
        self.use_multi_image = span_mode == "multi"
        use_ppi_px = span_mode == "advanced"
        if not self.layout_editor.config_mode:
            if self.current_preview_images:
                self.preview_wallpaper(self.current_preview_images, span_mode, spangroups=spangroups)
                self.layout_editor.move_bezel_buttons()
            else:
                self.refresh_preview(use_ppi_px)
                self.resize_displays(use_ppi_px)
                self.layout_editor.move_bezel_buttons()
                self.Refresh()

    def preview_wallpaper(
        self,
        image_list,
        span_mode: SpanMode,
        display_data=None,
        spangroups: tuple[tuple[int, ...], ...] | None = None,
    ):
        """Show ``image_list`` on the displays as ``span_mode`` spans it; ``spangroups``, the
        displays each image spans, apply to advanced spanning."""
        use_ppi_px = span_mode == "advanced"
        self.use_multi_image = span_mode == "multi"
        if display_data:
            self.display_data = display_data
        self._last_span_mode = span_mode
        self._last_spangroups = spangroups
        self.refresh_preview(use_ppi_px)
        self.current_preview_images = image_list
        if not image_list:
            # Nothing to show, e.g. the profile's images are on an unmounted drive.
            self.draw_displays(use_ppi_px)
            return

        match span_mode:
            case "multi":
                # A profile can list more images than there are displays, or fewer; the extras are
                # not shown and the missing ones repeat the first.
                images = [*image_list, *[image_list[0]] * (len(self.preview_img_list) - len(image_list))]
                for img_nm, st_bmp in zip(images, self.preview_img_list, strict=False):
                    st_bmp.SetBitmap(self.resize_and_bitmap(img_nm, st_bmp.GetSize()))
            case "advanced" if spangroups:
                self.use_multi_image = True  # disables canvas drawing
                # Images and groups can differ in number; the unpaired ones are not shown.
                for group, img_nm in zip(spangroups, image_list, strict=False):
                    display_rel_sizes = [self.display_rel_sizes[i] for i in group]
                    canv_sz, canvas_pos = canvas.group_canvas(display_rel_sizes)
                    bmp_clr, _ = self.resize_and_bitmap(img_nm, canv_sz, True)
                    self.show_cropped_displays(
                        bmp_clr,
                        canvas_pos,
                        display_rel_sizes,
                        [self.img_rel_sizes[i] for i in group],
                        [self.bz_rel_sizes[i] for i in group],
                        [self.preview_img_list[i] for i in group],
                    )
            case "advanced":
                # The image fills the canvas dimmed; each display shows its unaltered piece, with bezels.
                bmp_clr, bmp_bw = self.resize_and_bitmap(image_list[0], self.st_bmp_canvas.GetSize(), True)
                self.st_bmp_canvas.SetBitmap(wx.BitmapBundle(bmp_bw))
                self.show_cropped_displays(
                    bmp_clr,
                    self.dtop_canvas_pos,
                    self.display_rel_sizes,
                    self.img_rel_sizes,
                    self.bz_rel_sizes,
                    self.preview_img_list,
                )
            case "single":
                bmp_clr, bmp_bw = self.resize_and_bitmap(image_list[0], self.st_bmp_canvas.GetSize(), True)
                self.st_bmp_canvas.SetBitmap(wx.BitmapBundle(bmp_bw))

                canvas_pos = self.dtop_canvas_pos
                for (sz, offs), st_bmp in zip(self.display_rel_sizes, self.preview_img_list, strict=True):
                    pos = (offs[0] - canvas_pos[0], offs[1] - canvas_pos[1])
                    st_bmp.SetBitmap(clamped_sub_bitmap(bmp_clr, wx.Rect(pos, sz)))
            case _:
                assert_never(span_mode)
        self.draw_monitor_numbers(use_ppi_px)
        self.Refresh()

    def show_cropped_displays(self, bmp, canvas_pos, display_rel_sizes, img_rel_sizes, bz_rel_sizes, st_bmps):
        """Show on each display's StaticBitmap its piece of ``bmp``, with its bezels added."""
        for (sz, offs), img_sz, bez_szs, st_bmp in zip(
            display_rel_sizes, img_rel_sizes, bz_rel_sizes, st_bmps, strict=True
        ):
            pos = (offs[0] - canvas_pos[0], offs[1] - canvas_pos[1])
            crop = clamped_sub_bitmap(bmp, wx.Rect(pos, img_sz))
            st_bmp.SetBitmap(self.bezels_to_bitmap(crop, sz, bez_szs))

    def update_zoom_offset(self, zoom, offset):
        """Re-render the current preview with new zoom & offset values."""
        self.zoom = zoom
        self.offset = offset
        if not self.current_preview_images:
            return
        self.preview_wallpaper(
            list(self.current_preview_images),
            self._last_span_mode,
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
            pil = resize_to_fill(
                open_preview_image(fname),
                size,
                zoom=self.zoom,
                offset=self.offset,
                resample=Image.Resampling.HAMMING,
                reducing_gap=1.5,
            )
        except SourceImageError as error:  # unreadable, truncated, too large, or no longer there
            logger.info("Cannot preview image '%s': %s", fname, error)
            black_bmp = black_bitmap(size)
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

    def update_display_data(self, display_data, span_mode, spangroups=None):
        self.display_data = display_data
        self.refresh_preview()
        self.full_refresh_preview(span_mode, spangroups=spangroups)

    def draw_st_bmps(self, dc):
        for st_bmp in self.preview_img_list:
            pos = st_bmp.GetPosition()
            bmp = st_bmp.GetBitmap()
            self.draw_bmp(dc, pos, bmp)

    def draw_bmp(self, dc, pos, bmp):
        if bmp.IsOk():
            memDC = wx.MemoryDC()
            memDC.SelectObject(bmp)
            bmp_sz = bmp.GetSize()
            dc.Blit(pos[0], pos[1], bmp_sz[0], bmp_sz[1], memDC, 0, 0, wx.COPY, True)

    def OnPaint(self, evt):
        dc = wx.PaintDC(self)

        canvas_bmp = self.st_bmp_canvas.GetBitmap()
        if self.layout_editor.config_mode or self.use_multi_image or not self.current_preview_images:
            canvas_bmp = wx.Bitmap.FromRGBA(*canvas_bmp.GetSize(), red=30, green=30, blue=30, alpha=255)
        self.draw_bmp(dc, self.st_bmp_canvas.GetPosition(), canvas_bmp)

        # Display drawing
        if self.layout_editor.config_mode:
            self.layout_editor.draw_shapes(dc)
        else:
            self.draw_st_bmps(dc)
