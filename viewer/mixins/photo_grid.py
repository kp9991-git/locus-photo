import math
import os
import queue
import threading
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

from viewer.core.logging_config import lock
from viewer.core.utils import clear_queue, resize_image
from viewer.ui.widgets import pil_image_to_qpixmap, ZoomablePhotoLabel
from viewer.metadata.image_container import ImageContainer
from viewer.mixins.image_loading import ImageLoadingMixin
from viewer.metadata.exiftool_wrapper import ExifToolWrapper
from viewer.core.enums import MetaTagName

class PhotoGridMixin:
    WORKER_STOP_SIGNAL = None

    # ── Photo grid & pagination ───────────────────────────────────────

    def _clear_grid_focus_state(self):
        self._focused_grid_origin_fpaths = None
        self._focused_grid_origin_page_index = 0

    def _update_focus_restore_control(self):
        button = getattr(self, "back_to_grid_button", None)
        if button is None:
            return

        origin = getattr(self, "_focused_grid_origin_fpaths", None)
        current = getattr(self, "selected_photo_fpaths", [])
        can_restore = (
            isinstance(origin, list)
            and len(origin) > 1
            and len(current) == 1
            and current[0] in origin
        )
        button.setVisible(can_restore)
        button.setEnabled(can_restore)

    def _queue_image_preload_window(self):
        if len(self.selected_photo_fpaths) == 0:
            return

        start = self.current_page_index * self.grid_items_per_page
        end = start + self.grid_items_per_page * 2
        for fpath in dict.fromkeys(self.selected_photo_fpaths[start:end]):
            self.image_load_queue.put(fpath)

    def _photo_decoration_extra_pixels(self):
        # Total horizontal/vertical inset introduced by frame + subtle shadow.
        return 12

    def _get_photo_label_stylesheet(self):
        # Keep the thumbnail slot neutral; framing is painted into the image pixmap.
        return (
            "QLabel {"
            "background-color: transparent;"
            f"color: {self.text_color};"
            "border: none;"
            "padding: 0px;"
            "}"
        )

    def _decorate_photo_pixmap(self, pixmap):
        if pixmap is None or pixmap.isNull():
            return pixmap

        frame_padding = 2
        frame_radius = 3
        shadow_layers = 3
        shadow_offset_x = 1
        shadow_offset_y = 1
        shadow_max_alpha = 18 if self.theme_name in ("light", "gray") else 26

        frame_w = pixmap.width() + frame_padding * 2
        frame_h = pixmap.height() + frame_padding * 2

        left_pad = shadow_layers
        top_pad = shadow_layers
        right_pad = shadow_layers + shadow_offset_x
        bottom_pad = shadow_layers + shadow_offset_y

        out_w = frame_w + left_pad + right_pad
        out_h = frame_h + top_pad + bottom_pad

        out = QPixmap(out_w, out_h)
        out.fill(Qt.GlobalColor.transparent)

        frame_x = left_pad
        frame_y = top_pad

        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)

        # Layered rounded rectangles create a very subtle soft shadow.
        for layer in range(shadow_layers, 0, -1):
            alpha = max(2, int(shadow_max_alpha * layer / shadow_layers))
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(
                frame_x - layer + shadow_offset_x,
                frame_y - layer + shadow_offset_y,
                frame_w + layer * 2,
                frame_h + layer * 2,
                frame_radius + layer,
                frame_radius + layer,
            )

        frame_bg = QColor(getattr(self, "control_bg_color", self.bg_color))
        frame_border = QColor(getattr(self, "border_color", self.text_color))
        painter.setBrush(frame_bg)
        painter.setPen(QPen(frame_border, 1))
        painter.drawRoundedRect(frame_x, frame_y, frame_w, frame_h, frame_radius, frame_radius)

        painter.drawPixmap(frame_x + frame_padding, frame_y + frame_padding, pixmap)
        painter.end()
        return out

    def _apply_photo_label_decoration(self, label):
        label.setStyleSheet(self._get_photo_label_stylesheet())
        label.setContentsMargins(0, 0, 0, 0)
        label.setGraphicsEffect(None)

        label.set_decorate_pixmap_callback(self._decorate_photo_pixmap)

        base_pixmap = label.property("_photo_base_pixmap")
        if isinstance(base_pixmap, QPixmap) and not base_pixmap.isNull():
            label.set_base_pixmap(base_pixmap, reset_zoom=False)

    def _clear_photo_grid(self):
        if self.photo_grid_layout is None:
            return
        with lock:
            for label in self.image_labels:
                self.photo_grid_layout.removeWidget(label)
                label.deleteLater()
            self.image_labels = []
            self.displayed_photos = []
            self.canvas_currently_displayed_image_fpath = None
            self.canvas_selected_fpath = None
            self.canvas_selected_fpath_loaded = False
        self.signals.clear_map_signal.emit()

    def _get_total_pages(self):
        if len(self.selected_photo_fpaths) == 0:
            return 0
        return (len(self.selected_photo_fpaths) + self.grid_items_per_page - 1) // self.grid_items_per_page

    def _get_current_page_fpaths(self):
        total_pages = self._get_total_pages()
        if total_pages == 0:
            return []
        self.current_page_index = min(max(self.current_page_index, 0), total_pages - 1)
        start = self.current_page_index * self.grid_items_per_page
        end = start + self.grid_items_per_page
        return self.selected_photo_fpaths[start:end]

    def _update_pagination_controls(self):
        self._update_focus_restore_control()
        if (
            self.pagination_frame is None
            or self.page_status_label is None
            or self.first_page_button is None
            or self.prev_page_button is None
            or self.next_page_button is None
            or self.last_page_button is None
        ):
            return
        total_selected = len(self.selected_photo_fpaths)
        show_pagination = total_selected > 1
        self.pagination_frame.setVisible(show_pagination)
        if not show_pagination:
            self.page_status_label.setText("")
            self.first_page_button.setEnabled(False)
            self.prev_page_button.setEnabled(False)
            self.next_page_button.setEnabled(False)
            self.last_page_button.setEnabled(False)
            return

        total_pages = self._get_total_pages()
        if total_pages == 0:
            self.page_status_label.setText("")
            self.first_page_button.setEnabled(False)
            self.prev_page_button.setEnabled(False)
            self.next_page_button.setEnabled(False)
            self.last_page_button.setEnabled(False)
            return

        current_page = min(self.current_page_index + 1, total_pages)
        self.page_status_label.setText("{}/{} ({} images)".format(
            current_page, total_pages, total_selected,
        ))
        self.first_page_button.setEnabled(current_page > 1)
        self.prev_page_button.setEnabled(current_page > 1)
        self.next_page_button.setEnabled(current_page < total_pages)
        self.last_page_button.setEnabled(current_page < total_pages)

    def _queue_current_page_for_display(self):
        page_fpaths = self._get_current_page_fpaths()
        self._queue_image_preload_window()
        self._update_pagination_controls()
        clear_queue(self.display_image_queue)
        if len(page_fpaths) > 0:
            self.display_image_queue.put(page_fpaths)
        else:
            self._clear_photo_grid()

    def show_previous_page(self):
        if self.current_page_index > 0:
            self.current_page_index -= 1
            self._queue_current_page_for_display()

    def show_first_page(self):
        if self.current_page_index > 0:
            self.current_page_index = 0
            self._queue_current_page_for_display()

    def show_next_page(self):
        total_pages = self._get_total_pages()
        if self.current_page_index + 1 < total_pages:
            self.current_page_index += 1
            self._queue_current_page_for_display()

    def show_last_page(self):
        total_pages = self._get_total_pages()
        if total_pages > 0 and self.current_page_index != total_pages - 1:
            self.current_page_index = total_pages - 1
            self._queue_current_page_for_display()

    def show_photo_in_parent_grid(self, fpath):
        if not fpath:
            return

        parent_dir = os.path.dirname(fpath)
        if not parent_dir or not os.path.isdir(parent_dir):
            return

        folder_fpaths = []
        for name in os.listdir(parent_dir):
            full_fpath = os.path.join(parent_dir, name)
            if not os.path.isdir(full_fpath):
                folder_fpaths.append(full_fpath)

        folder_fpaths = list(dict.fromkeys(folder_fpaths))
        if len(folder_fpaths) == 0:
            return

        if fpath not in folder_fpaths:
            folder_fpaths.append(fpath)

        target_index = folder_fpaths.index(fpath)
        target_page_index = target_index // max(1, int(self.grid_items_per_page))

        self.selected_items = [parent_dir]
        tree_widget = getattr(self, "tree", None)
        folder_tree_item = self._find_tree_item(parent_dir)
        if tree_widget is not None and folder_tree_item is not None:
            previous_block_state = tree_widget.blockSignals(True)
            try:
                tree_widget.clearSelection()
                folder_tree_item.setSelected(True)
                tree_widget.setCurrentItem(folder_tree_item)
            finally:
                tree_widget.blockSignals(previous_block_state)

        self._clear_grid_focus_state()
        self.selected_photo_fpaths = folder_fpaths
        self.current_page_index = target_page_index
        self._queue_current_page_for_display()

    def _update_map_slot(self, coords):
        for c in coords:
            self.map_widget.set_position(c[0], c[1], marker=True)

    def _clear_map_slot(self):
        self.map_widget.delete_all_marker()

    def _is_raw_zoom_candidate(self, fpath):
        ext = os.path.splitext(fpath)[1].lower()
        if not ext:
            return False
        image_extensions = {str(e).lower() for e in getattr(self, "IMAGE_SUPPORTED_EXTENSIONS", [])}
        return ext not in image_extensions

    def _request_zoom_image_load(self, fpath, label):
        if not fpath or label is None:
            return
        if not self._is_raw_zoom_candidate(fpath):
            return
        if bool(label.property("_zoom_fullres_loaded")):
            return

        if getattr(self, "_zoom_loading_fpaths", None) is None:
            self._zoom_loading_fpaths = set()

        if fpath in self._zoom_loading_fpaths:
            return

        self._zoom_loading_fpaths.add(fpath)
        thread = threading.Thread(
            name="viewer-zoom-image-load",
            target=self._run_zoom_image_load,
            args=(fpath,),
            daemon=True,
        )
        thread.start()

    def _run_zoom_image_load(self, fpath):
        # Uses a dedicated ExifToolWrapper to avoid concurrent access on the
        # shared self.exiftool instance, which is not thread-safe (a timeout
        # on either thread could terminate or replace the shared subprocess).
        # Like GPS write workers, the local wrapper is always terminated in
        # the finally block.
        #
        # Note on zoom quality: load_image follows the same thumbnail
        # extraction chain as normal loading (ExifTool JPEG/preview, then
        # rawpy partial-read). With resize_ratio=None the result is the
        # embedded preview at full size rather than postprocessed RAW data,
        # which is sufficient for zoom while avoiding the large memory spike
        # of a full rawpy.postprocess() decode.
        image_container = None
        exiftool_local = ExifToolWrapper(logger=self.logger)
        try:
            supported_extensions = set(self.SUPPORTED_EXTENSIONS) if self.SUPPORTED_EXTENSIONS is not None else None
            image_supported_extensions = set(self.IMAGE_SUPPORTED_EXTENSIONS)
            image_container = ImageLoadingMixin.load_image(
                fpath,
                self.use_logging,
                exiftool_local,
                self.MAX_FILE_SIZE,
                supported_extensions,
                image_supported_extensions,
                self.thumbnail_via_exiftool,
                self.read_raw_partially,
                resize_ratio=None,
            )
        except Exception:
            if self.logger:
                self.logger.error("Unexpected error loading zoom image for %s", fpath, exc_info=True)
        finally:
            try:
                exiftool_local.terminate()
            except Exception:
                pass

        payload = {
            "fpath": fpath,
            "image_container": image_container,
        }
        zoom_signal = getattr(self.signals, "zoom_image_ready", None)
        if zoom_signal is not None:
            zoom_signal.emit(payload)
        else:
            self._on_zoom_image_ready(payload)

    def _apply_zoom_image_to_label(self, label, image_container):
        if label is None or image_container is None or image_container.img is None:
            return

        angle = image_container.get_rotation_angle_cw()
        img = image_container.img.rotate(angle, expand=True)
        base_pixmap = pil_image_to_qpixmap(img)
        label.setProperty("_photo_base_pixmap", base_pixmap)
        label.set_base_pixmap(base_pixmap, reset_zoom=False)
        label.setProperty("_zoom_fullres_loaded", True)
        label.mark_zoom_data_ready()

    def _on_zoom_image_ready(self, payload):
        if not isinstance(payload, dict):
            return

        fpath = payload.get("fpath")
        if getattr(self, "_zoom_loading_fpaths", None) is None:
            self._zoom_loading_fpaths = set()
        if fpath:
            self._zoom_loading_fpaths.discard(fpath)

        image_container = payload.get("image_container")
        if image_container is None:
            for label in list(getattr(self, "image_labels", [])):
                if label.property("_photo_source_fpath") == fpath:
                    label.clear_zoom_request_state()
            return

        for label in list(getattr(self, "image_labels", [])):
            if label.property("_photo_source_fpath") != fpath:
                continue
            self._apply_zoom_image_to_label(label, image_container)
            break

    def map_location_background(self):
        while True:
            try:
                coords = self.map_location_queue.get(timeout=0.1)
            except queue.Empty:
                if not self.running:
                    break
                continue

            if coords is self.WORKER_STOP_SIGNAL:
                break
            if len(coords) == 0:
                self.signals.clear_map_signal.emit()
            else:
                self.signals.update_map_signal.emit(coords)

    def display_image_background(self):
        while True:
            try:
                fpaths = self.display_image_queue.get(timeout=0.1)
            except queue.Empty:
                if not self.running:
                    break
                continue

            if fpaths is self.WORKER_STOP_SIGNAL:
                break
            if self.logger:
                [self.logger.debug("display_image_background: #{} {}".format(i + 1, fpath)) for i, fpath in enumerate(fpaths)]
            self.signals.display_images_signal.emit(fpaths)

    def _display_images_slot(self, fpaths, _attempt=0):
        if _attempt > 0:
            expected_fpaths = self._get_current_page_fpaths()
            if expected_fpaths != fpaths:
                return
        if not self.display_images(fpaths):
            if _attempt < 5:
                QTimer.singleShot(1000, lambda fp=fpaths, a=_attempt + 1: self._display_images_slot(fp, a))

    def display_images(self, fpaths):
        if len(fpaths) == 0:
            return True

        with lock:
            fpath = fpaths[0]
            for label in self.image_labels:
                self.photo_grid_layout.removeWidget(label)
                label.deleteLater()
            self.image_labels = []
            self.displayed_photos = []
            self.signals.clear_map_signal.emit()
            self.canvas_selected_fpath = fpath
            self.canvas_selected_fpath_loaded = False

        res = True
        nb_items = len(fpaths)
        nb_columns = max(1, int(math.ceil(math.sqrt(nb_items))))
        nb_rows = max(1, int(math.ceil(nb_items / nb_columns)))
        padx = 12
        pady = 12

        photo_frame_width = self.photo_frame.width() - padx * 2 * nb_columns
        photo_frame_height = self.photo_frame.height() - pady * 2 * nb_rows

        if photo_frame_width <= 0:
            photo_frame_width = self.photo_frames_width - padx * 2 * nb_columns
        if photo_frame_height <= 0:
            photo_frame_height = self.photo_frame_height - pady * 2 * nb_rows

        img_target_width = max(80, photo_frame_width // nb_columns)
        img_target_height = max(80, photo_frame_height // nb_rows)
        frame_inset_px = self._photo_decoration_extra_pixels()
        img_render_width = max(40, img_target_width - frame_inset_px)
        img_render_height = max(40, img_target_height - frame_inset_px)

        row = 0
        column = 0
        map_queue = []

        for i, fpath in enumerate(fpaths):
            if self.logger:
                self.logger.info("display_image: #{} {}".format(i + 1, fpath))

            if column >= nb_columns:
                column = 0
                row += 1

            img_container: ImageContainer = self.get_image(fpath)

            label = ZoomablePhotoLabel(decorate_pixmap_callback=self._decorate_photo_pixmap)
            label.setFixedSize(img_target_width, img_target_height)
            self._apply_photo_label_decoration(label)
            label.setProperty("_photo_source_fpath", fpath)
            label.setProperty("_zoom_fullres_loaded", False)
            label.set_zoom_request_callback(
                lambda target_label, target_fpath=fpath: self._request_zoom_image_load(target_fpath, target_label)
            )
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            focused_origin = getattr(self, "_focused_grid_origin_fpaths", None)
            is_focus_restore_mode = (
                isinstance(focused_origin, list)
                and len(focused_origin) > 1
                and len(self.selected_photo_fpaths) == 1
                and fpath in focused_origin
            )
            if is_focus_restore_mode:
                label.set_blowup_action(
                    callback=self.restore_grid_after_focus,
                    enabled=True,
                    tooltip="Back to grid",
                )
            elif len(self.selected_photo_fpaths) == 1:
                label.set_blowup_action(
                    callback=lambda target_fpath=fpath: self.show_photo_in_parent_grid(target_fpath),
                    enabled=True,
                    tooltip="Open folder grid",
                )
            else:
                label.set_blowup_action(
                    callback=lambda target_fpath=fpath: self.show_single_photo_in_grid(target_fpath),
                    enabled=len(self.selected_photo_fpaths) > 1,
                    tooltip="Focus this photo in grid",
                )

            if img_container is not None:

                angle = img_container.get_rotation_angle_cw()
                img = img_container.img.rotate(angle, expand=True)

                img = resize_image(img, width=img_render_width, height=img_render_height, logger=self.logger, width_max=True, height_max=True)

                base_pixmap = pil_image_to_qpixmap(img)
                label.setProperty("_photo_base_pixmap", base_pixmap)
                label.set_base_pixmap(base_pixmap)
                pixmap = label.pixmap()

                if pixmap is not None:
                    self.displayed_photos.append(pixmap)

                if img_container.meta_data_num.get(MetaTagName.GPSLatitude) is not None and img_container.meta_data_num.get(MetaTagName.GPSLongitude) is not None:
                    map_queue.append((img_container.meta_data_num[MetaTagName.GPSLatitude], img_container.meta_data_num[MetaTagName.GPSLongitude]))
                    self.canvas_selected_fpath_loaded = True

                self.canvas_currently_displayed_image_fpath = fpath

                if self.logger:
                    self.logger.debug("display_image: initial {}x{}, img {}x{}, col/row {}x{}".format(
                        img_target_width, img_target_height, img.size[0], img.size[1], column, row))
            else:
                label.setText("Loading")
                res = False

            self.photo_grid_layout.addWidget(label, row, column)
            self.image_labels.append(label)

            column += 1

        if map_queue:
            self.signals.update_map_signal.emit(map_queue)

        return res

    def show_single_photo_in_grid(self, fpath):
        if len(self.selected_photo_fpaths) <= 1:
            return
        if fpath not in self.selected_photo_fpaths:
            return

        self._focused_grid_origin_fpaths = list(self.selected_photo_fpaths)
        self._focused_grid_origin_page_index = int(self.current_page_index)
        self.selected_photo_fpaths = [fpath]
        self.current_page_index = 0
        self._queue_current_page_for_display()

    def restore_grid_after_focus(self):
        origin = getattr(self, "_focused_grid_origin_fpaths", None)
        if not isinstance(origin, list) or len(origin) <= 1:
            self._clear_grid_focus_state()
            self._update_focus_restore_control()
            return

        self.selected_photo_fpaths = list(origin)
        total_pages = self._get_total_pages()
        if total_pages <= 0:
            self.current_page_index = 0
        else:
            target_index = max(0, int(getattr(self, "_focused_grid_origin_page_index", 0)))
            self.current_page_index = min(target_index, total_pages - 1)

        self._clear_grid_focus_state()
        self._queue_current_page_for_display()

