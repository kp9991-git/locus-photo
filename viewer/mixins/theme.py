from PySide6.QtGui import QPixmap, QFont, QIcon, QColor, QPainter
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QSplashScreen, QStyle

from viewer.core.constants import APP_NAME
from viewer.ui.styling import (
    SYSTEM_THEME,
    get_theme_settings, normalize_theme_choice,
    build_stylesheet, apply_native_titlebar_theme,
)

class ThemeMixin:

    def _get_system_theme_name(self):
        if self.app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
            return "dark"
        return "light"

    def _set_theme_colors(self, theme_name):
        self.theme_choice = normalize_theme_choice(theme_name)
        resolved_theme = self._get_system_theme_name() if self.theme_choice == SYSTEM_THEME else self.theme_choice
        self.theme_name, self.theme = get_theme_settings(resolved_theme)
        self.bg_color = self.theme["bg_color"]
        self.text_color = self.theme["text_color"]
        self.selected_color = self.theme["selected_color"]
        self.control_bg_color = self.theme["control_bg_color"]
        self.border_color = self.theme["border_color"]
        self.hover_bg_color = self.theme["hover_bg_color"]
        self.selection_bg_color = self.theme["selection_bg_color"]
        self.scrollbar_handle_color = self.theme["scrollbar_handle_color"]
        self.scrollbar_handle_hover_color = self.theme["scrollbar_handle_hover_color"]
        self.link_color = self.theme["link_color"]

    def _create_splash_screen(self):
        splash_width = 480
        splash_height = 240

        pixmap = QPixmap(splash_width, splash_height)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        frame_rect = pixmap.rect().adjusted(1, 1, -1, -1)
        background_color = QColor(self.control_bg_color)
        border_color = QColor(self.border_color)
        accent_color = QColor(self.selected_color)
        text_color = QColor(self.text_color)

        painter.setPen(border_color)
        painter.setBrush(background_color)
        painter.drawRoundedRect(frame_rect, 16, 16)

        accent_strip = frame_rect.adjusted(12, 12, -12, -frame_rect.height() + 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent_color)
        painter.drawRoundedRect(accent_strip, 6, 6)

        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(text_color)
        painter.drawText(frame_rect.adjusted(20, 56, -20, -96), Qt.AlignmentFlag.AlignCenter, APP_NAME)

        subtitle_font = QFont()
        subtitle_font.setPointSize(11)
        painter.setFont(subtitle_font)
        painter.drawText(
            frame_rect.adjusted(20, 112, -20, -72),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "Preparing your workspace...",
        )
        painter.end()

        self.splash = QSplashScreen(
            pixmap,
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint,
        )

        screen_geometry = self.app.primaryScreen().availableGeometry()
        splash_x = screen_geometry.x() + (screen_geometry.width() - splash_width) // 2
        splash_y = screen_geometry.y() + (screen_geometry.height() - splash_height) // 2
        self.splash.move(splash_x, splash_y)
        self.splash.show()

        self._update_splash("Starting...")

    def _update_splash(self, message):
        if self.splash is None:
            return
        self.splash.showMessage(
            str(message),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            QColor(self.text_color),
        )
        self.app.processEvents()

    def _get_button_icon(self, theme_icon_name, fallback_standard_pixmap):
        icon = QIcon.fromTheme(theme_icon_name)
        if icon.isNull():
            icon = self.app.style().standardIcon(fallback_standard_pixmap)
        return icon

    def _tint_icon_for_theme(self, icon, icon_size):
        if icon.isNull() or self.theme_name != "dark":
            return icon

        tint_color = QColor(self.text_color).lighter(135)
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
                mode_tint = QColor(tint_color)
                if mode == QIcon.Mode.Disabled:
                    mode_tint.setAlpha(130)
                painter.fillRect(tinted_pixmap.rect(), mode_tint)
                painter.end()

                tinted_icon.addPixmap(tinted_pixmap, mode, state)

        return tinted_icon if has_pixmap else icon

    def _apply_button_icons(self):
        icon_size = QSize(16, 16)

        if self.copy_to_clipboard_button is not None:
            copy_icon = self._get_button_icon("edit-copy", QStyle.StandardPixmap.SP_DialogSaveButton)
            self.copy_to_clipboard_button.setIcon(self._tint_icon_for_theme(copy_icon, icon_size))
            self.copy_to_clipboard_button.setIconSize(icon_size)

        if self.paste_from_clipboard_button is not None:
            paste_icon = self._get_button_icon("edit-paste", QStyle.StandardPixmap.SP_DialogOpenButton)
            self.paste_from_clipboard_button.setIcon(self._tint_icon_for_theme(paste_icon, icon_size))
            self.paste_from_clipboard_button.setIconSize(icon_size)

        if self.undo_gps_button is not None:
            undo_icon = self._get_button_icon("edit-undo", QStyle.StandardPixmap.SP_ArrowBack)
            undo_icon = self._tint_icon_for_theme(undo_icon, icon_size)
            self.undo_gps_button.setIcon(undo_icon)
            self.undo_gps_button.setIconSize(icon_size)
            if self.undo_gps_action is not None:
                self.undo_gps_action.setIcon(undo_icon)

        if self.redo_gps_button is not None:
            redo_icon = self._get_button_icon("edit-redo", QStyle.StandardPixmap.SP_ArrowForward)
            redo_icon = self._tint_icon_for_theme(redo_icon, icon_size)
            self.redo_gps_button.setIcon(redo_icon)
            self.redo_gps_button.setIconSize(icon_size)
            if self.redo_gps_action is not None:
                self.redo_gps_action.setIcon(redo_icon)

        if self.prev_page_button is not None:
            previous_icon = self._get_button_icon("go-previous", QStyle.StandardPixmap.SP_ArrowBack)
            self.prev_page_button.setIcon(self._tint_icon_for_theme(previous_icon, icon_size))
            self.prev_page_button.setIconSize(icon_size)

        if self.first_page_button is not None:
            first_icon = self._get_button_icon("go-first", QStyle.StandardPixmap.SP_MediaSkipBackward)
            self.first_page_button.setIcon(self._tint_icon_for_theme(first_icon, icon_size))
            self.first_page_button.setIconSize(icon_size)

        if self.next_page_button is not None:
            next_icon = self._get_button_icon("go-next", QStyle.StandardPixmap.SP_ArrowForward)
            self.next_page_button.setIcon(self._tint_icon_for_theme(next_icon, icon_size))
            self.next_page_button.setIconSize(icon_size)

        if self.last_page_button is not None:
            last_icon = self._get_button_icon("go-last", QStyle.StandardPixmap.SP_MediaSkipForward)
            self.last_page_button.setIcon(self._tint_icon_for_theme(last_icon, icon_size))
            self.last_page_button.setIconSize(icon_size)

        back_to_grid_button = getattr(self, "back_to_grid_button", None)
        if back_to_grid_button is not None:
            back_icon = self._get_button_icon("go-previous", QStyle.StandardPixmap.SP_ArrowBack)
            back_to_grid_button.setIcon(self._tint_icon_for_theme(back_icon, icon_size))
            back_to_grid_button.setIconSize(icon_size)

        if self.settings_button is not None:
            settings_icon = self._get_button_icon("emblem-system", QStyle.StandardPixmap.SP_FileDialogDetailedView)
            self.settings_button.setIcon(self._tint_icon_for_theme(settings_icon, icon_size))
            self.settings_button.setIconSize(icon_size)

    def _apply_theme_stylesheet(self):
        stylesheet = build_stylesheet(**self.theme)
        self.root.setStyleSheet(stylesheet)

        self._apply_button_icons()

        if self.photo_frame is not None:
            self.photo_frame.setStyleSheet(f"background-color: {self.bg_color};")

        for label in self.image_labels:
            self._apply_photo_label_decoration(label)

        self._apply_native_titlebar_theme()

    def _apply_native_titlebar_theme(self):
        if self.custom_title_bar is not None:
            self.custom_title_bar.sync_window_state()

        hwnd = int(self.root.winId())
        apply_native_titlebar_theme(
            hwnd, self.theme_name,
            self.control_bg_color, self.text_color, self.border_color,
            logger=self.logger,
        )

    def _on_system_color_scheme_changed(self, _color_scheme):
        if self.theme_choice == SYSTEM_THEME:
            self.select_theme(SYSTEM_THEME, persist_config=False)

    def select_theme(self, choice, persist_config=True):
        previous_choice = self.theme_choice
        previous_theme = self.theme_name
        self._set_theme_colors(choice)
        self._apply_theme_stylesheet()
        self._sync_theme_menu_selection()
        if persist_config and self.config.get('theme') != self.theme_choice:
            self.config['theme'] = self.theme_choice
            self.save_config()
        if self.logger and (previous_choice != self.theme_choice or previous_theme != self.theme_name):
            self.logger.info("Theme changed from {} ({}) to {} ({})".format(
                previous_choice, previous_theme, self.theme_choice, self.theme_name))
