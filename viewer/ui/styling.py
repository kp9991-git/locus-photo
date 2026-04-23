import platform


DEFAULT_THEME = "dark"
SYSTEM_THEME = "system"

THEME_PRESETS = {
    "dark": {
        "bg_color": "#2b2b2b",
        "text_color": "#dce4ee",
        "selected_color": "#1f6aa5",
        "control_bg_color": "#343638",
        "border_color": "#565b5e",
        "hover_bg_color": "#383a3c",
        "selection_bg_color": "#14375e",
        "scrollbar_handle_color": "#565b5e",
        "scrollbar_handle_hover_color": "#686d71",
        "link_color": "#7ecbff",
    },
    "gray": {
        "bg_color": "#d9dcdf",
        "text_color": "#1f2328",
        "selected_color": "#4f6f95",
        "control_bg_color": "#eceef1",
        "border_color": "#aab2bc",
        "hover_bg_color": "#d2d7dd",
        "selection_bg_color": "#bcc7d3",
        "scrollbar_handle_color": "#9ca6b2",
        "scrollbar_handle_hover_color": "#8e99a7",
        "link_color": "#2f6ea2",
    },
    "light": {
        "bg_color": "#f5f6f7",
        "text_color": "#202124",
        "selected_color": "#1a73e8",
        "control_bg_color": "#ffffff",
        "border_color": "#c9ced6",
        "hover_bg_color": "#e9edf3",
        "selection_bg_color": "#d2e3fc",
        "scrollbar_handle_color": "#b8c0cc",
        "scrollbar_handle_hover_color": "#9ea8b5",
        "link_color": "#1a73e8",
    },
}

THEME_ALIASES = {
    "forest": "gray",
}


def get_theme_settings(theme_name):
    theme_key = str(theme_name).strip().lower() if theme_name is not None else DEFAULT_THEME
    theme_key = THEME_ALIASES.get(theme_key, theme_key)
    if theme_key not in THEME_PRESETS:
        theme_key = DEFAULT_THEME
    return theme_key, THEME_PRESETS[theme_key]


def normalize_theme_choice(theme_name):
    theme_key = str(theme_name).strip().lower() if theme_name is not None else DEFAULT_THEME
    theme_key = THEME_ALIASES.get(theme_key, theme_key)
    if theme_key == SYSTEM_THEME:
        return SYSTEM_THEME
    if theme_key not in THEME_PRESETS:
        return DEFAULT_THEME
    return theme_key


def hex_to_colorref(color):
    if not isinstance(color, str):
        return 0
    value = color.strip().lstrip("#")
    if len(value) != 6:
        return 0
    try:
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
    except ValueError:
        return 0
    return (blue << 16) | (green << 8) | red


def build_stylesheet(bg_color, text_color, selected_color, control_bg_color,
                     border_color, hover_bg_color, selection_bg_color,
                     scrollbar_handle_color, scrollbar_handle_hover_color,
                     link_color):
    return f"""
        QMainWindow, QWidget {{
            background-color: {bg_color};
            color: {text_color};
        }}
        QPushButton {{
            font-size: 13px;
            padding: 6px 16px;
            min-height: 24px;
        }}
        QToolButton {{
            font-size: 13px;
            padding: 6px 16px;
            min-height: 24px;
            background-color: {control_bg_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 6px;
        }}
        QToolButton:hover {{
            border: 1px solid {selected_color};
            background-color: {hover_bg_color};
        }}
        QToolButton::menu-indicator {{
            image: none;
            width: 0px;
        }}
        QComboBox {{
            background-color: {control_bg_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 13px;
            min-height: 28px;
        }}
        QComboBox:hover {{
            border: 1px solid {selected_color};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 28px;
            border-left: 1px solid {border_color};
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid {text_color};
            margin-right: 8px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {control_bg_color};
            color: {text_color};
            selection-background-color: {selected_color};
            border: 1px solid {border_color};
            border-radius: 4px;
            padding: 4px;
            outline: none;
        }}
        QMenu {{
            background-color: {control_bg_color};
            color: {text_color};
            border: 1px solid {border_color};
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 20px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {hover_bg_color};
        }}
        QMenu::separator {{
            height: 1px;
            background: {border_color};
            margin: 4px 6px;
        }}
        QToolTip {{
            background-color: {control_bg_color};
            color: {text_color};
            border: 1px solid {border_color};
            padding: 4px 6px;
        }}
        QTreeWidget {{
            background-color: {bg_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 6px;
            padding: 4px;
            font-size: 13px;
        }}
        QTreeWidget::item {{
            padding: 3px 0px;
        }}
        QTreeWidget::item:selected {{
            background-color: {selection_bg_color};
            color: {text_color};
            border-radius: 4px;
        }}
        QTreeWidget::item:hover {{
            background-color: {hover_bg_color};
        }}
        QScrollBar:vertical {{
            background-color: {bg_color};
            width: 12px;
            border-radius: 6px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {scrollbar_handle_color};
            border-radius: 5px;
            min-height: 30px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {scrollbar_handle_hover_color};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QDialog {{
            background-color: {bg_color};
            color: {text_color};
        }}
        QTextEdit {{
            background-color: {control_bg_color};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 6px;
            padding: 4px;
            font-size: 13px;
        }}
        QLabel {{
            background-color: transparent;
        }}
        QLabel[linkLabel="true"] {{
            color: {link_color};
        }}
        QWidget#AppTitleBar {{
            background-color: {control_bg_color};
            border-bottom: 1px solid {border_color};
        }}
        QLabel#AppTitleLabel {{
            color: {text_color};
            font-size: 13px;
            font-weight: 600;
        }}
        QPushButton#AppTitleButton {{
            background-color: transparent;
            color: {text_color};
            border: 1px solid transparent;
            border-radius: 6px;
            min-width: 32px;
            max-width: 32px;
            min-height: 24px;
            max-height: 24px;
            padding: 0px;
            font-size: 13px;
        }}
        QPushButton#AppTitleButton:hover {{
            background-color: {hover_bg_color};
            border: 1px solid {border_color};
        }}
        QPushButton#AppTitleCloseButton {{
            background-color: transparent;
            color: {text_color};
            border: 1px solid transparent;
            border-radius: 6px;
            min-width: 32px;
            max-width: 32px;
            min-height: 24px;
            max-height: 24px;
            padding: 0px;
            font-size: 13px;
        }}
        QPushButton#AppTitleCloseButton:hover {{
            background-color: #b3261e;
            color: #ffffff;
            border: 1px solid #b3261e;
        }}
    """


def apply_native_titlebar_theme(hwnd, theme_name, control_bg_color, text_color, border_color, logger=None):
    if platform.system() != "Windows":
        return

    try:
        import ctypes
        from ctypes import wintypes

        dwmapi = ctypes.windll.dwmapi

        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWA_BORDER_COLOR = 34
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMWA_USE_IMMERSIVE_DARK_MODE_FALLBACK = 19
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20

        DWMWCP_ROUND = 2
        DWMSBT_MAINWINDOW = 2

        def set_dwm_attribute(attr, value):
            value_ref = ctypes.c_int(value)
            dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_uint(attr),
                ctypes.byref(value_ref),
                ctypes.sizeof(value_ref),
            )

        is_dark_mode = 1 if theme_name == "dark" else 0
        caption_color = hex_to_colorref(control_bg_color)
        text_color_ref = hex_to_colorref(text_color)
        border_color_ref = hex_to_colorref(border_color)

        set_dwm_attribute(DWMWA_USE_IMMERSIVE_DARK_MODE_FALLBACK, is_dark_mode)
        set_dwm_attribute(DWMWA_USE_IMMERSIVE_DARK_MODE, is_dark_mode)
        set_dwm_attribute(DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
        set_dwm_attribute(DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_MAINWINDOW)
        set_dwm_attribute(DWMWA_CAPTION_COLOR, caption_color)
        set_dwm_attribute(DWMWA_TEXT_COLOR, text_color_ref)
        set_dwm_attribute(DWMWA_BORDER_COLOR, border_color_ref)
    except Exception as e:
        if logger:
            logger.debug("Could not apply native title bar theme: {}".format(e))
