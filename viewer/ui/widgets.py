from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QStyle, QMenu, QToolButton, QFrame
from PySide6.QtCore import Qt, Signal, QObject, QUrl, QEvent, QPoint, QSize
from PySide6.QtGui import QPixmap, QImage, QIcon, QPainter, QColor, QPalette, QGuiApplication, QCursor, QFont
from PySide6.QtWebEngineWidgets import QWebEngineView


def pil_image_to_qpixmap(pil_img):
    """Convert a PIL Image to a QPixmap."""
    if pil_img.mode != "RGBA":
        pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimage = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())


class WorkerSignals(QObject):
    """Signals for cross-thread GUI updates."""
    update_tree_icons = Signal(list)
    display_images_signal = Signal(list)
    update_map_signal = Signal(list)
    clear_map_signal = Signal()
    gps_write_completed = Signal(object)
    gps_read_completed = Signal(object)
    zoom_image_ready = Signal(object)


class ZoomablePhotoLabel(QLabel):
    """Photo label supporting mouse-wheel zoom around the current image."""

    def __init__(self, parent=None, decorate_pixmap_callback=None):
        super().__init__(parent)
        self._base_pixmap = QPixmap()
        self._render_pixmap = QPixmap()
        self._zoom_factor = 1.0
        self._min_zoom = 1.0
        self._max_zoom = 5.0
        self._zoom_step = 1.12
        self._decorate_pixmap_callback = decorate_pixmap_callback
        self._pan_offset = QPoint(0, 0)
        self._drag_active = False
        self._drag_last_pos = QPoint(0, 0)
        self._zoom_controls = None
        self._zoom_out_button = None
        self._zoom_reset_button = None
        self._zoom_in_button = None
        self._zoom_blowup_button = None
        self._blowup_callback = None
        self._blowup_enabled = False
        self._zoom_request_callback = None
        self._zoom_data_requested = False
        self._fit_scale = 1.0
        self._create_zoom_controls()

    def _update_fit_scale(self):
        if self._base_pixmap.isNull() or self.width() <= 0 or self.height() <= 0:
            self._fit_scale = 1.0
            return
        scale_w = float(self.width()) / float(self._base_pixmap.width())
        scale_h = float(self.height()) / float(self._base_pixmap.height())
        self._fit_scale = max(0.01, min(1.0, scale_w, scale_h))

    def _create_zoom_controls(self):
        self._zoom_controls = QWidget(self)
        self._zoom_controls.setObjectName("PhotoZoomControls")

        controls_layout = QHBoxLayout(self._zoom_controls)
        controls_layout.setContentsMargins(4, 3, 4, 3)
        controls_layout.setSpacing(2)

        self._zoom_out_button = QToolButton(self._zoom_controls)
        self._zoom_out_button.setText("-")
        self._zoom_out_button.setToolTip("Zoom out")
        self._zoom_out_button.clicked.connect(self.zoom_out)

        self._zoom_reset_button = QToolButton(self._zoom_controls)
        self._zoom_reset_button.setText("fit")
        self._zoom_reset_button.setToolTip("Fit to view")
        self._zoom_reset_button.clicked.connect(self.reset_zoom)

        self._zoom_in_button = QToolButton(self._zoom_controls)
        self._zoom_in_button.setText("+")
        self._zoom_in_button.setToolTip("Zoom in")
        self._zoom_in_button.clicked.connect(self.zoom_in)

        self._zoom_blowup_button = QToolButton(self._zoom_controls)
        self._zoom_blowup_button.setText("[]")
        self._zoom_blowup_button.setToolTip("Focus this photo in grid")
        self._zoom_blowup_button.clicked.connect(self.open_full_size_preview)

        mono_font = QFont("Courier New")
        mono_font.setStyleHint(QFont.StyleHint.TypeWriter)
        mono_font.setPointSize(9)

        for button in (self._zoom_out_button, self._zoom_reset_button, self._zoom_in_button, self._zoom_blowup_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoRaise(True)
            button.setFont(mono_font)
            button.setStyleSheet(
                "QToolButton {"
                "background-color: rgba(18, 18, 18, 78);"
                "color: white;"
                "border: 1px solid rgba(255, 255, 255, 34);"
                "border-radius: 5px;"
                "padding: 0px 3px;"
                "font-size: 9px;"
                "}"
                "QToolButton:hover { background-color: rgba(18, 18, 18, 120); }"
            )
            button.setFixedHeight(16)

        self._zoom_reset_button.setFixedWidth(24)
        self._zoom_out_button.setFixedWidth(16)
        self._zoom_in_button.setFixedWidth(16)
        self._zoom_blowup_button.setFixedWidth(20)

        controls_layout.addWidget(self._zoom_out_button)
        controls_layout.addWidget(self._zoom_reset_button)
        controls_layout.addWidget(self._zoom_in_button)
        controls_layout.addWidget(self._zoom_blowup_button)

        self._zoom_controls.setStyleSheet(
            "#PhotoZoomControls {"
            "background-color: rgba(10, 10, 10, 52);"
            "border: 1px solid rgba(255, 255, 255, 24);"
            "border-radius: 7px;"
            "}"
        )
        self._zoom_controls.hide()
        self._zoom_blowup_button.hide()
        self._position_zoom_controls()

    def _get_render_origin(self):
        origin_x = (self.width() - self._render_pixmap.width()) // 2 + self._pan_offset.x()
        origin_y = (self.height() - self._render_pixmap.height()) // 2 + self._pan_offset.y()
        return origin_x, origin_y

    def _position_zoom_controls(self):
        if self._zoom_controls is None:
            return

        self._zoom_controls.adjustSize()
        inset = 6

        if self._render_pixmap.isNull():
            x = max(0, self.width() - self._zoom_controls.width() - inset)
            y = inset
            self._zoom_controls.move(x, y)
            return

        origin_x, origin_y = self._get_render_origin()
        x = origin_x + self._render_pixmap.width() - self._zoom_controls.width() - inset
        y = origin_y + inset

        # Keep controls in the visible bounds even when the image is panned.
        x = min(max(0, x), max(0, self.width() - self._zoom_controls.width()))
        y = min(max(0, y), max(0, self.height() - self._zoom_controls.height()))
        self._zoom_controls.move(x, y)

    def _show_zoom_controls(self):
        if self._zoom_controls is None or self._base_pixmap.isNull():
            return
        self._position_zoom_controls()
        self._zoom_controls.show()
        self._zoom_controls.raise_()

    def _hide_zoom_controls(self):
        if self._zoom_controls is not None:
            self._zoom_controls.hide()

    def _set_zoom_factor(self, zoom_factor):
        if self._base_pixmap.isNull():
            return

        target_zoom = max(self._min_zoom, min(self._max_zoom, float(zoom_factor)))
        if target_zoom > self._min_zoom and not self._zoom_data_requested and callable(self._zoom_request_callback):
            self._zoom_data_requested = True
            self._zoom_request_callback(self)

        self._zoom_factor = target_zoom
        if self._zoom_factor <= self._min_zoom:
            self._pan_offset = QPoint(0, 0)
        self._refresh_pixmap()

    def set_zoom_request_callback(self, callback):
        self._zoom_request_callback = callback

    def mark_zoom_data_ready(self):
        self._zoom_data_requested = True

    def clear_zoom_request_state(self):
        self._zoom_data_requested = False

    def zoom_in(self):
        self._set_zoom_factor(self._zoom_factor * self._zoom_step)

    def zoom_out(self):
        self._set_zoom_factor(self._zoom_factor / self._zoom_step)

    def reset_zoom(self):
        self._set_zoom_factor(self._min_zoom)

    def set_blowup_action(self, callback=None, enabled=False, tooltip=None):
        self._blowup_callback = callback
        self._blowup_enabled = bool(enabled and callable(callback))
        if self._zoom_blowup_button is not None:
            if tooltip is not None:
                self._zoom_blowup_button.setToolTip(str(tooltip))
            self._zoom_blowup_button.setVisible(self._blowup_enabled)
        self._position_zoom_controls()

    def open_full_size_preview(self):
        if self._base_pixmap.isNull() or not self._blowup_enabled:
            return
        if callable(self._blowup_callback):
            self._blowup_callback()

    def set_decorate_pixmap_callback(self, callback):
        self._decorate_pixmap_callback = callback
        self._refresh_pixmap()

    def set_base_pixmap(self, pixmap, reset_zoom=True):
        if pixmap is None or pixmap.isNull():
            self._base_pixmap = QPixmap()
            self._render_pixmap = QPixmap()
            self._pan_offset = QPoint(0, 0)
            self._fit_scale = 1.0
            self._zoom_data_requested = False
            self._hide_zoom_controls()
            self.clear()
            return
        self._base_pixmap = pixmap
        if reset_zoom:
            self._zoom_factor = 1.0
            self._pan_offset = QPoint(0, 0)
            self._zoom_data_requested = False
        self._update_fit_scale()
        self._refresh_pixmap()

    def _clamp_pan_offset(self):
        if self._render_pixmap.isNull():
            self._pan_offset = QPoint(0, 0)
            return

        max_x = max(0, (self._render_pixmap.width() - self.width()) // 2)
        max_y = max(0, (self._render_pixmap.height() - self.height()) // 2)
        clamped_x = min(max(self._pan_offset.x(), -max_x), max_x)
        clamped_y = min(max(self._pan_offset.y(), -max_y), max_y)
        self._pan_offset = QPoint(clamped_x, clamped_y)

    def _can_pan(self):
        if self._render_pixmap.isNull():
            return False
        return self._render_pixmap.width() > self.width() or self._render_pixmap.height() > self.height()

    def _refresh_pixmap(self):
        if self._base_pixmap.isNull():
            self._render_pixmap = QPixmap()
            self._hide_zoom_controls()
            self.clear()
            return

        scale = self._fit_scale * self._zoom_factor
        width = max(1, int(self._base_pixmap.width() * scale))
        height = max(1, int(self._base_pixmap.height() * scale))
        pixmap = self._base_pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        if callable(self._decorate_pixmap_callback):
            pixmap = self._decorate_pixmap_callback(pixmap)

        self._render_pixmap = pixmap
        self._clamp_pan_offset()
        self._position_zoom_controls()
        self.setPixmap(self._render_pixmap)
        self.update()

    def paintEvent(self, event):
        if self._render_pixmap.isNull():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        origin_x, origin_y = self._get_render_origin()
        painter.drawPixmap(origin_x, origin_y, self._render_pixmap)
        painter.end()

    def resizeEvent(self, event):
        self._update_fit_scale()
        self._refresh_pixmap()
        super().resizeEvent(event)

    def enterEvent(self, event):
        self._show_zoom_controls()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._hide_zoom_controls()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        if self._base_pixmap.isNull():
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return

        if delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._can_pan():
            self._drag_active = True
            self._drag_last_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active and (event.buttons() & Qt.MouseButton.LeftButton):
            current_pos = event.position().toPoint()
            delta = current_pos - self._drag_last_pos
            self._drag_last_pos = current_pos
            self._pan_offset += delta
            self._clamp_pan_offset()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_active:
            self._drag_active = False
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._can_pan() else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._base_pixmap.isNull():
            self.reset_zoom()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MapWidget(QWebEngineView):
    """Leaflet.js-based map widget replacing tkintermapview."""

    copy_position = Signal(float, float)

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self._markers = []
        self._position = (0, 0)
        self._overlay = None
        self._logger = logger
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_map_context_menu)
        self._init_map()

    def _init_map(self):
        tile_url = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

        html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{{height:100%;margin:0;padding:0;}}</style>
</head><body>
<div id="map"></div>
<script>
var map = L.map('map').setView([0,0], 2);
L.tileLayer('{tile_url}', {{maxZoom:19, attribution:'&copy; OpenStreetMap contributors'}}).addTo(map);
var markers = [];
function clearMarkers() {{
    markers.forEach(function(m) {{ map.removeLayer(m); }});
    markers = [];
}}
function setPosition(lat, lng, addMarker) {{
    map.setView([lat, lng], 15);
    if (addMarker) {{
        var m = L.marker([lat, lng]).addTo(map);
        markers.push(m);
    }}
}}
function getPosition() {{
    var c = map.getCenter();
    return c.lat + ',' + c.lng;
}}
function getLatLngFromPoint(x, y) {{
    try {{
        var ll = map.containerPointToLatLng([x, y]);
        return ll.lat + ',' + ll.lng;
    }} catch(e) {{
        return '';
    }}
}}
</script>
</body></html>"""
        self.setHtml(html, QUrl("https://www.openstreetmap.org/"))

    def _show_map_context_menu(self, point):
        menu = QMenu(self)
        copy_action = menu.addAction("Copy GPS coordinates")
        selected_action = menu.exec(self.mapToGlobal(point))
        if selected_action == copy_action:
            self._copy_position_at_point(point)

    def _copy_position_at_point(self, point):
        js = "getLatLngFromPoint({}, {});".format(int(point.x()), int(point.y()))
        self.page().runJavaScript(js, 0, self._on_copy_position_result)

    def _on_copy_position_result(self, result):
        if not isinstance(result, str) or ',' not in result:
            if self._logger:
                self._logger.warning("GPS copy from map: unexpected JS result: %r", result)
            return
        try:
            lat_str, lng_str = result.split(',', 1)
            lat = float(lat_str)
            lng = float(lng_str)
        except (TypeError, ValueError):
            if self._logger:
                self._logger.warning("GPS copy from map: could not parse result as float: %r", result)
            return
        self._position = (lat, lng)
        QGuiApplication.clipboard().setText("{}, {}".format(lat, lng))
        self.copy_position.emit(lat, lng)

    def set_position(self, lat, lng, marker=True):
        self._position = (lat, lng)
        marker_str = "true" if marker else "false"
        self.page().runJavaScript(f"setPosition({lat}, {lng}, {marker_str});")

    def delete_all_marker(self):
        self._markers = []
        self.page().runJavaScript("clearMarkers();")

    def get_position(self, callback=None):
        """Get map center position. Returns cached position synchronously."""
        return self._position

    def set_overlay(self, widget):
        if self._overlay is not None and self._overlay is not widget:
            self._overlay.setParent(None)
        self._overlay = widget
        if widget is not None:
            widget.setParent(self)
            widget.raise_()
            self._position_overlay()

    def _position_overlay(self):
        if self._overlay is None:
            return
        margin = 10
        max_width = max(120, self.width() - 2 * margin)
        self._overlay.setMaximumWidth(max_width)
        self._overlay.adjustSize()
        x = max(margin, (self.width() - self._overlay.width()) // 2)
        self._overlay.move(x, margin)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlay()


class MapHintBubble(QFrame):
    """Dismissible banner shown over the map to surface a hidden interaction."""

    closed = Signal()

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setObjectName("MapHintBubble")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            #MapHintBubble {
                background-color: rgba(240, 128, 128, 235);
                border: 1px solid rgba(120, 30, 30, 180);
                border-radius: 10px;
            }
            #MapHintBubble QLabel {
                color: #2a0000;
                background: transparent;
                font-size: 14px;
                font-weight: 500;
            }
            #MapHintBubble QToolButton {
                background: transparent;
                color: #2a0000;
                border: none;
                padding: 0px 6px;
                font-weight: bold;
                font-size: 18px;
            }
            #MapHintBubble QToolButton:hover {
                color: #800000;
            }
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 8, 10)
        layout.setSpacing(8)

        self._label = QLabel(text)
        self._label.setWordWrap(True)
        layout.addWidget(self._label, stretch=1)

        self._close_button = QToolButton()
        self._close_button.setText("\u00d7")
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.setToolTip("Dismiss")
        self._close_button.clicked.connect(self._on_close_clicked)
        layout.addWidget(self._close_button, alignment=Qt.AlignmentFlag.AlignTop)

    def _on_close_clicked(self):
        self.hide()
        self.closed.emit()


class ThemedTitleBar(QWidget):
    """Cross-platform custom title bar used where native caption theming is unavailable."""

    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._dragging = False
        self._drag_offset = QPoint()

        self.setObjectName("AppTitleBar")
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 8, 4)
        layout.setSpacing(6)

        self.title_label = QLabel(window.windowTitle())
        self.title_label.setObjectName("AppTitleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.minimize_button = QPushButton()
        self.minimize_button.setObjectName("AppTitleButton")
        self.minimize_button.setToolTip("Minimize")
        self.minimize_button.clicked.connect(self._window.showMinimized)

        self.maximize_button = QPushButton()
        self.maximize_button.setObjectName("AppTitleButton")
        self.maximize_button.clicked.connect(self._toggle_maximize_restore)

        self.close_button = QPushButton()
        self.close_button.setObjectName("AppTitleCloseButton")
        self.close_button.setToolTip("Close")
        self.close_button.clicked.connect(self._window.close)

        for button in (self.minimize_button, self.maximize_button, self.close_button):
            button.setFixedSize(32, 24)
            button.setIconSize(QSize(12, 12))
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout.addWidget(self.title_label, stretch=1)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

        self._window.installEventFilter(self)
        self.sync_window_state()

    def _apply_titlebar_icons(self):
        icon_size = self.minimize_button.iconSize()
        style = self._window.style()

        def tint_if_needed(icon):
            if icon.isNull():
                return icon

            background = self.palette().color(QPalette.ColorRole.Window)
            if background.lightness() >= 128:
                return icon

            tint = self.palette().color(QPalette.ColorRole.WindowText).lighter(135)
            tinted_icon = QIcon()
            has_pixmap = False

            for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected, QIcon.Mode.Disabled):
                for state in (QIcon.State.Off, QIcon.State.On):
                    base_pixmap = icon.pixmap(icon_size, mode, state)
                    if base_pixmap.isNull():
                        continue

                    has_pixmap = True
                    tinted_pixmap = QPixmap(base_pixmap.size())
                    tinted_pixmap.fill(Qt.GlobalColor.transparent)

                    painter = QPainter(tinted_pixmap)
                    painter.drawPixmap(0, 0, base_pixmap)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    mode_tint = QColor(tint)
                    if mode == QIcon.Mode.Disabled:
                        mode_tint.setAlpha(130)
                    painter.fillRect(tinted_pixmap.rect(), mode_tint)
                    painter.end()

                    tinted_icon.addPixmap(tinted_pixmap, mode, state)

            return tinted_icon if has_pixmap else icon

        self.minimize_button.setIcon(tint_if_needed(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMinButton)))
        if self._window.isMaximized():
            self.maximize_button.setIcon(tint_if_needed(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarNormalButton)))
        else:
            self.maximize_button.setIcon(tint_if_needed(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMaxButton)))
        self.close_button.setIcon(tint_if_needed(style.standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton)))

    def _toggle_maximize_restore(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.sync_window_state()

    def sync_window_state(self):
        self._apply_titlebar_icons()
        if self._window.isMaximized():
            self.maximize_button.setToolTip("Restore")
        else:
            self.maximize_button.setToolTip("Maximize")

    def eventFilter(self, obj, event):
        if obj is self._window:
            if event.type() == QEvent.Type.WindowStateChange:
                self.sync_window_state()
            elif event.type() == QEvent.Type.WindowTitleChange:
                self.title_label.setText(self._window.windowTitle())
        return super().eventFilter(obj, event)

    def _is_over_button(self, event):
        child = self.childAt(event.position().toPoint())
        return isinstance(child, QPushButton)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._is_over_button(event):
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton and not self._window.isMaximized():
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._is_over_button(event):
            self._toggle_maximize_restore()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
