from unittest.mock import MagicMock, patch

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPaintEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import QWidget

from viewer.ui.widgets import MapWidget, ThemedTitleBar, ZoomablePhotoLabel, pil_image_to_qpixmap


class _DummyWheelDelta:
    def __init__(self, value):
        self._value = value

    def y(self):
        return self._value


class _DummyWheelEvent:
    def __init__(self, delta):
        self._delta = delta
        self.accepted = False
        self.ignored = False

    def angleDelta(self):
        return _DummyWheelDelta(self._delta)

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


class _DummyWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._maximized = False
        self._minimized = False
        self._closed = False
        self._moved_to = QPoint(0, 0)
        self._frame_top_left = QPoint(50, 60)
        self.setWindowTitle("Initial")

    def isMaximized(self):
        return self._maximized

    def showMaximized(self):
        self._maximized = True

    def showNormal(self):
        self._maximized = False

    def showMinimized(self):
        self._minimized = True

    def close(self):
        self._closed = True

    def frameGeometry(self):
        class _Geometry:
            def __init__(self, top_left):
                self._top_left = top_left

            def topLeft(self):
                return self._top_left

        return _Geometry(self._frame_top_left)

    def move(self, point):
        self._moved_to = QPoint(point)


def test_pil_image_to_qpixmap_converts_rgba_image_without_resize(qapp):
    pil_img = Image.new("RGBA", (7, 5), color=(0, 120, 255, 200))

    pixmap = pil_image_to_qpixmap(pil_img)

    assert pixmap.width() == 7
    assert pixmap.height() == 5


def test_zoomable_set_decorate_callback_triggers_refresh(qapp):
    label = ZoomablePhotoLabel()
    label._refresh_pixmap = MagicMock()

    callback = lambda pixmap: pixmap
    label.set_decorate_pixmap_callback(callback)

    assert label._decorate_pixmap_callback == callback
    label._refresh_pixmap.assert_called_once()


def test_zoomable_set_base_pixmap_with_null_clears_state(qapp):
    label = ZoomablePhotoLabel()
    label._pan_offset = QPoint(12, 9)

    label.set_base_pixmap(QPixmap())

    assert label._base_pixmap.isNull() is True
    assert label._render_pixmap.isNull() is True
    assert label._pan_offset == QPoint(0, 0)


def test_zoomable_clamp_pan_offset_resets_when_render_is_null(qapp):
    label = ZoomablePhotoLabel()
    label._pan_offset = QPoint(99, -88)
    label._render_pixmap = QPixmap()

    label._clamp_pan_offset()

    assert label._pan_offset == QPoint(0, 0)
    assert label._can_pan() is False


def test_zoomable_refresh_applies_decorator_callback(qapp):
    label = ZoomablePhotoLabel()
    label.resize(180, 120)

    decorated = {}

    def decorate(pixmap):
        decorated["size"] = (pixmap.width(), pixmap.height())
        return pixmap

    label.set_decorate_pixmap_callback(decorate)
    label.set_base_pixmap(pil_image_to_qpixmap(Image.new("RGB", (90, 60), color=(20, 10, 5))))

    assert decorated["size"][0] > 0
    assert decorated["size"][1] > 0
    assert label.pixmap().isNull() is False


def test_zoomable_wheel_zero_delta_is_ignored(qapp):
    label = ZoomablePhotoLabel()
    label.set_base_pixmap(pil_image_to_qpixmap(Image.new("RGB", (80, 50), color=(10, 20, 30))))

    event = _DummyWheelEvent(0)
    label.wheelEvent(event)

    assert event.ignored is True
    assert event.accepted is False


def test_zoomable_hover_controls_visibility_and_labels(qapp):
    label = ZoomablePhotoLabel()
    label.resize(120, 90)
    label.show()
    qapp.processEvents()

    # Controls remain hidden until an image is set.
    label._show_zoom_controls()
    assert label._zoom_controls.isVisible() is False

    label.set_base_pixmap(pil_image_to_qpixmap(Image.new("RGB", (80, 50), color=(5, 6, 7))))
    assert label._zoom_out_button.text() == "-"
    assert label._zoom_reset_button.text() == "fit"
    assert label._zoom_in_button.text() == "+"
    assert label._zoom_blowup_button.text() == "[]"
    assert "courier" in label._zoom_in_button.font().family().lower()
    assert label._zoom_blowup_button.isVisible() is False

    label._show_zoom_controls()
    assert label._zoom_controls.isVisible() is True

    label._hide_zoom_controls()
    assert label._zoom_controls.isVisible() is False


def test_zoomable_hover_control_buttons_update_zoom(qapp):
    label = ZoomablePhotoLabel()
    label.resize(120, 90)
    label.set_base_pixmap(pil_image_to_qpixmap(Image.new("RGB", (80, 50), color=(10, 11, 12))))

    initial_zoom = label._zoom_factor
    label._zoom_in_button.click()
    assert label._zoom_factor > initial_zoom

    label._zoom_out_button.click()
    assert label._zoom_factor >= 1.0

    label._zoom_in_button.click()
    label._zoom_reset_button.click()
    assert label._zoom_factor == 1.0


def test_zoomable_blowup_button_triggers_grid_callback_when_enabled(qapp):
    label = ZoomablePhotoLabel()
    label.resize(160, 120)
    label.set_base_pixmap(pil_image_to_qpixmap(Image.new("RGB", (80, 50), color=(20, 30, 40))))

    callback = MagicMock()
    label.set_blowup_action(callback=callback, enabled=True, tooltip="Back to grid")
    assert label._zoom_blowup_button.isHidden() is False
    assert label._zoom_blowup_button.toolTip() == "Back to grid"
    label._zoom_blowup_button.click()
    callback.assert_called_once()

    callback.reset_mock()
    label.set_blowup_action(callback=callback, enabled=False)
    assert label._zoom_blowup_button.isVisible() is False
    label.open_full_size_preview()
    callback.assert_not_called()


def test_zoomable_hover_controls_anchor_to_rendered_image_top_right(qapp):
    label = ZoomablePhotoLabel()
    label.resize(200, 160)
    label.show()
    qapp.processEvents()
    label.set_base_pixmap(pil_image_to_qpixmap(Image.new("RGB", (80, 40), color=(13, 14, 15))))

    label._show_zoom_controls()
    qapp.processEvents()

    inset = 6
    render_w = label._render_pixmap.width()
    render_h = label._render_pixmap.height()
    controls_w = label._zoom_controls.width()
    controls_h = label._zoom_controls.height()
    origin_x = (label.width() - render_w) // 2 + label._pan_offset.x()
    origin_y = (label.height() - render_h) // 2 + label._pan_offset.y()

    expected_x = origin_x + render_w - controls_w - inset
    expected_y = origin_y + inset
    expected_x = min(max(0, expected_x), max(0, label.width() - controls_w))
    expected_y = min(max(0, expected_y), max(0, label.height() - controls_h))

    assert label._zoom_controls.pos().x() == expected_x
    assert label._zoom_controls.pos().y() == expected_y


def test_mapwidget_init_map_sets_html_with_expected_tile_source():
    dummy = type("DummyMap", (), {"setHtml": MagicMock()})()

    MapWidget._init_map(dummy)

    html, base_url = dummy.setHtml.call_args.args
    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in html
    assert "getLatLngFromPoint" in html
    assert base_url.toString() == "https://www.openstreetmap.org/"


def test_mapwidget_show_context_menu_calls_copy_on_selected_action():
    copy_calls = []
    point = QPoint(12, 7)

    dummy = type(
        "DummyMap",
        (),
        {
            "mapToGlobal": lambda self, p: p,
            "_copy_position_at_point": lambda self, p: copy_calls.append((p.x(), p.y())),
        },
    )()

    menu = MagicMock()
    copy_action = object()
    menu.addAction.return_value = copy_action
    menu.exec.return_value = copy_action

    with patch("viewer.ui.widgets.QMenu", return_value=menu):
        MapWidget._show_map_context_menu(dummy, point)

    assert copy_calls == [(12, 7)]


def test_mapwidget_show_context_menu_noop_when_other_action_selected():
    copy_calls = []
    point = QPoint(2, 3)

    dummy = type(
        "DummyMap",
        (),
        {
            "mapToGlobal": lambda self, p: p,
            "_copy_position_at_point": lambda self, p: copy_calls.append((p.x(), p.y())),
        },
    )()

    menu = MagicMock()
    copy_action = object()
    menu.addAction.return_value = copy_action
    menu.exec.return_value = object()

    with patch("viewer.ui.widgets.QMenu", return_value=menu):
        MapWidget._show_map_context_menu(dummy, point)

    assert copy_calls == []


def test_mapwidget_copy_position_at_point_builds_expected_js_call():
    page = MagicMock()
    dummy = type("DummyMap", (), {"page": lambda self: page, "_on_copy_position_result": object()})()

    MapWidget._copy_position_at_point(dummy, QPoint(21, 42))

    js, callback = page.runJavaScript.call_args.args
    assert js == "getLatLngFromPoint(21, 42);"
    assert callback is dummy._on_copy_position_result


def test_mapwidget_set_position_and_delete_marker_execute_js_and_update_cache():
    page = MagicMock()
    dummy = type("DummyMap", (), {"_position": (0.0, 0.0), "_markers": [1], "page": lambda self: page})()

    MapWidget.set_position(dummy, 3.5, -9.25, marker=False)
    MapWidget.delete_all_marker(dummy)

    assert dummy._position == (3.5, -9.25)
    assert dummy._markers == []
    assert page.runJavaScript.call_args_list[0].args[0] == "setPosition(3.5, -9.25, false);"
    assert page.runJavaScript.call_args_list[1].args[0] == "clearMarkers();"


def test_mapwidget_copy_result_ignores_wrong_length_payload(qapp):
    dummy = type("DummyMap", (), {"_position": (4.0, 5.0)})()

    MapWidget._on_copy_position_result(dummy, [1.0])

    assert dummy._position == (4.0, 5.0)


def test_titlebar_toggle_and_sync_window_state_updates_tooltip(qapp):
    window = _DummyWindow()
    titlebar = ThemedTitleBar(window)

    window._maximized = False
    titlebar._toggle_maximize_restore()
    assert window.isMaximized() is True
    assert titlebar.maximize_button.toolTip() == "Restore"

    titlebar._toggle_maximize_restore()
    assert window.isMaximized() is False
    assert titlebar.maximize_button.toolTip() == "Maximize"


def test_titlebar_apply_icons_handles_dark_palette_tint_path(qapp):
    window = _DummyWindow()
    titlebar = ThemedTitleBar(window)

    icon = QIcon(QPixmap(16, 16))
    style_mock = MagicMock()
    style_mock.standardIcon.return_value = icon
    with patch.object(window, "style", return_value=style_mock):
        dark_palette = MagicMock()

        def color_for_role(role):
            if role.name == "Window":
                return QColor(20, 20, 20)
            if role.name == "WindowText":
                return QColor(240, 240, 240)
            return QColor(128, 128, 128)

        dark_palette.color.side_effect = color_for_role
        with patch.object(titlebar, "palette", return_value=dark_palette):
            titlebar._apply_titlebar_icons()

    assert titlebar.minimize_button.icon().isNull() is False
    assert titlebar.maximize_button.icon().isNull() is False
    assert titlebar.close_button.icon().isNull() is False


def test_titlebar_apply_icons_handles_null_icon_path(qapp):
    window = _DummyWindow()
    titlebar = ThemedTitleBar(window)

    style_mock = MagicMock()
    style_mock.standardIcon.return_value = QIcon()
    with patch.object(window, "style", return_value=style_mock):
        titlebar._apply_titlebar_icons()

    assert titlebar.minimize_button.icon().isNull() is True


def test_titlebar_event_filter_updates_on_state_and_title_change(qapp):
    window = _DummyWindow()
    titlebar = ThemedTitleBar(window)

    titlebar.sync_window_state = MagicMock()
    titlebar.eventFilter(window, QEvent(QEvent.Type.WindowStateChange))
    titlebar.sync_window_state.assert_called_once()

    window.setWindowTitle("Renamed")
    titlebar.eventFilter(window, QEvent(QEvent.Type.WindowTitleChange))
    assert titlebar.title_label.text() == "Renamed"


def test_titlebar_drag_mouse_events_move_window_when_not_maximized(qapp):
    window = _DummyWindow()
    titlebar = ThemedTitleBar(window)
    titlebar._is_over_button = lambda event: False

    press_event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        QPointF(90, 100),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    titlebar.mousePressEvent(press_event)
    assert titlebar._dragging is True

    move_event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(20, 20),
        QPointF(20, 20),
        QPointF(120, 130),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    titlebar.mouseMoveEvent(move_event)
    assert window._moved_to == QPoint(80, 90)

    release_event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(20, 20),
        QPointF(20, 20),
        QPointF(120, 130),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    titlebar.mouseReleaseEvent(release_event)
    assert titlebar._dragging is False


def test_titlebar_fallback_event_paths_do_not_crash(qapp):
    window = _DummyWindow()
    titlebar = ThemedTitleBar(window)
    titlebar._is_over_button = lambda event: True

    press_event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        QPointF(90, 100),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    titlebar.mousePressEvent(press_event)

    window._maximized = True
    titlebar._dragging = True
    move_event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(20, 20),
        QPointF(20, 20),
        QPointF(120, 130),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    titlebar.mouseMoveEvent(move_event)

    dbl_click = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(10, 10),
        QPointF(10, 10),
        QPointF(95, 95),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    titlebar.mouseDoubleClickEvent(dbl_click)


def test_titlebar_double_click_toggles_when_not_over_button(qapp):
    window = _DummyWindow()
    titlebar = ThemedTitleBar(window)
    titlebar._is_over_button = lambda event: False
    titlebar._toggle_maximize_restore = MagicMock()

    dbl_click = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(10, 10),
        QPointF(10, 10),
        QPointF(95, 95),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    titlebar.mouseDoubleClickEvent(dbl_click)

    titlebar._toggle_maximize_restore.assert_called_once()


def test_titlebar_is_over_button_checks_child_widget_type(qapp):
    window = _DummyWindow()
    titlebar = ThemedTitleBar(window)

    event = MagicMock()
    event.position.return_value.toPoint.return_value = QPoint(1, 1)

    with patch.object(titlebar, "childAt", return_value=titlebar.minimize_button):
        assert titlebar._is_over_button(event) is True

    with patch.object(titlebar, "childAt", return_value=window):
        assert titlebar._is_over_button(event) is False


def test_zoomable_paint_resize_and_mouse_fallback_paths(qapp):
    label = ZoomablePhotoLabel()
    label.resize(100, 80)

    label.paintEvent(QPaintEvent(label.rect()))
    label.resizeEvent(QResizeEvent(label.size(), label.size()))

    press_event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5, 5),
        QPointF(5, 5),
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    label.mousePressEvent(press_event)

    move_event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(7, 7),
        QPointF(7, 7),
        QPointF(7, 7),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    label.mouseMoveEvent(move_event)

    release_event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(7, 7),
        QPointF(7, 7),
        QPointF(7, 7),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    label.mouseReleaseEvent(release_event)

    dbl_click = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(8, 8),
        QPointF(8, 8),
        QPointF(8, 8),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    label.mouseDoubleClickEvent(dbl_click)
