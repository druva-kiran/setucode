@echo off
setlocal
echo =================================================
echo     Installing SetuCode Globally (Windows)
echo =================================================

:: Check if uv is installed
where uv >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [!] 'uv' not found. Please install uv first:
    echo     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    exit /b 1
)

:: Sync dependencies
echo Syncing dependencies with uv...
call uv sync

:: Create batch wrapper
set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "BIN_DIR=%LOCALAPPDATA%\Microsoft\WindowsApps"
set "TARGET_BAT=%BIN_DIR%\setucode.bat"

if not exist "%VENV_PYTHON%" (
    echo [!] Virtual environment not found: %VENV_PYTHON%
    exit /b 1
)

if not exist "%BIN_DIR%" (
    mkdir "%BIN_DIR%"
)

echo @echo off > "%TARGET_BAT%"
echo set "WORKSPACE_ROOT=%%cd%%" >> "%TARGET_BAT%"
echo cd /d "%~dp0" >> "%TARGET_BAT%"
echo "%VENV_PYTHON%" -m dashboard.app %%* >> "%TARGET_BAT%"

echo.
echo ✓ SetuCode installed successfully!
echo   Location: %TARGET_BAT%
echo.
echo You can now run 'setucode' from any directory in your terminal.
pause
