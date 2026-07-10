@echo off
echo === Building VB Player v0.7.0 ===

echo Step 1: PyInstaller packaging...
call .venv\Scripts\python.exe -m PyInstaller --noconfirm --name "VB Player" --windowed --add-data "audio_player/ui/themes;audio_player/ui/themes" --add-data "audio_player/i18n;audio_player/i18n" --hidden-import audio_player.platform.windows.asio_ctypes main.py
if %errorlevel% neq 0 (
    echo PyInstaller build failed!
    exit /b 1
)

echo.
echo Step 2: Inno Setup installer...
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
if %errorlevel% neq 0 (
    echo Inno Setup build failed!
    exit /b 1
)

echo.
echo === Build complete! ===
echo Output files in dist\ and current directory
dir /b VB-Player-*.exe 2>nul
