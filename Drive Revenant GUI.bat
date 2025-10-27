@echo off
REM Drive Revenant GUI.bat
REM Version: 2.0.0
REM Enhanced GUI launcher with comprehensive checks, new CLI options, and improved error handling.

echo ========================================
echo    Drive Revenant GUI Launcher v2.0
echo ========================================
echo.
echo Enhanced launcher with new features and better error handling
echo.

REM Ensure we are in the script directory
pushd "%~dp0" >nul

REM Check if Python is available
echo [1/7] Checking Python installation...
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

REM Check for PySide6 and install if needed
echo [2/7] Checking PySide6 installation...
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
echo [3/7] Verifying application modules...
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
echo [4/7] Checking application files...
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
echo [5/7] Checking configuration...
if not exist config.json (
    echo WARNING: config.json not found - will create default config
) else (
    echo   Configuration file found.
    echo   Use --config-info to inspect current configuration
)
echo.

REM Show available options and launch info
echo [6/7] Available launch options:
echo   - Default GUI mode (recommended for normal use)
echo   - --debug (for debugging and development)
echo   - --config-info (to inspect current configuration)
echo   - --fix-autostart (to fix autostart issues)
echo   - --portable (force portable mode)
echo.
echo Launching Drive Revenant GUI...
echo.

REM Launch application with GUI mode (default)
echo [7/7] Starting Drive Revenant GUI...
echo   Launching GUI with console suppressed...
echo.

REM Use pythonw.exe to launch without console window
start "" pythonw main.py %*

echo ========================================
echo   Drive Revenant GUI launched!
echo ========================================
echo.
echo   The GUI is now running in the background.
echo   Check the system tray for the Drive Revenant icon.
echo.
echo   To view logs: %APPDATA%\DriveRevenant\logs\
echo   (or ./logs/ if running in portable mode)
echo.
echo   This launcher window will close in 3 seconds...
echo.

timeout /t 3 /nobreak >nul

popd >nul
exit /b %EXITCODE%