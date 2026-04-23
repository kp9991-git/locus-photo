"""Dialogs used by the application (About, Feedback, Terms acceptance)."""

import os
import sys

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from viewer.core.constants import APP_NAME, APP_RELEASE


TERMS_VERSION = 1
TERMS_FILENAME = "TERMS_OF_USE.txt"

# Minimal fallback shown only if the bundled TERMS_OF_USE.txt is missing
# (e.g. corrupt install). The canonical text lives in TERMS_OF_USE.txt.
_TERMS_FALLBACK = (
    "{app} — Terms of Use could not be loaded.\n\n"
    "This software is provided AS IS, without warranty of any kind. The authors "
    "are not liable for any data loss, file corruption, or damages arising from "
    "its use. You are responsible for maintaining backups. Use at your own risk.\n\n"
    "Please reinstall the software or see the TERMS_OF_USE.txt file distributed "
    "with it for the full terms."
).format(app=APP_NAME)


def _resolve_terms_path():
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
        return os.path.join(base, TERMS_FILENAME)
    # viewer/ui/dialogs.py -> project root is three levels up.
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(project_root, TERMS_FILENAME)


def load_terms_text():
    path = _resolve_terms_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return _TERMS_FALLBACK


TERMS_OF_USE = load_terms_text()


def _build_terms_scroll_area(font):
    terms_label = QLabel(TERMS_OF_USE)
    terms_label.setFont(font)
    terms_label.setWordWrap(True)
    terms_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    terms_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    container = QWidget()
    container_layout = QVBoxLayout(container)
    container_layout.setContentsMargins(12, 12, 12, 12)
    container_layout.addWidget(terms_label)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(container)
    return scroll


class AboutDialog(QDialog):

    def __init__(self, parent, link_color="#3a96dd"):
        super().__init__(parent)
        self.setWindowTitle("About")
        self.resize(720, 560)

        parent_geo = parent.geometry()
        x = parent_geo.x() + (parent_geo.width() // 2) - 360
        y = parent_geo.y() + (parent_geo.height() // 2) - 280
        self.move(x, y)

        layout = QVBoxLayout(self)

        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label = QLabel("{} {}".format(APP_NAME, APP_RELEASE))
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        body_font = QFont()
        body_font.setPointSize(9)
        layout.addWidget(_build_terms_scroll_area(body_font))

        EXIFTOOL_LICENCE_LINK = "https://www.exiftool.org/index.html#license"
        exiftool_label = QLabel("This software contains the ExifTool created by Phil Harvey.")
        exiftool_label.setFont(body_font)
        exiftool_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(exiftool_label)
        exiftool_link = QLabel(
            f'<a href="{EXIFTOOL_LICENCE_LINK}" style="color: {link_color}; text-decoration: underline;">'
            f'{EXIFTOOL_LICENCE_LINK}</a>'
        )
        exiftool_link.setFont(body_font)
        exiftool_link.setProperty("linkLabel", True)
        exiftool_link.setStyleSheet(f"QLabel {{ color: {link_color}; }} QLabel a {{ color: {link_color}; }}")
        exiftool_link.setOpenExternalLinks(True)
        exiftool_link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(exiftool_link)

        MAP_LINK = "https://www.openstreetmap.org/copyright"
        map_label = QLabel("This software uses OpenStreetMap.")
        map_label.setFont(body_font)
        map_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(map_label)
        map_link = QLabel(
            f'<a href="{MAP_LINK}" style="color: {link_color}; text-decoration: underline;">'
            f'{MAP_LINK}</a>'
        )
        map_link.setFont(body_font)
        map_link.setProperty("linkLabel", True)
        map_link.setStyleSheet(f"QLabel {{ color: {link_color}; }} QLabel a {{ color: {link_color}; }}")
        map_link.setOpenExternalLinks(True)
        map_link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(map_link)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)


class TermsAcceptanceDialog(QDialog):
    """First-run modal that requires the user to accept the Terms of Use.

    exec() returns QDialog.Accepted if the user accepted; QDialog.Rejected otherwise
    (including closing the window via the title bar).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("{} — Terms of Use".format(APP_NAME))
        self.setModal(True)
        self.resize(720, 600)
        # Prevent dismissal via Escape; force an explicit choice.
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        if parent is not None:
            parent_geo = parent.geometry()
            x = parent_geo.x() + (parent_geo.width() // 2) - 360
            y = parent_geo.y() + (parent_geo.height() // 2) - 300
            self.move(x, y)

        layout = QVBoxLayout(self)

        heading_font = QFont()
        heading_font.setPointSize(11)
        heading_font.setBold(True)
        heading = QLabel("Please review and accept the Terms of Use to continue.")
        heading.setFont(heading_font)
        heading.setWordWrap(True)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)

        body_font = QFont()
        body_font.setPointSize(9)
        layout.addWidget(_build_terms_scroll_area(body_font))

        button_row = QHBoxLayout()
        decline_button = QPushButton("Decline and Exit")
        decline_button.clicked.connect(self.reject)
        accept_button = QPushButton("I Accept")
        accept_button.setDefault(True)
        accept_button.clicked.connect(self.accept)
        button_row.addStretch(1)
        button_row.addWidget(decline_button)
        button_row.addWidget(accept_button)
        layout.addLayout(button_row)

    def keyPressEvent(self, event):
        # Block Escape from rejecting; require explicit button click.
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)
