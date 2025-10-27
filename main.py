# main.py
# Version: 1.0.6
# Main entry point for Drive Revenant with command-line argument parsing,
# single-instance enforcement, and application lifecycle management.

import sys
import os
import argparse
import time
import threading
from pathlib import Path
from typing import Tuple, Optional
import logging
import traceback

# Windows-specific imports
try:
    import win32api
    import win32con
    import win32event
    import win32process
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False

from app_config import ConfigManager, AppConfig
from app_autostart import AutostartManager
from app_core import CoreEngine
from app_io import IOManager
from app_logging import LoggingManager

# Set up logger
logger = logging.getLogger(__name__)

# Global application state
app_instance = None
config_manager = None
core_engine = None
logging_manager = None
io_manager = None
_original_console_mode = None  # Store original mode to restore on exit
_shutdown_in_progress = False  # Track if shutdown has been initiated
_force_exit_timer = None  # Timer for force exit
_single_instance_mutex = None  # Keep mutex alive for single instance protection

def setup_logging():
    """Set up basic logging before config is loaded."""
    # Only set level, don't configure handlers - LoggingManager will handle that
    logging.getLogger().setLevel(logging.INFO)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Drive Revenant - Keep selected drives awake",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  DriveRevenant                    # Run in standard mode
  DriveRevenant --portable         # Run in portable mode
  DriveRevenant --no-autostart     # Disable autostart
  DriveRevenant --fix-autostart    # Fix autostart configuration
        """
    )
    
    parser.add_argument(
        '--portable',
        action='store_true',
        help='Run in portable mode (config and logs next to executable)'
    )
    
    parser.add_argument(
        '--no-autostart',
        action='store_true',
        help='Disable autostart on system startup'
    )
    
    parser.add_argument(
        '--fix-autostart',
        action='store_true',
        help='Fix autostart configuration and exit'
    )

    parser.add_argument(
        '--config-info',
        action='store_true',
        help='Print configuration information and exit'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging and detailed output for development'
    )

    parser.add_argument(
        '--version',
        action='version',
        version='Drive Revenant 2.3.0'
    )
    
    return parser.parse_args()

def check_single_instance():
    """Check if another instance is already running."""
    global _single_instance_mutex
    
    if not WINDOWS_AVAILABLE:
        logger.warning("Windows API not available, skipping single-instance check")
        return True

    try:
        # Create a named mutex
        mutex_name = "DriveRevenant_SingleInstance"
        _single_instance_mutex = win32event.CreateMutex(None, True, mutex_name)  # Initially owned

        # Check if we got the mutex (no other instance running)
        last_error = win32api.GetLastError()
        if last_error == 183:  # ERROR_ALREADY_EXISTS = 183
            logger.error("Another instance of Drive Revenant is already running")
            return False

        logger.info("Single instance check passed - no other instances running")
        return True

    except Exception as e:
        logger.error(f"Failed to check single instance: {e}")
        return True  # Continue anyway

def initialize_application(args) -> Tuple[bool, Optional[AppConfig]]:
    """Initialize the application components."""
    global config_manager, core_engine, logging_manager, io_manager

    try:
        # Initialize config manager (auto-detect portable mode unless explicitly specified)
        if args.portable:
            portable_mode = True
        else:
            portable_mode = None  # Auto-detect
        config_manager = ConfigManager(portable_mode=portable_mode)
        config = config_manager.load_config()

        # Override autostart setting if requested
        if args.no_autostart:
            config.autostart = False

        # Hide console window if configured to do so
        if config.hide_console_window:
            hide_console_window()
        else:
            # If console is visible, disable QuickEdit to prevent accidental pausing
            disable_quickedit_mode()

        # Initialize logging manager
        log_dir = config_manager.get_log_dir()
        logging_manager = LoggingManager(log_dir, config)

        # Initialize I/O manager
        io_manager = IOManager(config)

        # Initialize core engine with all managers
        core_engine = CoreEngine(config, io_manager, config_manager, logging_manager)

        # Set up callbacks
        core_engine.status_callback = lambda status: None  # Will be set by GUI
        core_engine.log_callback = lambda op, result, time: logging_manager.log_operation(
            op, result, core_engine._build_drive_state_from_scheduler(op.drive_letter), time
        )

        # Start core engine
        core_engine.start()

        logging_manager.log_system_event("INIT", "Application initialized successfully")
        return True, config

    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        return False, None

def handle_autostart_fix():
    """Handle the --fix-autostart command."""
    try:
        # Determine exe path (same as in old ConfigManager logic)
        exe_path = Path(__file__).parent / "DriveRevenant.exe"

        autostart_manager = AutostartManager(exe_path)

        # Check current autostart status
        is_valid, method, error = autostart_manager.verify_autostart()

        if is_valid:
            print(f"Autostart is already configured correctly using {method}")
            return True

        print(f"Autostart issue detected: {error}")
        print(f"Attempting to fix using {method} method...")

        # Try to fix using the current method
        if autostart_manager.ensure_autostart(method):
            print("Autostart configuration fixed successfully")
            return True
        else:
            print("Failed to fix autostart configuration")
            return False

    except Exception as e:
        print(f"Error fixing autostart: {e}")
        return False

def handle_config_info(args) -> bool:
    """Handle the --config-info command."""
    try:
        # Initialize config manager (auto-detect portable mode unless explicitly specified)
        if args.portable:
            portable_mode = True
        else:
            portable_mode = None  # Auto-detect
        config_manager = ConfigManager(portable_mode=portable_mode)
        config = config_manager.load_config()

        print("Drive Revenant Configuration Information")
        print("=" * 50)
        print(f"Config path: {config_manager.config_path}")
        print(f"Config directory: {config_manager.config_dir}")
        print(f"Log directory: {config_manager.log_dir}")
        print(f"Portable mode: {config.portable}")
        print(f"Install ID: {config.install_id}")
        print(f"Version: {config.version}")
        print(f"Autostart: {config.autostart}")
        print(f"Autostart method: {config.autostart_method}")
        print(f"Default interval (sec): {config.default_interval_sec}")
        print(f"Interval min (sec): {config.interval_min_sec}")
        print(f"Jitter (sec): {config.jitter_sec}")
        print(f"Pause on battery: {config.pause_on_battery}")
        print(f"Idle pause (min): {config.idle_pause_min}")
        print(f"Error quarantine after: {config.error_quarantine_after}")
        print(f"Error quarantine (sec): {config.error_quarantine_sec}")
        print(f"Log max size (KB): {config.log_max_kb}")
        print(f"Log history count: {config.log_history_count}")
        print(f"GUI update interval (ms): {config.gui_update_interval_ms}")
        print(f"GUI update interval editing (ms): {config.gui_update_interval_editing_ms}")
        print(f"CLI countdown interval (sec): {config.cli_countdown_interval_sec}")

        if config.per_drive:
            print(f"\nPer-drive configurations: {len(config.per_drive)} drives")
            for drive_letter, drive_config in config.per_drive.items():
                print(f"  {drive_letter}: enabled={drive_config.enabled}, interval={drive_config.interval}, type={drive_config.type}")
        else:
            print("\nPer-drive configurations: None (will be auto-detected)")

        return True

    except Exception as e:
        print(f"Error getting config info: {e}")
        return False

def check_autostart_integrity():
    """Check autostart integrity and log issues."""
    try:
        # Determine exe path (same as in old ConfigManager logic)
        exe_path = Path(__file__).parent / "DriveRevenant.exe"
        autostart_manager = AutostartManager(exe_path)

        is_valid, method, error = autostart_manager.verify_autostart()

        if not is_valid:
            if logging_manager:
                logging_manager.log_system_event(
                    "AUTOSTART_ISSUE",
                    f"Autostart integrity check failed: {error}",
                    {"method": method, "error": error}
                )
            else:
                logger.error(f"Autostart integrity check failed: {error}")
            return False, method, error

        return True, method, ""

    except Exception as e:
        logger.error(f"Failed to check autostart integrity: {e}")
        return False, "unknown", str(e)

def force_exit():
    """Force exit the application if graceful shutdown fails."""
    global _force_exit_timer

    logger.warning("Force exiting application after timeout")
    # Cancel the timer since we're forcing exit
    if _force_exit_timer:
        _force_exit_timer.cancel()
        _force_exit_timer = None

    # Force immediate exit
    os._exit(1)

def shutdown_application():
    """Shutdown the application gracefully with force exit fallback."""
    global core_engine, logging_manager, _shutdown_in_progress, _force_exit_timer, _single_instance_mutex

    # Prevent multiple shutdown attempts
    if _shutdown_in_progress:
        return

    _shutdown_in_progress = True

    try:
        # Start force exit timer (10 seconds)
        _force_exit_timer = threading.Timer(10.0, force_exit)
        _force_exit_timer.daemon = True
        _force_exit_timer.start()

        logger.info("Starting graceful shutdown (10s timeout for force exit)")

        # Restore original console mode
        restore_quickedit_mode()

        if core_engine:
            if logging_manager:
                logging_manager.log_system_event("SHUTDOWN", "Shutting down core engine")
            # Use longer timeout for core engine stop
            core_engine.stop(timeout_ms=2000)  # Increased from 500ms

        if logging_manager:
            logging_manager.shutdown()

        # Release single instance mutex
        if _single_instance_mutex and WINDOWS_AVAILABLE:
            try:
                win32event.ReleaseMutex(_single_instance_mutex)
                logger.debug("Single instance mutex released")
            except Exception as e:
                logger.debug(f"Failed to release mutex: {e}")

        # Use logging_manager if available, otherwise basic logging
        if logging_manager:
            logging_manager.log_system_event("SHUTDOWN", "Application shutdown complete")
        else:
            logging.info("Application shutdown complete")

        # Cancel force exit timer since shutdown completed successfully
        if _force_exit_timer:
            _force_exit_timer.cancel()
            _force_exit_timer = None

    except Exception as e:
        if logging_manager:
            logging_manager.log_system_event("ERROR", f"Error during shutdown: {e}")
        else:
            logging.error(f"Error during shutdown: {e}")
        # Don't cancel force exit timer - let it run to ensure we exit

def hide_console_window():
    """Hide the console window if configured to do so."""
    try:
        import ctypes
        from ctypes import wintypes
        
        # Get console window handle
        console_window = ctypes.windll.kernel32.GetConsoleWindow()
        if console_window:
            # Hide the console window
            ctypes.windll.user32.ShowWindow(console_window, 0)  # SW_HIDE = 0
            logger.debug("Console window hidden")
    except Exception as e:
        logger.debug(f"Could not hide console window: {e}")

def disable_quickedit_mode():
    """Disable Windows QuickEdit mode to prevent console from pausing on click.
    
    QuickEdit mode causes the console to pause the entire application when:
    - User clicks in the console window
    - User selects text in the console
    - Console accidentally receives focus and selection
    
    This is a Windows feature, not a program bug. Disabling it prevents 
    the "press space to continue" behavior.
    
    Returns the original mode value so it can be restored later.
    """
    global _original_console_mode
    
    if not WINDOWS_AVAILABLE:
        return None
    
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        
        # Get console input handle
        STD_INPUT_HANDLE = -10
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        
        if handle == -1 or handle == 0:
            return None  # Console not available
        
        # Get current console mode and save it
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return None
        
        _original_console_mode = mode.value
        
        # Disable QuickEdit mode and Insert mode
        ENABLE_QUICK_EDIT_MODE = 0x0040
        ENABLE_INSERT_MODE = 0x0020
        new_mode = mode.value & ~(ENABLE_QUICK_EDIT_MODE | ENABLE_INSERT_MODE)
        
        # Set new console mode
        kernel32.SetConsoleMode(handle, new_mode)
        logger.debug("Disabled QuickEdit mode to prevent console pausing")
        
        return _original_console_mode
        
    except Exception as e:
        logger.debug(f"Could not disable QuickEdit mode: {e}")
        return None

def restore_quickedit_mode():
    """Restore the original console mode on exit.
    
    This ensures we don't affect the user's console settings or other programs.
    """
    global _original_console_mode
    
    if not WINDOWS_AVAILABLE or _original_console_mode is None:
        return
    
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        
        # Get console input handle
        STD_INPUT_HANDLE = -10
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        
        if handle == -1 or handle == 0:
            return
        
        # Restore original console mode
        kernel32.SetConsoleMode(handle, _original_console_mode)
        logger.debug("Restored original console mode")
        
    except Exception as e:
        logger.debug(f"Could not restore console mode: {e}")

def main():
    """Main application entry point."""
    global app_instance

    # Set up basic logging
    setup_logging()
    
    try:
        # Parse command line arguments
        args = parse_arguments()
        
        # Handle special commands
        if args.fix_autostart:
            success = handle_autostart_fix()
            sys.exit(0 if success else 1)

        if args.config_info:
            success = handle_config_info(args)
            sys.exit(0 if success else 1)
        
        # Check single instance
        if not check_single_instance():
            sys.exit(1)
        
        # Initialize application
        success, config = initialize_application(args)
        if not success:
            logger.error("Failed to initialize application")
            sys.exit(1)

        # Show debug log location if in debug mode
        if args.debug and logging_manager:
            debug_log_path = logging_manager.log_dir / "debug.log"
            logger.info(f"Debug log location: {debug_log_path}")
            print(f"Debug log: {debug_log_path}")

        # Check autostart integrity
        autostart_valid, autostart_method, autostart_error = check_autostart_integrity()

        # Start GUI
        logger.info("Starting GUI...")
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as e:
            logger.exception("Failed to import PySide6.QtWidgets (Qt not installed?)")
            print("ERROR: Failed to import PySide6. Try: pip install -r requirements.txt")
            raise

        try:
            from app_gui import MainWindow
        except Exception as e:
            logger.exception("Failed to import app_gui.MainWindow")
            print("ERROR importing app_gui. See traceback below:")
            print(traceback.format_exc())
            raise

        app = QApplication(sys.argv)
        app.setApplicationName("Drive Revenant")
        app.setApplicationVersion("1.0.0")
        app.setOrganizationName("Drive Revenant")
        app.setStyle('Fusion')
        
        # Create main window with provided components
        window = MainWindow(config_manager, core_engine, logging_manager, io_manager)
        window.show()
        
        # Run application
        sys.exit(app.exec())

    except Exception as e:
        # Log with full traceback
        if logging_manager:
            logging_manager.log_system_event("ERROR", f"Unexpected error in main: {e}")
        logger.exception("Unexpected error in main")
        print("\nFull traceback:\n" + traceback.format_exc())
        sys.exit(1)
    
    finally:
        shutdown_application()

if __name__ == "__main__":
    main()
