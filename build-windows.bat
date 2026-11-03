@echo off
rem Builds MusicMaid for Windows: release\MusicMaid-<ver>-windows-x64.zip (+ setup.exe if Inno Setup is installed)
rem Requirements: Python 3.10+ from python.org ("Add python.exe to PATH" ticked).
rem Optional: Inno Setup 6 (https://jrsoftware.org/isdl.php) for the installer.
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv-win\Scripts\python.exe (
    echo Creating build environment...
    %PY% -m venv .venv-win || goto :error
)
.venv-win\Scripts\python -m pip install --upgrade pip >nul
.venv-win\Scripts\python -m pip install ".[gui]" pyinstaller || goto :error
.venv-win\Scripts\python packaging\build.py --installer || goto :error
echo.
echo Self-test of the built app:
start /wait "" dist\MusicMaid\MusicMaid.exe --self-test
type "%TEMP%\musicmaid-selftest.txt"
echo.
echo Done. Your app is in the "release" folder (or run dist\MusicMaid\MusicMaid.exe directly).
pause
exit /b 0
:error
echo BUILD FAILED
pause
exit /b 1
