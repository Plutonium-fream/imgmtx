@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m imgmtx
    exit /b
)

rem Codex includes a local Python runtime with Pillow and Tkinter.
set "IMGM_TX_RUNTIME=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python"
if exist "%IMGM_TX_RUNTIME%\pythonw.exe" (
    start "" "%IMGM_TX_RUNTIME%\pythonw.exe" -m imgmtx
    exit /b
)

py -3 -c "import tkinter; from PIL import Image" >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 -m imgmtx
    exit /b
)

python -c "import tkinter; from PIL import Image" >nul 2>nul
if not errorlevel 1 (
    start "" pythonw -m imgmtx
    exit /b
)

echo ImgMtx requires Python 3.10+ with Tkinter and Pillow.
echo Install Python from python.org, then run:
echo   py -3 -m pip install -r requirements.txt
echo Double-click this launcher again after installation.
pause
