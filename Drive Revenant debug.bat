@echo off
REM Drive Revenant debug.bat
REM Version: 2.0.0
REM Enhanced debug launcher with comprehensive error handling, new CLI options, and improved diagnostics.

echo ========================================
echo    Drive Revenant DEBUG Launcher v2.0
echo ========================================
echo.
echo Enhanced debugging with new CLI options and improved error handling
echo.

REM Ensure we are in the script directory
pushd "%~dp0" >nul

REM Check if Python is available
echo [1/8] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.11 or later from python.org
    echo.
    pause
    popd >nul
    exit /b 1
)
echo Python available:
python --version
echo.

REM Clear Python cache files to prevent stale code issues
echo [2/8] Clearing Python cache files...
if exist __pycache__ (
    echo   Removing __pycache__ directories...
    for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
)
if exist *.pyc (
    echo   Removing .pyc files...
    del /s /q *.pyc 2>nul
)
echo   Cache cleared.
echo.

REM Clear any existing log files that might be causing issues
echo [3/8] Cleaning up log files...
if exist logs\debug.log (
    echo   Clearing debug log...
    del /q logs\debug.log 2>nul
)
if exist logs\Log_current.txt (
    echo   Clearing current log...
    del /q logs\Log_current.txt 2>nul
)
if exist logs\events.ndjson (
    echo   Clearing events log...
    del /q logs\events.ndjson 2>nul
)
echo   Log cleanup completed.
echo.

REM Check for PySide6 and install if needed
echo [4/8] Checking PySide6 installation...
python -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo   PySide6 not found. Installing requirements...
    if exist requirements.txt (
        echo   Installing from requirements.txt...
        pip install -r requirements.txt
        if errorlevel 1 (
            echo ERROR: Failed to install required packages
            echo Try: pip install -r requirements.txt --user
            echo.
            pause
            popd >nul
            exit /b 1
        )
        echo   Requirements installed successfully.
    ) else (
        echo WARNING: requirements.txt not found; attempting direct PySide6 install...
        pip install PySide6 pyyaml
        if errorlevel 1 (
            echo ERROR: Failed to install PySide6
            echo Try: pip install PySide6 --user
            echo.
            pause
            popd >nul
            exit /b 1
        )
    )
) else (
    echo   PySide6 is available.
)
echo.

REM Verify core modules can be imported
echo [5/8] Verifying application modules...
python -c "import app_config, app_core, app_io, app_logging" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Failed to import core application modules
    echo This may indicate missing dependencies or code issues
    echo.
    pause
    popd >nul
    exit /b 1
)
echo   Core modules imported successfully.
echo.

REM Check for main.py
echo [6/8] Checking application files...
if not exist main.py (
    echo ERROR: main.py not found in current directory
    echo Please ensure you are running this from the Drive Revenant directory
    echo.
    pause
    popd >nul
    exit /b 1
)
echo   Application files found.
echo.

REM Check config file and show info
echo [7/8] Checking configuration...
if not exist config.json (
    echo WARNING: config.json not found - will create default config
) else (
    echo   Configuration file found.
    echo   Use --config-info to inspect current configuration
)
echo.

REM Show available debug options
echo [8/8] Starting Drive Revenant in DEBUG mode...
echo   Available options: --debug, --config-info, --fix-autostart
echo   Launching with arguments: --debug %*
echo.
echo ========================================
echo   DEBUG MODE - Application Starting...
echo ========================================
echo.
echo   Watch this window for debug output and boot banner...
echo   GUI will open in a separate window.
echo   Press Ctrl+C to stop the application.
echo.
echo   NEW FEATURES:
echo   - Boot banner shows config path and SHA256 hash
echo   - Dual-file guard warns if both portable and AppData configs exist
echo   - --config-info shows resolved configuration
echo   - Scheduler banner shows timing settings
echo.

python main.py --debug %*
set EXITCODE=%ERRORLEVEL%

echo.
echo ========================================
if %EXITCODE%==0 (
    echo   Application exited normally
    echo.
    echo   SUCCESS: Drive Revenant ran without errors
) else (
    echo   Application exited with error code %EXITCODE%
    echo.
    echo   DEBUGGING INFORMATION:
    echo   =====================
    echo   1. Check the debug log: logs\debug.log
    echo   2. Check the current log: logs\Log_current.txt
    echo   3. Check the events log: logs\events.ndjson
    echo   4. Try: python main.py --config-info (shows resolved config)
    echo   5. Try: python main.py --debug (runs in debug mode)
    echo   6. Try: python main.py --fix-autostart (fixes autostart issues)
    echo.
    echo   COMMON ISSUES:
    echo   - If you see module import errors, ensure all dependencies are installed
    echo   - If GUI doesn't appear, check PySide6: python -c "import PySide6; print('OK')"
    echo   - If drives aren't detected, check I/O permissions and drive accessibility
    echo   - If config issues, use --config-info to inspect resolved configuration
    echo   - If timing issues, check scheduler settings in logs
    echo.
    echo   NEW DEBUGGING TOOLS:
    echo   - Boot banner shows config location and integrity hash
    echo   - Scheduler banner shows timing grid and spacing settings
    echo   - --config-info provides comprehensive configuration details
    echo.
    pause
)

popd >nul
exit /b %EXITCODE%
