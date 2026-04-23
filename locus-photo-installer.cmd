@echo off
setlocal

set "APP_NAME=LocusPhoto"
set "ENTRYPOINT=main.py"
set "CONFIG_FILE=.locus-photo-config.yaml"
set "DIST_DIR=dist\release"
set "WORK_DIR=build\pyinstaller"
set "PROJECT_DIR=%~dp0"

if exist "%WORK_DIR%\%APP_NAME%.spec" del /q "%WORK_DIR%\%APP_NAME%.spec"

call .venv\Scripts\activate.bat
if errorlevel 1 (
	echo Failed to activate virtual environment from .venv\Scripts\activate.bat
	exit /b 1
)

python -m PyInstaller ^
	--noconfirm ^
	--clean ^
	--onefile ^
	--windowed ^
	--specpath "%WORK_DIR%" ^
	--distpath "%DIST_DIR%" ^
	--workpath "%WORK_DIR%" ^
	--name "%APP_NAME%" ^
	--hidden-import PySide6.QtWebEngineCore ^
	--hidden-import PySide6.QtWebEngineWidgets ^
	--hidden-import PySide6.QtWebChannel ^
	--add-data "%PROJECT_DIR%%CONFIG_FILE%;." ^
	--add-data "%PROJECT_DIR%LICENSE;." ^
	--add-data "%PROJECT_DIR%NOTICE;." ^
	--add-data "%PROJECT_DIR%THIRD_PARTY_LICENSES.txt;." ^
	--add-data "%PROJECT_DIR%TERMS_OF_USE.txt;." ^
	--add-data "%PROJECT_DIR%README.md;." ^
	--add-binary "%PROJECT_DIR%exiftool\Windows\exiftool-13.55_64\exiftool.exe;exiftool\Windows\exiftool-13.55_64" ^
	--add-data "%PROJECT_DIR%exiftool\Windows\exiftool-13.55_64\exiftool_files;exiftool\Windows\exiftool-13.55_64\exiftool_files" ^
	"%PROJECT_DIR%%ENTRYPOINT%"

if errorlevel 1 (
	echo Build failed. Ensure PyInstaller is installed in the active environment: pip install pyinstaller
	exit /b 1
)

echo Build succeeded. Output: %DIST_DIR%\%APP_NAME%.exe