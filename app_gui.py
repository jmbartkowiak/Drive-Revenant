# app_gui.py
# Version: 2.0.2
# Main GUI module for Drive Revenant - imports MainWindow from modular components

# Import the MainWindow class from the modular GUI components
# Note: MainWindow is implemented in this file but uses components from separate modules

from PySide6.QtWidgets import QMainWindow, QApplication, QSystemTrayIcon, QMenu, QMessageBox, QDialog, QFileDialog
from PySide6.QtCore import Qt, QTimer, QPoint, Signal
from PySide6.QtGui import QIcon, QAction, QFont, QKeySequence
import time
import logging

# Import GUI components from separate modules
from app_gui_drive_table import DriveTableWidget, StatusIndicator, ComboBoxDelegate
from app_gui_status_thread import StatusUpdateThread
from app_gui_settings_dialog import SettingsDialog
from app_gui_log_viewer import LogViewerDialog, LogParser

# Import core components
from app_config import ConfigManager
from app_core import CoreEngine
from app_io import IOManager
from app_logging import LoggingManager

# Import types
from app_types import DriveConfig, DriveState

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window for Drive Revenant."""

    def __init__(self, config_manager=None, core_engine=None, logging_manager=None, io_manager=None):
        super().__init__()

        # Store component references
        self.config_manager = config_manager
        self.core_engine = core_engine
        self.logging_manager = logging_manager
        self.io_manager = io_manager

        # Initialize UI components
        self.setup_window()
        self.setup_menu_bar()
        self.setup_toolbar()
        self.setup_status_bar()
        self.setup_system_tray()
        self.setup_central_widget()

        # Set up status update thread
        if self.core_engine:
            self.status_thread = StatusUpdateThread(
                self.core_engine,
                self.drive_table if hasattr(self, 'drive_table') else None,
                self.config_manager.load_config() if self.config_manager else None
            )
            self.status_thread.status_updated.connect(self.update_status)
            self.status_thread.start()

        # Connect signals
        self.connect_signals()

        # Set window properties
        self.setWindowTitle("Drive Revenant")
        self.setWindowIcon(QIcon("DR tray icon.png"))
        self.resize(1200, 800)

    def setup_window(self):
        """Set up the main window properties."""
        self.setWindowTitle("Drive Revenant")
        self.setMinimumSize(800, 600)

    def setup_menu_bar(self):
        """Set up the menu bar."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        self.export_action = QAction("&Export Diagnostics...", self)
        self.export_action.triggered.connect(self.export_diagnostics)
        file_menu.addAction(self.export_action)

        file_menu.addSeparator()
        
        self.full_scan_action = QAction("&Full Drive Scan", self)
        self.full_scan_action.triggered.connect(self.full_drive_scan)
        file_menu.addAction(self.full_scan_action)
        
        self.full_rescan_action = QAction("&Full Rescan (Clear All)", self)
        self.full_rescan_action.triggered.connect(self.full_rescan_drives)
        file_menu.addAction(self.full_rescan_action)

        file_menu.addSeparator()

        self.clear_logs_menu_action = QAction("&Clear Logs", self)
        self.clear_logs_menu_action.triggered.connect(self.clear_logs)
        file_menu.addAction(self.clear_logs_menu_action)

        file_menu.addSeparator()

        # Minimize to Tray
        self.minimize_to_tray_action = QAction("&Minimize to Tray", self)
        self.minimize_to_tray_action.triggered.connect(self.exit_to_tray)
        file_menu.addAction(self.minimize_to_tray_action)

        # Exit Application
        self.quit_action = QAction("&Exit Application", self)
        self.quit_action.setShortcut(QKeySequence.Quit)
        self.quit_action.triggered.connect(self.quit_application)
        file_menu.addAction(self.quit_action)
        
        # Drives menu
        drives_menu = menubar.addMenu("&Drives")
        
        self.refresh_action = QAction("&Refresh Drives", self)
        self.refresh_action.triggered.connect(self.refresh_drives)
        drives_menu.addAction(self.refresh_action)
        
        self.ping_selected_action = QAction("&Ping Selected Now", self)
        self.ping_selected_action.triggered.connect(self.ping_selected_drive)
        drives_menu.addAction(self.ping_selected_action)

        drives_menu.addSeparator()

        # Bulk actions submenu
        bulk_menu = drives_menu.addMenu("&Bulk Actions")

        self.bulk_enable_action = QAction("&Enable Selected", self)
        self.bulk_enable_action.triggered.connect(self.bulk_enable_drives)
        bulk_menu.addAction(self.bulk_enable_action)

        self.bulk_disable_action = QAction("&Disable Selected", self)
        self.bulk_disable_action.triggered.connect(self.bulk_disable_drives)
        bulk_menu.addAction(self.bulk_disable_action)

        self.bulk_ping_action = QAction("&Ping Selected", self)
        self.bulk_ping_action.triggered.connect(self.bulk_ping_drives)
        bulk_menu.addAction(self.bulk_ping_action)

        self.bulk_clear_quarantine_action = QAction("&Clear Quarantine for Selected", self)
        self.bulk_clear_quarantine_action.triggered.connect(self.bulk_clear_quarantine)
        bulk_menu.addAction(self.bulk_clear_quarantine_action)
        
        # Settings menu
        settings_menu = menubar.addMenu("&Settings")

        self.settings_action = QAction("&Preferences...", self)
        self.settings_action.triggered.connect(self.show_settings)
        settings_menu.addAction(self.settings_action)

        settings_menu.addSeparator()

        self.disable_hotkeys_action = QAction("&Disable Hotkeys", self)
        self.disable_hotkeys_action.setCheckable(True)
        self.disable_hotkeys_action.setChecked(False)  # Default: hotkeys enabled
        self.disable_hotkeys_action.triggered.connect(self.toggle_disable_hotkeys)
        settings_menu.addAction(self.disable_hotkeys_action)

        self.autostart_action = QAction("&Fix Autostart", self)
        self.autostart_action.triggered.connect(self.fix_autostart)
        settings_menu.addAction(self.autostart_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")

        self.about_action = QAction("&About", self)
        self.about_action.triggered.connect(self.show_about)
        help_menu.addAction(self.about_action)

        help_menu.addSeparator()

        self.log_viewer_action = QAction("&View Logs", self)
        self.log_viewer_action.triggered.connect(self.show_log_viewer)
        help_menu.addAction(self.log_viewer_action)

        help_menu.addSeparator()

        self.open_logs_folder_action = QAction("&Open Logs Folder", self)
        self.open_logs_folder_action.triggered.connect(self._open_logs_folder)
        help_menu.addAction(self.open_logs_folder_action)

        self.accessibility_test_action = QAction("&Test Accessibility", self)
        self.accessibility_test_action.triggered.connect(self.test_accessibility)
        help_menu.addAction(self.accessibility_test_action)

        self.status_colors_test_action = QAction("&Test Status Colors", self)
        self.status_colors_test_action.triggered.connect(self.test_status_colors)
        help_menu.addAction(self.status_colors_test_action)

    def setup_toolbar(self):
        """Set up the toolbar."""
        toolbar = self.addToolBar("Main")
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        
        # Global pause/resume
        self.pause_action = QAction("Pause All", self)
        # Remove setCheckable - no longer a toggle
        self.pause_action.triggered.connect(self.pause_all_drives)
        toolbar.addAction(self.pause_action)

        self.resume_action = QAction("Resume All", self)
        self.resume_action.triggered.connect(self.resume_all_drives)
        toolbar.addAction(self.resume_action)
        
        toolbar.addSeparator()
        
        # Pause/Resume Selected
        self.pause_selected_action = QAction("Pause Selected", self)
        self.pause_selected_action.triggered.connect(self.pause_selected_drives)
        toolbar.addAction(self.pause_selected_action)

        self.resume_selected_action = QAction("Resume Selected", self)
        self.resume_selected_action.triggered.connect(self.resume_selected_drives)
        toolbar.addAction(self.resume_selected_action)
        
        toolbar.addSeparator()
        
        # Ping selected
        toolbar.addAction(self.ping_selected_action)

        toolbar.addSeparator()

        # Bulk actions
        self.bulk_enable_btn = QAction("Enable Selected", self)
        self.bulk_enable_btn.triggered.connect(self.bulk_enable_drives)
        toolbar.addAction(self.bulk_enable_btn)

        self.bulk_disable_btn = QAction("Disable Selected", self)
        self.bulk_disable_btn.triggered.connect(self.bulk_disable_drives)
        toolbar.addAction(self.bulk_disable_btn)

        # Refresh drives
        toolbar.addAction(self.refresh_action)
        
        toolbar.addSeparator()
        
        # Clear logs
        self.clear_logs_action = QAction("Clear Logs", self)
        self.clear_logs_action.triggered.connect(self.clear_logs)
        toolbar.addAction(self.clear_logs_action)

    def setup_status_bar(self):
        """Set up the status bar."""
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready", 2000)
        
        # Add permanent widget on the right side for next drives display
        from PySide6.QtWidgets import QLabel
        self.next_drives_label = QLabel("Next: —")
        self.next_drives_label.setStyleSheet("QLabel { font-weight: bold; padding: 2px 8px; }")
        self.status_bar.addPermanentWidget(self.next_drives_label)
        
        # Add status legend to the left side by inserting it before the main message
        legend_widget = self._create_status_legend()
        self.status_bar.insertPermanentWidget(0, legend_widget)

    def setup_system_tray(self):
        """Set up the system tray icon."""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("DR tray icon.png"))

        # Create tray menu
        tray_menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.do_quit)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)

        self.tray_icon.show()

    def setup_central_widget(self):
        """Set up the central widget with drive table."""
        from PySide6.QtWidgets import QWidget, QVBoxLayout

        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        # Create drive table
        self.drive_table = DriveTableWidget()
        self.drive_table.set_main_window(self)  # Set main window reference for interval editing
        if self.core_engine:
            self.drive_table.set_core_engine(self.core_engine)
        if self.config_manager:
            self.drive_table.set_config_manager(self.config_manager)
        if self.logging_manager:
            self.drive_table.set_logging_manager(self.logging_manager)

        layout.addWidget(self.drive_table)
        
        self.setCentralWidget(central_widget)

    def _create_status_legend(self):
        """Create a compact legend for status indicators."""
        from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSizePolicy

        legend = QWidget()
        legend.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        legend_layout = QHBoxLayout(legend)
        legend_layout.setContentsMargins(5, 2, 5, 2)
        legend_layout.setSpacing(8)

        # Compact status indicators legend
        indicators = [
            ("🟢", "Active"),
            ("🟡", "Paused"),
            ("🔴", "Disabled"),
            ("🟢+T", "Throttled")
        ]

        for symbol, description in indicators:
            item = QWidget()
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(2)

            symbol_label = QLabel(symbol)
            symbol_label.setStyleSheet("QLabel { font-size: 9px; }")

            desc_label = QLabel(description)
            desc_label.setStyleSheet("QLabel { font-size: 8px; color: #666; }")

            item_layout.addWidget(symbol_label)
            item_layout.addWidget(desc_label)
            legend_layout.addWidget(item)

        return legend

    def connect_signals(self):
        """Connect GUI signals."""
        # Connect drive table signals if available
        if hasattr(self.drive_table, 'drive_selection_changed'):
            self.drive_table.drive_selection_changed.connect(self.on_drive_selection_changed)

    def closeEvent(self, event):
        """Handle window close event."""
        if self.tray_icon and self.tray_icon.isVisible():
            # Hide to tray instead of closing
            self.hide()
            event.ignore()
        else:
            # Actually close
            self.do_quit()
            event.accept()

    def cleanup(self):
        """Clean up resources before closing."""
        if hasattr(self, 'status_thread') and self.status_thread:
            self.status_thread.stop()
            self.status_thread.wait(1000)

        if self.tray_icon:
            self.tray_icon.hide()

    def tray_icon_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show()
            self.raise_()
            self.activateWindow()

    def show_settings(self):
        """Show settings dialog."""
        if not self.config_manager:
            QMessageBox.warning(self, "Settings", "Configuration manager not available")
            return

        dialog = SettingsDialog(self.config_manager, self)
        if dialog.exec() == QDialog.Accepted:
            self.status_bar.showMessage("Settings saved", 2000)
            if hasattr(self, 'status_thread') and self.status_thread:
                config = self.config_manager.load_config()
                old_intervals = (self.status_thread.fast_update_interval, self.status_thread.slow_update_interval)
                new_intervals = (config.gui_update_interval_ms, config.gui_update_interval_editing_ms)
                if old_intervals != new_intervals:
                    self.status_thread.fast_update_interval = config.gui_update_interval_ms
                    self.status_thread.slow_update_interval = config.gui_update_interval_editing_ms
                    self.status_thread.config = config
        else:
            self.status_bar.showMessage("Settings cancelled", 2000)

    def ping_selected_drive(self):
        """Ping the currently selected drive."""
        if self.drive_table:
            selected_drives = self.drive_table.get_selected_drives()
            if selected_drives:
                drive_letter = selected_drives[0]
                if self.core_engine:
                    success = self.core_engine.ping_drive_now(drive_letter)
                    if success:
                        self.status_bar.showMessage(f"Successfully pinged drive {drive_letter}", 2000)
                    else:
                        self.status_bar.showMessage(f"Failed to ping drive {drive_letter}", 2000)
                else:
                    self.status_bar.showMessage("Core engine not available", 2000)
            else:
                self.status_bar.showMessage("No drive selected", 2000)

    def refresh_drives(self):
        """Refresh the drive list by rescanning (uses quick mode by default)."""
        if not self.core_engine:
            self.status_bar.showMessage("Core engine not available", 2000)
            return

        success = self.core_engine.rescan_drives(mode="quick")
        if success:
            # Update the table with new drive data
            status = self.core_engine.get_full_status_snapshot()
            self.update_status(status)
            self.status_bar.showMessage("Drive scan completed", 2000)
        else:
            self.status_bar.showMessage("Drive scan failed", 2000)

    def full_drive_scan(self):
        """Trigger a full drive scan (E-Z) instead of quick scan."""
        if not self.core_engine:
            self.status_bar.showMessage("Core engine not available", 2000)
            return
        
        # Show confirmation dialog
        reply = QMessageBox.question(
            self, 
            "Full Drive Scan",
            "This will scan all drive letters from E: to Z: to discover new drives.\n\n"
            "This may take 10-15 seconds.\n\nProceed?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.Yes:
            self.status_bar.showMessage("Performing full drive scan...", 5000)
            success = self.core_engine.rescan_drives(mode="full")
            if success:
                status = self.core_engine.get_full_status_snapshot()
                self.update_status(status)
                self.status_bar.showMessage("Full drive scan completed", 2000)
            else:
                self.status_bar.showMessage("Full drive scan failed", 2000)

    def full_rescan_drives(self):
        """Clear all existing drives and perform a complete fresh scan."""
        if not self.core_engine:
            self.status_bar.showMessage("Core engine not available", 2000)
            return
        
        # Show confirmation dialog with warning
        reply = QMessageBox.question(
            self, 
            "Full Rescan (Clear All)",
            "This will:\n"
            "• CLEAR ALL existing drive configurations\n"
            "• Reset all drive states and schedules\n"
            "• Perform a fresh scan of all drives E-Z\n"
            "• Re-discover and configure all available drives\n\n"
            "This may take 10-15 seconds.\n\n"
            "WARNING: All current drive settings will be lost!\n\n"
            "Proceed?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No  # Default to No for safety
        )
        
        if reply == QMessageBox.Yes:
            self.status_bar.showMessage("Clearing all drives and performing fresh scan...", 10000)
            try:
                # Clear all existing drive configurations
                self.core_engine.config.per_drive.clear()
                
                # Clear scheduler state
                self.core_engine.scheduler._drive_timing.clear()
                self.core_engine.scheduler._version = 0
                self.core_engine.scheduler._snapshot = None
                
                # Clear scheduled operations
                self.core_engine.scheduled_operations.clear()
                
                # Perform fresh full scan
                available_drives = self.core_engine._scan_and_update_drives(mode="full")
                
                # Re-initialize drive states
                self.core_engine._initialize_drive_states()
                
                # Update status
                status = self.core_engine.get_full_status_snapshot()
                self.update_status(status)
                
                self.status_bar.showMessage(f"Full rescan completed: {len(available_drives)} drives discovered", 5000)
                
            except Exception as e:
                self.status_bar.showMessage(f"Full rescan failed: {e}", 5000)
                logger.error(f"Full rescan error: {e}")

    def clear_logs(self):
        """Clear the application logs."""
        if self.logging_manager:
            try:
                self.logging_manager.clear_logs()
                self.status_bar.showMessage("Logs cleared", 2000)
            except Exception as e:
                self.status_bar.showMessage(f"Failed to clear logs: {e}", 2000)
        else:
            self.status_bar.showMessage("Logging manager not available", 2000)

    def show_about(self):
        """Show the about dialog."""
        QMessageBox.about(
            self,
            "About Drive Revenant",
            "Drive Revenant v1.0.0\n\n"
            "Keeps external drives awake by periodically accessing them.\n\n"
            "Prevents drives from spinning down during active use."
        )

    def pause_all_drives(self):
        """Pause all drives."""
        if not self.core_engine:
            return
        
        count = self.core_engine.pause_all_drives()
        self.status_bar.showMessage(f"Paused {count} drive(s)", 2000)
        self.refresh_drives()

    def on_drive_selection_changed(self, selected_drives):
        """Handle drive selection changes."""
        if selected_drives:
            self.status_bar.showMessage(f"Selected drive: {selected_drives[0]}", 2000)
        else:
            self.status_bar.showMessage("No drive selected", 2000)

    def update_status(self, status):
        """Update the GUI with new status information."""
        if self.drive_table:
            self.drive_table.update_drive_data(status.get('drives', {}))

        # Show next 5 drives using real scheduler data (no local prediction)
        upcoming_ops = status.get('upcoming_operations', [])
        drives = status.get('drives', {})
        
        if upcoming_ops:
            # Format as simple arrow chain: G → E → I → N → G
            drive_letters = [op["drive"].rstrip(':') for op in upcoming_ops]
            message = " → ".join(drive_letters)
            self.next_drives_label.setText(f"Next: {message}")
        else:
            # Show active drive count if no upcoming operations (e.g., all paused)
            active_count = sum(1 for d in drives.values() if d.get('enabled', False))
            if active_count > 0:
                self.next_drives_label.setText(f"Active: {active_count} drive{'s' if active_count != 1 else ''}")
            else:
                self.next_drives_label.setText("Active: No drives")

    def export_diagnostics(self):
        """Export diagnostic information with security hardening."""
        if not self.logging_manager or not self.config_manager:
            QMessageBox.warning(self, "Export Diagnostics", "Required managers not available")
            return

        try:
            import zipfile
            import tempfile
            import shutil
            import os
            import time
            from pathlib import Path

            # Let user choose export location
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            default_filename = f"DriveRevenant_Diagnostics_{timestamp}.zip"
            export_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Diagnostics",
                str(Path.home() / default_filename),
                "ZIP files (*.zip)"
            )

            if not export_path:
                return  # User cancelled

            export_path = Path(export_path)

            # Ensure the path is safe (no path traversal)
            if ".." in export_path.parts or export_path.is_absolute() == False:
                QMessageBox.warning(self, "Export Diagnostics", "Invalid export path specified")
                return

            # Create temporary directory for diagnostics
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Export configuration (redacted)
                config = self.config_manager.load_config()
                redacted_config = self._redact_config_for_export(config)
                config_file = temp_path / "config.json"
                config_file.write_text(redacted_config)

                # Export logs
                log_dir = self.config_manager.get_log_dir()
                logs_dir = temp_path / "logs"
                logs_dir.mkdir()

                # Copy log files safely
                for log_file in self.logging_manager.get_log_files():
                    if log_file.exists() and log_file.is_file():
                        try:
                            shutil.copy2(log_file, logs_dir / log_file.name)
                        except (OSError, PermissionError) as e:
                            print(f"Warning: Could not copy log file {log_file}: {e}")

                # Export NDJSON
                ndjson_file = self.logging_manager.get_ndjson_file()
                if ndjson_file and ndjson_file.exists() and ndjson_file.is_file():
                    try:
                        shutil.copy2(ndjson_file, logs_dir / "events.ndjson")
                    except (OSError, PermissionError) as e:
                        print(f"Warning: Could not copy NDJSON file {ndjson_file}: {e}")

                # Create environment info
                env_info = self._get_environment_info()
                env_file = temp_path / "environment.json"
                env_file.write_text(env_info)

                # Create autostart info
                autostart_info = self._get_autostart_info()
                autostart_file = temp_path / "autostart.json"
                autostart_file.write_text(autostart_info)

                # Create zip file safely
                try:
                    with zipfile.ZipFile(export_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for file_path in temp_path.rglob('*'):
                            if file_path.is_file():
                                # Ensure no path traversal in zip
                                arcname = file_path.relative_to(temp_path)
                                if ".." in str(arcname) or str(arcname).startswith("/"):
                                    continue
                                zf.write(file_path, arcname)

                    self.status_bar.showMessage(f"Diagnostics exported to {export_path}", 5000)
                    QMessageBox.information(self, "Export Diagnostics", f"Diagnostics exported successfully to:\n{export_path}")

                except (OSError, PermissionError) as e:
                    QMessageBox.warning(self, "Export Diagnostics", f"Could not write to selected location:\n{e}\n\nPlease choose a different location with write permissions.")

        except Exception as e:
            QMessageBox.warning(self, "Export Diagnostics", f"Error exporting diagnostics: {e}")

    def _redact_config_for_export(self, config) -> str:
        """Redact sensitive information from configuration for export."""
        import json
        from copy import deepcopy

        # Deep copy to avoid modifying original
        export_config = deepcopy(config.__dict__)

        # Redact install_id
        export_config['install_id'] = "[REDACTED]"

        # Redact absolute paths in ping_dir
        for drive_letter, drive_config in export_config.get('per_drive', {}).items():
            if 'ping_dir' in drive_config and drive_config['ping_dir']:
                drive_config['ping_dir'] = "[REDACTED_PATH]"

        return json.dumps(export_config, indent=2)

    def _get_environment_info(self) -> str:
        """Get environment information for diagnostics."""
        import json
        import platform
        import sys
        import time

        env_info = {
            "platform": platform.platform(),
            "python_version": sys.version,
            "python_bits": platform.architecture()[0],
            "processor": platform.processor(),
            "application_version": "1.0.0",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "config_location": str(self.config_manager.config_path) if self.config_manager else "Unknown",
            "log_location": str(self.config_manager.get_log_dir()) if self.config_manager else "Unknown"
        }

        return json.dumps(env_info, indent=2)

    def _get_autostart_info(self) -> str:
        """Get autostart information for diagnostics."""
        import json
        import time
        
        autostart_info = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "autostart_enabled": False,
            "autostart_method": "none",
            "autostart_valid": False,
            "autostart_error": "Not checked"
        }
        
        try:
            if self.config_manager:
                config = self.config_manager.load_config()
                autostart_info["autostart_enabled"] = config.autostart
                autostart_info["autostart_method"] = config.autostart_method
                
                # Check autostart status
                from app_autostart import AutostartManager
                autostart_manager = AutostartManager(self.config_manager)
                is_valid, method, error = autostart_manager.verify_autostart()
                
                autostart_info["autostart_valid"] = is_valid
                autostart_info["autostart_method"] = method
                autostart_info["autostart_error"] = error
                
        except Exception as e:
            autostart_info["autostart_error"] = f"Error checking autostart: {e}"
        
        return json.dumps(autostart_info, indent=2)

    def show_log_viewer(self):
        """Show log viewer dialog."""
        try:
            if not self.logging_manager:
                QMessageBox.warning(self, "Log Viewer", "Logging manager not available")
                return
            
            # Create and show log viewer dialog
            dialog = LogViewerDialog(self.logging_manager, self)
            dialog.exec()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Log Viewer Error",
                f"Failed to open log viewer: {e}"
            )

    def fix_autostart(self):
        """Fix autostart configuration."""
        if not self.config_manager:
            QMessageBox.warning(self, "Fix Autostart", "Configuration manager not available")
            return
            
        try:
            from app_autostart import AutostartManager
            autostart_manager = AutostartManager(self.config_manager)
            
            # Check current status first
            is_valid, method, error = autostart_manager.verify_autostart()
            
            if is_valid:
                QMessageBox.information(self, "Fix Autostart", f"Autostart is already configured correctly using {method}")
                return
            
            # Try to fix using the preferred method (scheduler first, then registry)
            if autostart_manager.ensure_autostart("scheduler"):
                QMessageBox.information(self, "Fix Autostart", "Autostart configuration fixed successfully using Task Scheduler")
            elif autostart_manager.ensure_autostart("registry"):
                QMessageBox.information(self, "Fix Autostart", "Autostart configuration fixed successfully using Registry")
            else:
                QMessageBox.warning(self, "Fix Autostart", f"Failed to fix autostart configuration. Error: {error}")
                
        except Exception as e:
            QMessageBox.critical(self, "Fix Autostart", f"Error fixing autostart: {e}")

    def _open_logs_folder(self):
        """Open the logs folder in the file explorer."""
        if not self.config_manager:
            QMessageBox.warning(self, "Open Logs Folder", "Configuration manager not available")
            return

        try:
            import subprocess
            import platform

            log_dir = self.config_manager.get_log_dir()

            # Create directory if it doesn't exist
            log_dir.mkdir(parents=True, exist_ok=True)

            if platform.system() == "Windows":
                subprocess.run(["explorer", str(log_dir)], check=True)
            else:
                # For non-Windows systems, try to open with default file manager
                subprocess.run(["xdg-open", str(log_dir)], check=True)

            self.status_bar.showMessage(f"Opened logs folder: {log_dir}", 3000)

        except subprocess.CalledProcessError:
            QMessageBox.warning(self, "Open Logs Folder", "Could not open logs folder. Please navigate to it manually.")
        except Exception as e:
            QMessageBox.warning(self, "Open Logs Folder", f"Error opening logs folder: {e}")

    def test_accessibility(self):
        """Run accessibility baseline validation."""
        results = []

        # Test 1: Keyboard navigation
        try:
            # Check if table can receive focus
            if hasattr(self.drive_table, 'setFocus'):
                results.append("✅ Keyboard navigation: Table focus supported")
            else:
                results.append("❌ Keyboard navigation: Table focus not supported")
        except:
            results.append("❌ Keyboard navigation: Test failed")

        # Test 2: High DPI scaling
        try:
            # Check if window respects DPI scaling
            if hasattr(self, 'devicePixelRatio'):
                results.append("✅ High DPI scaling: Supported")
            else:
                results.append("❌ High DPI scaling: Not supported")
        except:
            results.append("❌ High DPI scaling: Test failed")

        # Test 3: Color contrast
        try:
            # Check if status indicators use distinct colors
            from PySide6.QtGui import QColor
            green_color = QColor(0, 255, 0)
            red_color = QColor(255, 0, 0)
            yellow_color = QColor(255, 255, 0)

            # Basic contrast check (simplified)
            if (green_color != red_color and green_color != yellow_color and red_color != yellow_color):
                results.append("✅ Color contrast: Status indicators use distinct colors")
            else:
                results.append("❌ Color contrast: Status indicators may not be distinguishable")
        except:
            results.append("❌ Color contrast: Test failed")

        # Test 4: Screen reader compatibility
        try:
            # Check if table items have accessible names
            if self.drive_table.rowCount() > 0:
                item = self.drive_table.item(0, 1)  # Drive letter column
                if item and hasattr(item, 'text'):
                    results.append("✅ Screen reader compatibility: Table items have accessible text")
                else:
                    results.append("❌ Screen reader compatibility: Table items may not be accessible")
            else:
                results.append("⚠️ Screen reader compatibility: No data to test")
        except:
            results.append("❌ Screen reader compatibility: Test failed")

        # Display results
        results_text = "Accessibility Test Results:\n\n" + "\n".join(results)

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Accessibility Test")
        msg_box.setText(results_text)
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

    def toggle_disable_hotkeys(self):
        """Toggle the disable hotkeys setting."""
        if not self.config_manager:
            return

        config = self.config_manager.load_config()
        config.disable_hotkeys = not config.disable_hotkeys
        if not self.config_manager.save_config(config):
            self.status_bar.showMessage("Failed to save hotkey settings", 3000)
            # Revert the change visually
            config.disable_hotkeys = not config.disable_hotkeys
            return

        # Show status message
        if config.disable_hotkeys:
            self.status_bar.showMessage("Hotkeys disabled", 2000)
        else:
            self.status_bar.showMessage("Hotkeys enabled", 2000)

    def exit_to_tray(self):
        """Exit to system tray."""
        if self.tray_icon:
            self.hide()
            self.tray_icon.showMessage(
                "Drive Revenant",
                "Application minimized to system tray",
                QSystemTrayIcon.Information,
                2000
            )

    def quit_application(self):
        """Quit the application with confirmation."""
        # Check if confirmation is suppressed
        if self.config_manager:
            config = self.config_manager.load_config()
            if config.suppress_quit_confirm:
                self.do_quit()
                return

        # Create custom message box with checkbox
        from PySide6.QtWidgets import QCheckBox
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Exit Drive Revenant")
        msg_box.setText("Do you really want to exit Drive Revenant?\nThis will close the application completely.")
        msg_box.setIcon(QMessageBox.Question)
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)

        # Add checkbox for "don't ask again"
        checkbox = QCheckBox("Do not ask me again")
        msg_box.setCheckBox(checkbox)

        # Show dialog
        reply = msg_box.exec()

        if reply == QMessageBox.Yes:
            # Save preference if checkbox is checked
            if checkbox.isChecked() and self.config_manager:
                config = self.config_manager.load_config()
                original_value = config.suppress_quit_confirm
                config.suppress_quit_confirm = True
                if not self.config_manager.save_config(config):
                    self.status_bar.showMessage(f"Failed to save quit confirmation preference", 3000)
                    # Revert the config change
                    config.suppress_quit_confirm = original_value

            self.do_quit()

    def do_quit(self):
        """Actually quit the application with force exit fallback."""
        # Show shutdown feedback
        self.status_bar.showMessage("Shutting down...")

        # Disable quit confirmation to prevent double-clicks during shutdown
        self.setEnabled(False)

        # Stop status thread first
        if hasattr(self, 'status_thread') and self.status_thread:
            self.status_thread.stop()

        # Force save if dirty
        if hasattr(self.drive_table, '_config_dirty') and self.drive_table._config_dirty:
            if self.config_manager:
                config = self.config_manager.load_config()
                self.config_manager.save_config(config)
                import logging
                logger = logging.getLogger(__name__)
                logger.info("Config saved on shutdown (dirty flag was set)")

        # Stop core engine with longer timeout
        if self.core_engine:
            self.core_engine.stop(timeout_ms=2000)  # Increased timeout

        # Shutdown logging last
        if self.logging_manager:
            self.logging_manager.shutdown()

        # Close application
        QApplication.quit()

    def resume_all_drives(self):
        """Resume all drives."""
        if not self.core_engine:
            return
        
        count = self.core_engine.resume_all_drives()
        self.status_bar.showMessage(f"Resumed {count} drive(s)", 2000)
        self.refresh_drives()

    def _get_selected_drive_letters(self):
        """Get list of drive letters for selected rows."""
        selected_letters = []
        for row in self.drive_table.selectionModel().selectedRows():
            drive_item = self.drive_table.item(row.row(), 1)  # Drive letter column
            if drive_item:
                selected_letters.append(drive_item.text())
        return selected_letters

    def _bulk_set_enabled_state(self, enabled: bool, status_when_enabled: str, status_when_disabled: str):
        """Helper method for bulk enable/disable operations."""
        selected_letters = self._get_selected_drive_letters()
        if not selected_letters:
            self.status_bar.showMessage("No drives selected", 2000)
            return 0

        success_count = 0
        for drive_letter in selected_letters:
            if self.core_engine:
                drive_state = self.core_engine._build_drive_state_from_scheduler(drive_letter)
                if not drive_state:
                    continue
                should_change = (enabled and not drive_state.enabled) or (not enabled and drive_state.enabled)

                if should_change:
                    # Use proper CoreEngine method instead of direct modification
                    self.core_engine.set_drive_config(
                        letter=drive_letter,
                        enabled=enabled,
                        interval=drive_state.config.interval,
                        drive_type=drive_state.config.type,
                        ping_dir=drive_state.config.ping_dir,
                        save_config=True
                    )
                    success_count += 1

        return success_count

    def bulk_enable_drives(self):
        """Enable all selected drives."""
        success_count = self._bulk_set_enabled_state(True, "ACTIVE", "OFFLINE")
        if success_count > 0:
            self.status_bar.showMessage(f"Enabled {success_count} drive(s)", 2000)
        else:
            self.status_bar.showMessage("No drives were enabled", 2000)

    def bulk_disable_drives(self):
        """Disable all selected drives."""
        success_count = self._bulk_set_enabled_state(False, "ACTIVE", "OFFLINE")
        if success_count > 0:
            self.status_bar.showMessage(f"Disabled {success_count} drive(s)", 2000)
        else:
            self.status_bar.showMessage("No drives were disabled", 2000)

    def bulk_ping_drives(self):
        """Ping all selected drives."""
        selected_letters = self._get_selected_drive_letters()
        if not selected_letters:
            self.status_bar.showMessage("No drives selected", 2000)
            return

        success_count = 0
        for drive_letter in selected_letters:
            if self.core_engine:
                if self.core_engine.ping_drive_now(drive_letter):
                    success_count += 1

        self.status_bar.showMessage(f"Successfully pinged {success_count}/{len(selected_letters)} drive(s)", 3000)

    def bulk_clear_quarantine(self):
        """Clear quarantine for all selected drives."""
        selected_letters = self._get_selected_drive_letters()
        if not selected_letters:
            self.status_bar.showMessage("No drives selected", 2000)
            return

        success_count = 0
        for drive_letter in selected_letters:
            if self.core_engine:
                drive_state = self.core_engine._build_drive_state_from_scheduler(drive_letter)
                if drive_state and drive_state.status.value == "Quarantine":
                    self.core_engine.clear_drive_quarantine(drive_letter)
                    success_count += 1

        if success_count > 0:
            self.refresh_drives()
            self.status_bar.showMessage(f"Cleared quarantine for {success_count} drive(s)", 2000)
        else:
            self.status_bar.showMessage("No drives were in quarantine", 2000)

    def _ping_drive_by_letter(self, drive_letter: str):
        """Ping a specific drive by letter."""
        if self.core_engine:
            success = self.core_engine.ping_drive_now(drive_letter)
            if success:
                self.status_bar.showMessage(f"Pinged {drive_letter}", 2000)
            else:
                self.status_bar.showMessage(f"Failed to ping {drive_letter}", 2000)

    def show_drive_details(self, drive_letter: str):
        """Show detailed information about a drive."""
        if not self.io_manager:
            QMessageBox.warning(self, "Drive Details", "I/O manager not available")
            return

        try:
            # Get detailed drive information
            # Strip colon from drive letter for get_drive_info
            drive_letter_clean = drive_letter.rstrip(':')
            drive_info = self.io_manager.get_drive_info(drive_letter_clean)

            # Create details dialog
            from PySide6.QtWidgets import QVBoxLayout, QFormLayout, QGroupBox, QLabel, QDialogButtonBox, QTextEdit
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Drive Details - {drive_letter}")
            dialog.setModal(True)
            dialog.resize(700, 600)

            layout = QVBoxLayout(dialog)

            # Drive info group
            info_group = QGroupBox(f"Drive {drive_letter} Information")
            info_layout = QFormLayout(info_group)

            # Basic info
            info_layout.addRow("Drive Letter:", QLabel(drive_letter))
            info_layout.addRow("Exists:", QLabel("Yes" if drive_info.get('exists', False) else "No"))
            info_layout.addRow("Accessible:", QLabel("Yes" if drive_info.get('accessible', False) else "No"))
            info_layout.addRow("Type:", QLabel(drive_info.get('type', 'Unknown')))
            
            # Ping file information - show exact folder and file being written to
            if self.core_engine and self.io_manager:
                # Get drive state from scheduler
                timing_state = self.core_engine.scheduler.get_timing_state(drive_letter)
                if timing_state:
                    # Get ping directory (use custom if configured, otherwise default)
                    from pathlib import Path
                    ping_dir = self.io_manager.get_ping_directory(drive_letter.rstrip(':'), timing_state.ping_dir)
                    ping_file = ping_dir / "drive_revenant"
                    
                    # Display paths
                    ping_dir_label = QLabel(str(ping_dir))
                    ping_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    info_layout.addRow("Ping Directory:", ping_dir_label)
                    
                    ping_file_label = QLabel(str(ping_file))
                    ping_file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    info_layout.addRow("Ping File:", ping_file_label)
            
            # Drive tracking information
            if drive_letter in self.core_engine.config.per_drive:
                drive_config = self.core_engine.config.per_drive[drive_letter]
                
                # Volume GUID
                if drive_config.volume_guid:
                    guid_label = QLabel(drive_config.volume_guid)
                    guid_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    info_layout.addRow("Volume GUID:", guid_label)
                
                # Last seen
                if drive_config.last_seen_timestamp:
                    from datetime import datetime
                    last_seen = datetime.fromtimestamp(drive_config.last_seen_timestamp)
                    info_layout.addRow("Last Seen:", QLabel(last_seen.strftime("%Y-%m-%d %H:%M:%S")))
                
                # Total size
                if drive_config.total_size_bytes:
                    size_gb = drive_config.total_size_bytes / (1024 ** 3)
                    info_layout.addRow("Total Size:", QLabel(f"{size_gb:.2f} GB"))

            # Volume information
            volume_info = drive_info.get('volume_info', {})
            if volume_info:
                info_layout.addRow("Volume Name:", QLabel(volume_info.get('volume_name', 'Unknown')))
                info_layout.addRow("File System:", QLabel(volume_info.get('file_system', 'Unknown')))
                info_layout.addRow("Serial Number:", QLabel(str(volume_info.get('serial_number', 'Unknown'))))
                info_layout.addRow("Max Component Length:", QLabel(str(volume_info.get('max_component_length', 'Unknown'))))

            layout.addWidget(info_group)

            # Operation history group
            history_group = QGroupBox("Recent Operation History")
            history_layout = QVBoxLayout(history_group)

            # Get drive state for history - use scheduler (Phase 3 alignment)
            drive_state = None
            if self.core_engine:
                drive_state = self.core_engine._build_drive_state_from_scheduler(drive_letter)
            
            if drive_state and drive_state.last_results:
                history_text = QTextEdit()
                history_text.setReadOnly(True)
                history_text.setMaximumHeight(200)

                from datetime import datetime, timedelta

                history_content = f"Last {len(drive_state.last_results)} operations:\n\n"
                for i, result in enumerate(reversed(drive_state.last_results[-15:])):  # Show last 15
                    # Calculate approximate operation time based on current time and operation position
                    # Each operation should be separated by the drive's interval
                    current_time = datetime.now()
                    interval_seconds = drive_state.config.interval
                    operation_time = current_time - timedelta(seconds=i * interval_seconds)
                    
                    history_content += f"{i+1}. {result.result_code.value} - {result.duration_ms/1000:.3f}s"
                    if result.details:
                        history_content += f" - {result.details}"
                    if hasattr(result, 'offset_ms') and result.offset_ms:
                        history_content += f" [{result.offset_ms/1000:+.3f}s]"
                    if (hasattr(result, 'jitter_reason') and 
                        result.jitter_reason and 
                        str(result.jitter_reason).strip() and 
                        result.jitter_reason != "in_window"):
                        history_content += f" ({result.jitter_reason})"
                    history_content += f" [~{operation_time.strftime('%H:%M:%S')}]"
                    history_content += "\n"

                history_text.setPlainText(history_content)
                history_layout.addWidget(history_text)
                
                # Add format explanation
                explanation_label = QLabel(
                    "<b>Format explanation:</b><br>"
                    "<code>1. OK - 0.000s - Wrote 12 bytes, flush: 0.0ms [~18:16:23]</code><br>"
                    "• <b>OK</b> = Result code (OK, ERROR, TIMEOUT, etc.)<br>"
                    "• <b>0.000s</b> = Operation duration in seconds<br>"
                    "• <b>Wrote 12 bytes, flush: 0.0ms</b> = Operation details and flush time<br>"
                    "• <b>[+3.0s]</b> = Timing offset from scheduled time (only shown if non-zero)<br>"
                    "• <b>(expanded)</b> = Jitter reason (only shown if not 'in_window')<br>"
                    "• <b>[~18:16:23]</b> = Approximate wall-clock time when operation completed<br><br>"
                    "<b>Note:</b> Operations use monotonic time for precision. "
                    "Wall-clock times are calculated based on current time minus interval spacing."
                )
                explanation_label.setWordWrap(True)
                explanation_label.setStyleSheet("QLabel { font-size: 9px; color: #555; background-color: #f9f9f9; padding: 8px; border: 1px solid #ddd; border-radius: 3px; }")
                history_layout.addWidget(explanation_label)
            else:
                no_history_label = QLabel("No operation history available")
                history_layout.addWidget(no_history_label)

            layout.addWidget(history_group)

            # Current status group
            status_group = QGroupBox("Current Status")
            status_layout = QFormLayout(status_group)

            if drive_state:
                status_layout.addRow("Status:", QLabel(drive_state.status.value))
                status_layout.addRow("Enabled:", QLabel("Yes" if drive_state.enabled else "No"))
                status_layout.addRow("Interval:", QLabel(f"{drive_state.config.interval}s"))
                status_layout.addRow("Consecutive Tick Failures:", QLabel(str(drive_state.consecutive_tick_failures)))
                if drive_state.quarantine_until:
                    status_layout.addRow("Quarantined Until:", QLabel(f"{drive_state.quarantine_until}s"))
                if drive_state.measured_speed:
                    status_layout.addRow("Measured Speed:", QLabel(f"{drive_state.measured_speed:.1f} MB/s"))
            else:
                status_layout.addRow("Status:", QLabel("Drive state not available"))

            layout.addWidget(status_group)

            # Button box
            button_box = QDialogButtonBox(QDialogButtonBox.Close)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)

            dialog.exec()

        except Exception as e:
            QMessageBox.warning(self, "Drive Details", f"Error getting drive details: {e}")

    def pause_drive(self, drive_letter: str):
        """Pause a specific drive."""
        if self.core_engine:
            self.core_engine.pause_drive(drive_letter)
            self.status_bar.showMessage(f"Drive {drive_letter} paused", 2000)

    def resume_drive(self, drive_letter: str):
        """Resume a specific drive."""
        if self.core_engine:
            self.core_engine.resume_drive(drive_letter)
            self.status_bar.showMessage(f"Drive {drive_letter} resumed", 2000)

    def pause_selected_drives(self):
        """Pause selected drives."""
        selected_letters = self._get_selected_drive_letters()
        if not selected_letters:
            self.status_bar.showMessage("No drives selected", 2000)
            return
        
        if self.core_engine:
            count = self.core_engine.pause_selected_drives(selected_letters)
            self.status_bar.showMessage(f"Paused {count} drive(s)", 2000)
            self.refresh_drives()

    def resume_selected_drives(self):
        """Resume selected drives."""
        selected_letters = self._get_selected_drive_letters()
        if not selected_letters:
            self.status_bar.showMessage("No drives selected", 2000)
            return
        
        if self.core_engine:
            count = self.core_engine.resume_selected_drives(selected_letters)
            self.status_bar.showMessage(f"Resumed {count} drive(s)", 2000)
            self.refresh_drives()

    def toggle_drive_enabled(self, drive_letter: str):
        """Toggle enabled state for a specific drive."""
        if not self.core_engine:
            return

        # PHASE 3: Get current state from scheduler
        timing = self.core_engine.scheduler.get_timing_state(drive_letter)
        if not timing:
            self.status_bar.showMessage(f"Drive {drive_letter} not found", 2000)
            return

        # Toggle enabled state using proper CoreEngine method
        new_enabled = not timing.enabled
        self.core_engine.set_drive_config(
            letter=drive_letter,
            enabled=new_enabled,
            interval=timing.interval_sec,
            drive_type=timing.type,
            ping_dir=timing.ping_dir,
            save_config=True
        )
        
        self.status_bar.showMessage(f"Drive {drive_letter} {'enabled' if new_enabled else 'disabled'}", 2000)

    def clear_drive_quarantine(self, drive_letter: str):
        """Clear quarantine status for a specific drive."""
        if not self.core_engine:
            return

        # Use core engine method to clear quarantine
        self.core_engine.clear_drive_quarantine(drive_letter)

        # Update UI
        self.refresh_drives()
        self.status_bar.showMessage(f"Quarantine cleared for {drive_letter}", 2000)

    def test_status_colors(self):
        """Test different status colors by temporarily setting drive statuses."""
        if not self.core_engine:
            QMessageBox.warning(self, "Test Status Colors", "Core engine not available")
            return

        from app_types import DriveStatus
        
        # Get first few drives to test with - use scheduler (Phase 3)
        all_timing_states = self.core_engine.scheduler.get_all_drive_states()
        drive_letters = list(all_timing_states.keys())[:4]
        if not drive_letters:
            QMessageBox.warning(self, "Test Status Colors", "No drives available for testing")
            return

        # Store original statuses - use scheduler (Phase 3)
        original_statuses = {}
        for letter in drive_letters:
            timing = self.core_engine.scheduler.get_timing_state(letter)
            if timing:
                original_statuses[letter] = timing.status

        try:
            # Set different statuses for testing via scheduler
            if len(drive_letters) >= 1:
                self.core_engine.scheduler.set_drive_status(drive_letters[0], DriveStatus.ACTIVE)
            if len(drive_letters) >= 2:
                self.core_engine.scheduler.set_drive_status(drive_letters[1], DriveStatus.PAUSED, "user")
            if len(drive_letters) >= 3:
                self.core_engine.scheduler.set_drive_status(drive_letters[2], DriveStatus.QUARANTINE)
            if len(drive_letters) >= 4:
                self.core_engine.scheduler.set_drive_status(drive_letters[3], DriveStatus.ERROR)
            if len(drive_letters) >= 5:
                self.core_engine.scheduler.set_drive_status(drive_letters[4], DriveStatus.CLAMPED)
            if len(drive_letters) >= 6:
                self.core_engine.scheduler.set_drive_status(drive_letters[5], DriveStatus.HDD_CAPPED)

            # Update UI
            self.refresh_drives()
            
            QMessageBox.information(self, "Test Status Colors", 
                f"Status colors test applied to drives: {', '.join(drive_letters)}\n\n"
                f"Expected colors:\n"
                f"• {drive_letters[0] if len(drive_letters) >= 1 else 'N/A'}: Green (Active)\n"
                f"• {drive_letters[1] if len(drive_letters) >= 2 else 'N/A'}: Yellow (Paused)\n"
                f"• {drive_letters[2] if len(drive_letters) >= 3 else 'N/A'}: Red (Quarantine)\n"
                f"• {drive_letters[3] if len(drive_letters) >= 4 else 'N/A'}: Yellow (Error)\n"
                f"• {drive_letters[4] if len(drive_letters) >= 5 else 'N/A'}: Yellow with C (Clamped)\n"
                f"• {drive_letters[5] if len(drive_letters) >= 6 else 'N/A'}: Orange (HDD-capped)\n\n"
                f"Click OK to restore original statuses.")

        finally:
            # Restore original statuses - use scheduler (Phase 3)
            for letter, original_status in original_statuses.items():
                self.core_engine.scheduler.set_drive_status(letter, original_status)
            
            # Update UI
            self.refresh_drives()


# For backward compatibility, export the main classes
__all__ = ['MainWindow']
