# app_gui_settings_dialog.py
# Version: 1.0.4
# Settings dialog for Drive Revenant GUI

from typing import Optional, Dict, Any

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QFormLayout,
    QGroupBox, QCheckBox, QSpinBox, QLabel, QDialogButtonBox,
    QMessageBox, QScrollArea, QWidget, QPushButton
)
from PySide6.QtCore import Qt

from app_config import ConfigManager, AppConfig

class SettingsDialog(QDialog):
    """Comprehensive settings dialog for Drive Revenant."""
    
    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.config = config_manager.load_config()
        self.original_config = self._deep_copy_config(self.config)
        
        self.setWindowTitle("Drive Revenant Settings")
        self.setModal(True)
        self.resize(600, 500)
        
        self.setup_ui()
        self.load_settings()
    
    def _deep_copy_config(self, config: AppConfig) -> AppConfig:
        """Create a deep copy of the config for rollback purposes."""
        return AppConfig(
            version=config.version,
            install_id=config.install_id,
            portable=config.portable,
            autostart=config.autostart,
            autostart_method=config.autostart_method,
            treat_unknown_as_ssd=config.treat_unknown_as_ssd,
            default_interval_sec=config.default_interval_sec,
            interval_min_sec=config.interval_min_sec,
            jitter_sec=config.jitter_sec,
            hdd_max_gap_sec=config.hdd_max_gap_sec,
            deadline_margin_sec=config.deadline_margin_sec,
            pause_on_battery=config.pause_on_battery,
            idle_pause_min=config.idle_pause_min,
            policy_precedence=config.policy_precedence.copy() if config.policy_precedence else None,
            fsync=config.fsync,
            max_flush_ms=config.max_flush_ms,
            lock_retry_ms=config.lock_retry_ms,
            error_quarantine_after=config.error_quarantine_after,
            error_quarantine_sec=config.error_quarantine_sec,
            log_max_kb=config.log_max_kb,
            log_history_count=config.log_history_count,
            log_ndjson=config.log_ndjson,
            disable_hotkeys=config.disable_hotkeys,
            suppress_quit_confirm=config.suppress_quit_confirm,
            suppress_ssd_warnings=config.suppress_ssd_warnings.copy() if config.suppress_ssd_warnings else None,
            gui_update_interval_ms=config.gui_update_interval_ms,
            gui_update_interval_editing_ms=config.gui_update_interval_editing_ms,
            hide_console_window=config.hide_console_window,
            drive_stale_removal_days=getattr(config, 'drive_stale_removal_days', 15),
            drive_scan_mode=getattr(config, 'drive_scan_mode', 'quick'),
            forced_drive_letters=getattr(config, 'forced_drive_letters', ''),
            per_drive=config.per_drive.copy() if config.per_drive else None
        )
    
    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        
        # Config info header
        config_info = QLabel(f"Configuration file: {self.config_manager.config_path}\nLogs directory: {self.config_manager.get_log_dir()}")
        config_info.setStyleSheet("QLabel { font-size: 10px; color: #666; padding: 5px; background-color: #f0f0f0; border-radius: 3px; }")
        config_info.setWordWrap(True)
        layout.addWidget(config_info)
        
        # Create tab widget
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)
        
        # Create tabs
        tab_widget.addTab(self.create_general_tab(), "General")
        tab_widget.addTab(self.create_io_tab(), "I/O")
        tab_widget.addTab(self.create_policy_tab(), "Policy")
        tab_widget.addTab(self.create_error_tab(), "Error Handling")
        tab_widget.addTab(self.create_logging_tab(), "Logging")
        tab_widget.addTab(self.create_interface_tab(), "Interface")
        
        # Button box
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def create_general_tab(self) -> QWidget:
        """Create the general settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # General settings group
        general_group = QGroupBox("General Settings")
        general_group.setToolTip("Basic timing and scheduling configuration")
        general_layout = QFormLayout(general_group)
        
        # Default interval
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)  # 5 seconds to 1 hour
        self.interval_spin.setSuffix(" seconds")
        self.interval_spin.setToolTip("Default interval between operations for new drives (5s - 1h)")
        general_layout.addRow("Default Interval:", self.interval_spin)
        
        # Jitter
        self.jitter_spin = QSpinBox()
        self.jitter_spin.setRange(0, 60)
        self.jitter_spin.setSuffix(" seconds")
        self.jitter_spin.setToolTip("Random jitter window to spread operations and avoid conflicts (0-60s)")
        general_layout.addRow("Jitter Window:", self.jitter_spin)
        
        # HDD max gap
        self.hdd_gap_spin = QSpinBox()
        self.hdd_gap_spin.setRange(1, 60)
        self.hdd_gap_spin.setSuffix(" seconds")
        self.hdd_gap_spin.setToolTip("Maximum time between HDD operations to prevent drive spin-down (1-60s)")
        general_layout.addRow("HDD Max Gap:", self.hdd_gap_spin)
        
        # Treat unknown as SSD
        self.treat_unknown_ssd_check = QCheckBox()
        self.treat_unknown_ssd_check.setToolTip("Treat unknown drive types as SSDs (safer for write operations)")
        general_layout.addRow("Treat Unknown as SSD:", self.treat_unknown_ssd_check)
        
        # Interval min sec
        self.interval_min_spin = QSpinBox()
        self.interval_min_spin.setRange(1, 60)
        self.interval_min_spin.setSuffix(" seconds")
        self.interval_min_spin.setToolTip("Minimum allowed interval for any drive (1-60s)")
        general_layout.addRow("Minimum Interval:", self.interval_min_spin)
        
        # Deadline margin sec
        self.deadline_margin_spin = QSpinBox()
        self.deadline_margin_spin.setRange(1, 30)
        self.deadline_margin_spin.setSuffix(" seconds")
        self.deadline_margin_spin.setToolTip("Safety margin for operation deadlines (1-30s)")
        general_layout.addRow("Deadline Margin:", self.deadline_margin_spin)
        
        layout.addWidget(general_group)
        layout.addStretch()
        return widget
    
    def create_io_tab(self) -> QWidget:
        """Create the I/O settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # I/O settings group
        io_group = QGroupBox("I/O Settings")
        io_group.setToolTip("File system operation parameters")
        io_layout = QFormLayout(io_group)
        
        # Max flush time
        self.max_flush_spin = QSpinBox()
        self.max_flush_spin.setRange(50, 1000)
        self.max_flush_spin.setSuffix(" ms")
        self.max_flush_spin.setToolTip("Maximum time to wait for file flush operations (50-1000ms)")
        io_layout.addRow("Max Flush Time:", self.max_flush_spin)
        
        # Lock retry time
        self.lock_retry_spin = QSpinBox()
        self.lock_retry_spin.setRange(100, 5000)
        self.lock_retry_spin.setSuffix(" ms")
        self.lock_retry_spin.setToolTip("Time to retry when files are locked by other processes (100-5000ms)")
        io_layout.addRow("Lock Retry Time:", self.lock_retry_spin)
        
        # Fsync enabled
        self.fsync_check = QCheckBox()
        self.fsync_check.setToolTip("Force file system synchronization after writes (slower but safer)")
        io_layout.addRow("Enable Fsync:", self.fsync_check)
        
        layout.addWidget(io_group)
        layout.addStretch()
        return widget
    
    def create_policy_tab(self) -> QWidget:
        """Create the policy settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Policy settings group
        policy_group = QGroupBox("Policy Settings")
        policy_group.setToolTip("Automatic pause/resume behavior based on system conditions")
        policy_layout = QFormLayout(policy_group)
        
        # Pause on battery
        self.pause_on_battery_check = QCheckBox()
        self.pause_on_battery_check.setToolTip("Automatically pause operations when running on battery power")
        policy_layout.addRow("Pause on Battery:", self.pause_on_battery_check)
        
        # Idle pause minimum
        self.idle_pause_min_spin = QSpinBox()
        self.idle_pause_min_spin.setRange(0, 60)
        self.idle_pause_min_spin.setSuffix(" minutes")
        self.idle_pause_min_spin.setToolTip("Pause operations when system has been idle for this many minutes (0 = disabled)")
        policy_layout.addRow("Idle Pause Threshold:", self.idle_pause_min_spin)
        
        # Disable hotkeys
        self.disable_hotkeys_check = QCheckBox()
        self.disable_hotkeys_check.setToolTip("Disable Ctrl+Q (exit to tray) and Ctrl+C (quit) keyboard shortcuts")
        policy_layout.addRow("Disable Hotkeys:", self.disable_hotkeys_check)
        
        layout.addWidget(policy_group)
        layout.addStretch()
        return widget
    
    def create_error_tab(self) -> QWidget:
        """Create the error handling tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Error handling group
        error_group = QGroupBox("Error Handling")
        error_group.setToolTip("How the system responds to operation failures")
        error_layout = QFormLayout(error_group)
        
        # Error quarantine after
        self.error_quarantine_after_spin = QSpinBox()
        self.error_quarantine_after_spin.setRange(1, 20)
        self.error_quarantine_after_spin.setToolTip("Number of consecutive failures before quarantining a drive (1-20)")
        error_layout.addRow("Quarantine After Errors:", self.error_quarantine_after_spin)
        
        # Error quarantine duration
        self.error_quarantine_sec_spin = QSpinBox()
        self.error_quarantine_sec_spin.setRange(10, 300)
        self.error_quarantine_sec_spin.setSuffix(" seconds")
        self.error_quarantine_sec_spin.setToolTip("How long to quarantine a drive after repeated failures (10-300s)")
        error_layout.addRow("Quarantine Duration:", self.error_quarantine_sec_spin)
        
        layout.addWidget(error_group)
        layout.addStretch()
        return widget
    
    def create_logging_tab(self) -> QWidget:
        """Create the logging settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Logging settings group
        logging_group = QGroupBox("Logging")
        logging_group.setToolTip("Log file management and format options")
        logging_layout = QFormLayout(logging_group)
        
        # NDJSON logging
        self.ndjson_check = QCheckBox()
        self.ndjson_check.setToolTip("Enable structured JSON logging for analysis tools")
        logging_layout.addRow("Enable NDJSON Logging:", self.ndjson_check)
        
        # Log max size
        self.log_max_kb_spin = QSpinBox()
        self.log_max_kb_spin.setRange(50, 1000)
        self.log_max_kb_spin.setSuffix(" KB")
        self.log_max_kb_spin.setToolTip("Maximum size of individual log files before rotation (50-1000KB)")
        logging_layout.addRow("Max Log Size:", self.log_max_kb_spin)
        
        # Log history count
        self.log_history_spin = QSpinBox()
        self.log_history_spin.setRange(1, 10)
        self.log_history_spin.setToolTip("Number of historical log files to keep (1-10)")
        logging_layout.addRow("Log History Count:", self.log_history_spin)
        
        layout.addWidget(logging_group)
        
        # Log management group
        log_management_group = QGroupBox("Log Management")
        log_management_group.setToolTip("Log retention policy and management options")
        log_management_layout = QFormLayout(log_management_group)
        
        # Log retention info
        retention_info = QLabel(f"Current policy: Keep {self.config.log_history_count} log files, max {self.config.log_max_kb}KB each")
        retention_info.setStyleSheet("QLabel { font-size: 10px; color: #666; }")
        retention_info.setWordWrap(True)
        
        # Open logs folder button
        open_logs_btn = QPushButton("Open Logs Folder")
        open_logs_btn.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                border: 1px solid #ccc;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """)
        open_logs_btn.clicked.connect(self._open_logs_folder)
        
        log_management_layout.addRow(retention_info)
        log_management_layout.addRow(open_logs_btn)
        
        layout.addWidget(log_management_group)
        layout.addStretch()
        return widget
    
    def create_interface_tab(self) -> QWidget:
        """Create the interface settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Interface settings group
        interface_group = QGroupBox("Interface")
        interface_group.setToolTip("User interface behavior and appearance")
        interface_layout = QFormLayout(interface_group)
        
        # Suppress quit confirmation
        self.suppress_quit_check = QCheckBox()
        self.suppress_quit_check.setToolTip("Skip confirmation dialog when exiting the application")
        interface_layout.addRow("Suppress Exit Confirmation:", self.suppress_quit_check)
        
        layout.addWidget(interface_group)
        
        # Advanced Drive Scanning group
        from PySide6.QtWidgets import QLineEdit
        advanced_group = QGroupBox("Advanced Drive Scanning")
        advanced_group.setToolTip("Advanced options for drive detection and monitoring")
        advanced_layout = QFormLayout(advanced_group)
        
        # Forced drive letters
        self.forced_drives_edit = QLineEdit()
        self.forced_drives_edit.setPlaceholderText("e.g., F,J,K")
        self.forced_drives_edit.setToolTip(
            "Comma-separated drive letters to always check during quick scans.\n"
            "Use this to force detection of specific drives (e.g., drives that changed letters).\n"
            "Forced drives are given a 13-day last_seen timestamp (removed after 2 days if not found).\n"
            "Leave empty to disable. Example: F,J,K"
        )
        advanced_layout.addRow("Force Check Drives:", self.forced_drives_edit)
        
        # Stale removal threshold
        self.stale_days_spin = QSpinBox()
        self.stale_days_spin.setRange(0, 90)
        self.stale_days_spin.setSuffix(" days")
        self.stale_days_spin.setToolTip(
            "Remove drives from config if not seen for this many days.\n"
            "0 = Disabled (drives never auto-removed)\n"
            "15 = Default (removes offline drives after 15 days)\n"
            "Forced drives get 2-day grace period before removal."
        )
        advanced_layout.addRow("Stale Drive Removal:", self.stale_days_spin)
        
        layout.addWidget(advanced_group)
        
        # GUI settings group
        gui_group = QGroupBox("GUI Performance")
        gui_group.setToolTip("User interface update and responsiveness settings")
        gui_layout = QFormLayout(gui_group)
        
        # GUI update interval
        self.gui_update_interval_spin = QSpinBox()
        self.gui_update_interval_spin.setRange(100, 5000)  # 100ms to 5 seconds
        self.gui_update_interval_spin.setSuffix(" ms")
        self.gui_update_interval_spin.setToolTip("How often the GUI updates when not editing (100ms - 5s). Lower values = more responsive but higher CPU usage.")
        gui_layout.addRow("Update Interval (Normal):", self.gui_update_interval_spin)
        
        # GUI update interval when editing
        self.gui_update_editing_spin = QSpinBox()
        self.gui_update_editing_spin.setRange(200, 10000)  # 200ms to 10 seconds
        self.gui_update_editing_spin.setSuffix(" ms")
        self.gui_update_editing_spin.setToolTip("How often the GUI updates when editing table cells (200ms - 10s). Slower updates prevent interference with editing.")
        gui_layout.addRow("Update Interval (Editing):", self.gui_update_editing_spin)
        
        layout.addWidget(gui_group)
        layout.addStretch()
        return widget
    
    def load_settings(self):
        """Load current configuration into the UI controls."""
        self.interval_spin.setValue(self.config.default_interval_sec)
        self.jitter_spin.setValue(self.config.jitter_sec)
        self.hdd_gap_spin.setValue(int(self.config.hdd_max_gap_sec))
        self.treat_unknown_ssd_check.setChecked(self.config.treat_unknown_as_ssd)
        self.interval_min_spin.setValue(getattr(self.config, 'interval_min_sec', 5))
        self.deadline_margin_spin.setValue(getattr(self.config, 'deadline_margin_sec', 5))
        self.max_flush_spin.setValue(self.config.max_flush_ms)
        self.lock_retry_spin.setValue(self.config.lock_retry_ms)
        self.fsync_check.setChecked(self.config.fsync)
        self.pause_on_battery_check.setChecked(self.config.pause_on_battery)
        self.idle_pause_min_spin.setValue(self.config.idle_pause_min)
        self.disable_hotkeys_check.setChecked(self.config.disable_hotkeys)
        self.error_quarantine_after_spin.setValue(self.config.error_quarantine_after)
        self.error_quarantine_sec_spin.setValue(self.config.error_quarantine_sec)
        self.ndjson_check.setChecked(self.config.log_ndjson)
        self.log_max_kb_spin.setValue(self.config.log_max_kb)
        self.log_history_spin.setValue(self.config.log_history_count)
        self.suppress_quit_check.setChecked(self.config.suppress_quit_confirm)
        self.gui_update_interval_spin.setValue(self.config.gui_update_interval_ms)
        self.gui_update_editing_spin.setValue(self.config.gui_update_interval_editing_ms)
        self.forced_drives_edit.setText(getattr(self.config, 'forced_drive_letters', ''))
        self.stale_days_spin.setValue(getattr(self.config, 'drive_stale_removal_days', 15))
    
    def save_settings(self) -> bool:
        """Save the current UI settings to configuration."""
        try:
            # Update config with current UI values
            self.config.default_interval_sec = self.interval_spin.value()
            self.config.jitter_sec = self.jitter_spin.value()
            self.config.hdd_max_gap_sec = self.hdd_gap_spin.value()
            self.config.treat_unknown_as_ssd = self.treat_unknown_ssd_check.isChecked()
            self.config.max_flush_ms = self.max_flush_spin.value()
            self.config.lock_retry_ms = self.lock_retry_spin.value()
            self.config.fsync = self.fsync_check.isChecked()
            self.config.pause_on_battery = self.pause_on_battery_check.isChecked()
            self.config.idle_pause_min = self.idle_pause_min_spin.value()
            self.config.disable_hotkeys = self.disable_hotkeys_check.isChecked()
            self.config.error_quarantine_after = self.error_quarantine_after_spin.value()
            self.config.error_quarantine_sec = self.error_quarantine_sec_spin.value()
            self.config.log_ndjson = self.ndjson_check.isChecked()
            self.config.log_max_kb = self.log_max_kb_spin.value()
            self.config.log_history_count = self.log_history_spin.value()
            self.config.suppress_quit_confirm = self.suppress_quit_check.isChecked()
            self.config.gui_update_interval_ms = self.gui_update_interval_spin.value()
            self.config.gui_update_interval_editing_ms = self.gui_update_editing_spin.value()
            self.config.forced_drive_letters = self.forced_drives_edit.text().strip()
            self.config.drive_stale_removal_days = self.stale_days_spin.value()
            
            # Save to file
            return self.config_manager.save_config(self.config)
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save settings: {e}")
            return False
    
    def _open_logs_folder(self):
        """Open the logs folder in the system file manager."""
        import os
        import subprocess
        import platform
        
        log_dir = self.config_manager.get_log_dir()
        try:
            if platform.system() == "Windows":
                os.startfile(log_dir)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", log_dir])
            else:  # Linux
                subprocess.run(["xdg-open", log_dir])
        except Exception as e:
            QMessageBox.warning(self, "Open Folder", f"Could not open logs folder: {e}")
    
    def accept(self):
        """Handle dialog acceptance."""
        if self.save_settings():
            super().accept()
        else:
            # Don't close dialog if save failed
            pass
