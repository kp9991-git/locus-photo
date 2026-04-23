#!/usr/bin/env bash
set -e

APP_NAME="LocusPhoto"
ENTRYPOINT="main.py"
CONFIG_FILE=".locus-photo-config.yaml"
DIST_DIR="dist/release"
WORK_DIR="build/pyinstaller"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

REQUIRED_PACKAGES=(libxcb-cursor0)
MISSING=()
for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
        MISSING+=("$pkg")
    fi
done
if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Missing required system packages: ${MISSING[*]}"
    echo "Install them with: sudo apt install ${MISSING[*]}"
    exit 1
fi

rm -f "$WORK_DIR/$APP_NAME.spec"

source .venv/bin/activate || {
    echo "Failed to activate virtual environment from .venv/bin/activate"
    exit 1
}

python -m PyInstaller \
    --noconfirm \
    --clean \
    --onefile \
    --windowed \
    --specpath "$WORK_DIR" \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR" \
    --name "$APP_NAME" \
    --hidden-import PySide6.QtWebEngineCore \
    --hidden-import PySide6.QtWebEngineWidgets \
    --hidden-import PySide6.QtWebChannel \
    --add-data "$PROJECT_DIR/$CONFIG_FILE:." \
    --add-data "$PROJECT_DIR/LICENSE:." \
    --add-data "$PROJECT_DIR/NOTICE:." \
    --add-data "$PROJECT_DIR/THIRD_PARTY_LICENSES.txt:." \
    --add-data "$PROJECT_DIR/TERMS_OF_USE.txt:." \
    --add-data "$PROJECT_DIR/README.md:." \
    --add-binary "$PROJECT_DIR/exiftool/Unix/Image-ExifTool-13.55/exiftool:exiftool/Unix/Image-ExifTool-13.55" \
    --add-data "$PROJECT_DIR/exiftool/Unix/Image-ExifTool-13.55/lib:exiftool/Unix/Image-ExifTool-13.55/lib" \
    "$PROJECT_DIR/$ENTRYPOINT"

echo "Build succeeded. Output: $DIST_DIR/$APP_NAME"
