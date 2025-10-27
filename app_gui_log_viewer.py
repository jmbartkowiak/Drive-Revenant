# app_gui_log_viewer.py
# Version: 1.0.0
# Log viewer dialog for Drive Revenant GUI

import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QPushButton, QSplitter,
    QTextEdit, QComboBox, QGroupBox, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont

from app_logging import LoggingManager

class LogParser:
    """Parse human-readable log files into structured data."""

    def __init__(self):
        self.log_pattern = re.compile(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d) (\w+) (\w+) (\w+):(\w+) i(\d+)s ([\d.-]+)ms ([\d.-]+)ms(?: (\([^)]*\)))? (.+)'
        )

    def parse_log_file(self, file_path):
        """Parse a log file and return structured data."""
        entries = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    match = self.log_pattern.match(line)
                    if match:
                        groups = match.groups()
                        timestamp_str = groups[0]
                        op_type = groups[1]
                        result = groups[2]
                        drive = groups[3]
                        drive_type = groups[4]
                        interval = groups[5]
                        duration = groups[6]
                        offset = groups[7]
                        jitter = groups[8] if len(groups) > 8 and groups[8] else ""
                        details = groups[9] if len(groups) > 9 else ""

                        try:
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                            entry = {
                                'timestamp': timestamp,
                                'operation_type': op_type,
                                'result_code': result,
                                'drive_letter': drive,
                                'drive_type': drive_type,
                                'interval': int(interval),
                                'duration_ms': float(duration) if duration != '-' else 0,
                                'offset_ms': float(offset) if offset != '-' else 0,
                                'jitter_reason': jitter.strip('()') if jitter else 'in_window',
                                'details': details,
                                'file_path': str(file_path),
                                'line_number': line_num
                            }
                            entries.append(entry)
                        except ValueError as e:
                            # Skip malformed lines
                            continue

        except Exception as e:
            print(f"Error parsing log file {file_path}: {e}")

        return entries

    def parse_all_logs(self, log_files):
        """Parse all log files and return combined data."""
        all_entries = []
        for log_file in log_files:
            entries = self.parse_log_file(log_file)
            all_entries.extend(entries)

        # Sort by timestamp (newest first for display)
        all_entries.sort(key=lambda x: x['timestamp'], reverse=True)
        return all_entries

    def get_drive_summary(self, entries):
        """Get summary statistics for each drive."""
        drive_stats = {}

        for entry in entries:
            drive = entry['drive_letter']
            if drive not in drive_stats:
                drive_stats[drive] = {
                    'total_operations': 0,
                    'successful_operations': 0,
                    'failed_operations': 0,
                    'last_operation': None,
                    'drive_type': entry['drive_type'],
                    'interval': entry['interval'],
                    'recent_operations': []
                }

            drive_stats[drive]['total_operations'] += 1
            if entry['result_code'] == 'OK':
                drive_stats[drive]['successful_operations'] += 1
            else:
                drive_stats[drive]['failed_operations'] += 1

            drive_stats[drive]['last_operation'] = entry['timestamp']

            # Keep only last 10 operations per drive
            if len(drive_stats[drive]['recent_operations']) >= 10:
                drive_stats[drive]['recent_operations'].pop(0)
            drive_stats[drive]['recent_operations'].append(entry)

        return drive_stats

class LogViewerDialog(QDialog):
    """Log viewer dialog with parsed drive information."""
    
    def __init__(self, logging_manager: LoggingManager, parent=None):
        super().__init__(parent)
        self.logging_manager = logging_manager
        self.log_parser = LogParser()
        self.current_entries = []
        
        self.setWindowTitle("Drive Revenant Log Viewer")
        self.setModal(False)
        self.resize(1000, 700)
        
        self.setup_ui()
        self.load_available_logs()
    
    def setup_ui(self):
        """Set up the user interface."""
        layout = QVBoxLayout(self)
        
        # Controls
        controls_layout = QHBoxLayout()
        
        # Log file selector
        self.log_selector = QComboBox()
        self.log_selector.addItem("All Logs", None)
        controls_layout.addWidget(QLabel("Log File:"))
        controls_layout.addWidget(self.log_selector)
        
        # Refresh button
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_data)
        controls_layout.addWidget(self.refresh_btn)
        
        # Export button
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.clicked.connect(self.export_to_csv)
        controls_layout.addWidget(self.export_btn)
        
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        # Main content
        self.splitter = QSplitter(Qt.Vertical)
        
        # Drive summary table
        self.summary_group = QGroupBox("Drive Summary")
        summary_layout = QVBoxLayout()
        
        self.summary_table = QTableWidget()
        self.summary_table.setColumnCount(6)
        self.summary_table.setHorizontalHeaderLabels([
            "Drive", "Type", "Total Ops", "Success", "Failed", "Last Operation"
        ])
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        summary_layout.addWidget(self.summary_table)
        
        self.summary_group.setLayout(summary_layout)
        self.splitter.addWidget(self.summary_group)
        
        # Recent operations table
        self.operations_group = QGroupBox("Recent Operations")
        operations_layout = QVBoxLayout()
        
        self.operations_table = QTableWidget()
        self.operations_table.setColumnCount(7)
        self.operations_table.setHorizontalHeaderLabels([
            "Time", "Drive", "Operation", "Result", "Duration", "Offset", "Details"
        ])
        self.operations_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        operations_layout.addWidget(self.operations_table)
        
        self.operations_group.setLayout(operations_layout)
        self.splitter.addWidget(self.operations_group)
        
        # Raw log view
        self.raw_group = QGroupBox("Raw Log Content")
        raw_layout = QVBoxLayout()
        
        self.raw_text = QTextEdit()
        self.raw_text.setReadOnly(True)
        self.raw_text.setFont(QFont("Consolas", 9))
        raw_layout.addWidget(self.raw_text)
        
        self.raw_group.setLayout(raw_layout)
        self.splitter.addWidget(self.raw_group)
        
        # Set splitter proportions
        self.splitter.setSizes([300, 400, 300])
        
        layout.addWidget(self.splitter)
        
        # Close button
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons_layout.addWidget(close_btn)
        layout.addLayout(buttons_layout)
        
        # Connect signals
        self.log_selector.currentIndexChanged.connect(self.refresh_data)
    
    def load_available_logs(self):
        """Load available log files into the selector."""
        self.log_selector.clear()
        self.log_selector.addItem("All Logs", None)
        
        if self.logging_manager:
            log_files = self.logging_manager.get_log_files()
            for log_file in log_files:
                if log_file.exists():
                    self.log_selector.addItem(log_file.name, log_file)
    
    def refresh_data(self):
        """Refresh the displayed data."""
        selected_log = self.log_selector.currentData()
        log_files_to_parse = [selected_log] if selected_log else [
            log_file for log_file in self.logging_manager.get_log_files() if log_file.exists()
        ]
        
        # Parse logs
        self.current_entries = self.log_parser.parse_all_logs(log_files_to_parse)
        drive_stats = self.log_parser.get_drive_summary(self.current_entries)
        
        # Update summary table
        self.summary_table.setRowCount(len(drive_stats))
        for row, (drive, stats) in enumerate(drive_stats.items()):
            self.summary_table.setItem(row, 0, QTableWidgetItem(drive))
            self.summary_table.setItem(row, 1, QTableWidgetItem(stats['drive_type']))
            self.summary_table.setItem(row, 2, QTableWidgetItem(str(stats['total_operations'])))
            self.summary_table.setItem(row, 3, QTableWidgetItem(str(stats['successful_operations'])))
            self.summary_table.setItem(row, 4, QTableWidgetItem(str(stats['failed_operations'])))
            
            last_op = stats['last_operation']
            if last_op:
                last_op_str = last_op.strftime('%Y-%m-%d %H:%M:%S')
                self.summary_table.setItem(row, 5, QTableWidgetItem(last_op_str))
            else:
                self.summary_table.setItem(row, 5, QTableWidgetItem('Never'))
        
        # Update operations table (show last 50 operations)
        recent_ops = self.current_entries[:50] if len(self.current_entries) > 50 else self.current_entries
        
        self.operations_table.setRowCount(len(recent_ops))
        for row, entry in enumerate(recent_ops):
            self.operations_table.setItem(row, 0, QTableWidgetItem(entry['timestamp'].strftime('%H:%M:%S')))
            self.operations_table.setItem(row, 1, QTableWidgetItem(entry['drive_letter']))
            self.operations_table.setItem(row, 2, QTableWidgetItem(entry['operation_type']))
            self.operations_table.setItem(row, 3, QTableWidgetItem(entry['result_code']))
            self.operations_table.setItem(row, 4, QTableWidgetItem(f"{entry['duration_ms']:.1f}ms"))
            self.operations_table.setItem(row, 5, QTableWidgetItem(f"{entry['offset_ms']:.1f}ms"))
            self.operations_table.setItem(row, 6, QTableWidgetItem(entry['details'][:100]))
        
        # Update raw log content
        if selected_log and selected_log.exists():
            try:
                with open(selected_log, 'r', encoding='utf-8') as f:
                    self.raw_text.setPlainText(f.read())
            except Exception as e:
                self.raw_text.setPlainText(f"Error reading log file: {e}")
        else:
            self.raw_text.clear()
    
    def export_to_csv(self):
        """Export current log data to CSV file."""
        if not self.current_entries:
            QMessageBox.information(self, "Export", "No log data to export")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Log Data", "drive_revenant_logs.csv", "CSV Files (*.csv)"
        )
        
        if file_path:
            try:
                import csv
                with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = [
                        'timestamp', 'operation_type', 'result_code', 'drive_letter',
                        'drive_type', 'interval', 'duration_ms', 'offset_ms',
                        'jitter_reason', 'details'
                    ]
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    
                    for entry in self.current_entries:
                        # Convert timestamp to string for CSV
                        csv_entry = entry.copy()
                        csv_entry['timestamp'] = entry['timestamp'].strftime('%Y-%m-%d %H:%M:%S.%f')
                        writer.writerow(csv_entry)
                
                QMessageBox.information(self, "Export", f"Log data exported to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export data: {e}")
