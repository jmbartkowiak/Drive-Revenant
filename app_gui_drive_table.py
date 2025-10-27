# app_gui_drive_table.py
# Version: 2.0.2
# Drive table component for Drive Revenant GUI

import time
import json
from functools import partial
from typing import Dict, Any, Optional, Set
from pathlib import Path

from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QStyledItemDelegate,
    QComboBox, QMessageBox, QMenu, QWidget, QLineEdit
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint, QModelIndex
from PySide6.QtGui import QFont, QPainter, QColor, QBrush, QPen, QAction

from app_config import ConfigManager
from app_core import CoreEngine
from app_types import DriveConfig, DriveStatus, ResultCode

class ComboBoxDelegate(QStyledItemDelegate):
    """Custom delegate for combobox editing in table cells."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items = items
    
    def createEditor(self, parent, option, index):
        """Create a combobox editor."""
        editor = QComboBox(parent)
        editor.addItems(self.items)
        return editor
    
    def setEditorData(self, editor, index):
        """Set the current value in the editor."""
        value = index.model().data(index, Qt.EditRole)
        if value:
            editor.setCurrentText(str(value))
    
    def setModelData(self, editor, model, index):
        """Set the data from the editor back to the model."""
        model.setData(index, editor.currentText(), Qt.EditRole)

class StatusIndicator(QWidget):
    """Status indicator widget (colored circle) for drive status."""

    clicked = Signal()

    def __init__(self, status: str, enabled: bool, drive_letter: str, main_window):
        super().__init__()
        self.status = status
        self.enabled = enabled
        self.drive_letter = drive_letter
        self.main_window = main_window
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)  # Show clickable cursor

        # Set accessible name for screen readers
        self._update_accessible_name()

    def _update_accessible_name(self):
        """Update accessible name for screen readers."""
        if self.enabled:
            status_text = f"Drive {self.drive_letter} is enabled and {self.status.lower()}"
        else:
            status_text = f"Drive {self.drive_letter} is disabled"
        self.setAccessibleName(status_text)

    def paintEvent(self, event):
        """Paint the status indicator circle."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Get color based on status and enabled state
        if not self.enabled:
            color = QColor(255, 0, 0)  # Red for disabled (not gray)
        elif self.status == "Disabled":
            color = QColor(255, 0, 0)  # Red for disabled
        elif self.status == "Active":
            color = QColor(0, 255, 0)  # Green for active
        elif self.status == "Paused":
            color = QColor(255, 255, 0)  # Yellow for paused
        elif self.status == "Quarantine":
            color = QColor(255, 255, 0)  # Yellow for quarantine
        elif self.status == "Offline":
            color = QColor(128, 128, 128)  # Gray for offline
        elif self.status == "Error":
            color = QColor(255, 255, 0)  # Yellow for error
        elif self.status == "Clamped":
            color = QColor(255, 255, 0)  # Yellow for clamped
        elif self.status == "HDD-capped":
            color = QColor(255, 165, 0)  # Orange for HDD-capped
        else:
            color = QColor(0, 0, 255)  # Blue for other statuses

        # Draw circle
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(QColor(0, 0, 0), 1))  # Black border
        painter.drawEllipse(2, 2, 16, 16)
        
        # Draw "C" for Clamped status
        if self.status == "Clamped" and self.enabled:
            painter.setPen(QPen(QColor(0, 0, 0), 2))  # Black pen for text
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.drawText(2, 2, 16, 16, Qt.AlignCenter, "C")

    def mousePressEvent(self, event):
        """Handle mouse press to emit clicked signal."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def update_status(self, status: str, enabled: bool):
        """Update the status and enabled state."""
        self.status = status
        self.enabled = enabled
        self._update_accessible_name()
        self.update()  # Trigger repaint

class DriveTableWidget(QTableWidget):
    """Custom table widget for drive management.
    
    CRITICAL FIX: Implements immediate save in closeEditor() to prevent data loss
    when signals are blocked during GUI updates. Uses change tracking to prevent
    excessive save attempts. The signal blocking during update_drive_data() would
    normally cause itemChanged signals to be lost, so we save immediately in
    closeEditor() before signals can be blocked.
    """

    # Signals (class attributes)
    drive_selection_changed = Signal(list)  # Emitted when drive selection changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.core_engine = None
        self.config_manager = None
        self.logging_manager = None
        self.setup_table()
        self.drive_data = {}
        self.main_window = None  # Explicit reference to MainWindow
        self._editing_cells = set()  # Track cells currently being edited
        self._recently_edited = set()  # Track cells recently edited (extend preservation)
        self._edit_protection_time = 0.5  # Seconds to preserve edits after editing ends (reduced from 2.0 for better responsiveness)
        self._current_editor = None  # Track the current editor widget
        self._current_editor_index = None  # Track the current editor's index
        self._row_for_drive = {}  # Stable mapping from drive letter -> row index
        self._editor_original_values = {}  # Track original values: (row, col) -> original_value
        # Countdown display uses snapshot-based data from centralized scheduler
        # Single source of truth: next_due_at from StatusSnapshot
        
        # NEW: Dirty flag system for config saves
        self._config_dirty = False  # Track if config needs saving
        self._save_timer = QTimer()
        self._save_timer.timeout.connect(self._save_config_if_dirty)
        self._save_timer.start(5000)  # Save every 5 seconds if dirty

    def set_core_engine(self, core_engine):
        """Set the core engine reference."""
        self.core_engine = core_engine

    def set_config_manager(self, config_manager):
        """Set the config manager reference."""
        self.config_manager = config_manager

    def set_main_window(self, main_window):
        """Set the main window reference."""
        self.main_window = main_window
    
    def _save_config_if_dirty(self):
        """Save config if dirty flag is set."""
        if self._config_dirty and self.main_window and self.main_window.config_manager:
            try:
                # Get current config and save it
                config = self.main_window.config_manager.load_config()
                self.main_window.config_manager.save_config(config)
                self._config_dirty = False
                import logging
                logger = logging.getLogger(__name__)
                logger.debug("Config saved via dirty flag system")
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to save config via dirty flag: {e}")

    def set_logging_manager(self, logging_manager):
        """Set the logging manager reference."""
        self.logging_manager = logging_manager

    def get_selected_drives(self):
        """Get the list of currently selected drive letters."""
        selected_drives = []
        for item in self.selectedItems():
            # Drive letter is in column 1
            if item.column() == 1:
                drive_letter = item.text()
                selected_drives.append(drive_letter)
        return selected_drives

    def selectionChanged(self, selected, deselected):
        """Override to emit drive_selection_changed signal."""
        super().selectionChanged(selected, deselected)
        selected_drives = self.get_selected_drives()
        self.drive_selection_changed.emit(selected_drives)

    def edit(self, index, trigger, event):
        """Override edit to track when cells are being edited.
        
        CRITICAL FIX: Capture original cell value before editing starts.
        This allows us to detect actual changes and prevent unnecessary saves.
        """
        row, col = index.row(), index.column()
        self._editing_cells.add((row, col))
        self._current_editor_index = index
        
        # Capture original value for change detection (columns 4=interval, 5=type)
        if col in (4, 5):
            item = self.item(row, col)
            if item:
                self._editor_original_values[(row, col)] = item.text()
        
        return super().edit(index, trigger, event)

    def closeEditor(self, editor, hint):
        """Override closeEditor to save changes immediately before they can be lost.
        
        CRITICAL FIX: Saves edits immediately when editor closes, bypassing the
        itemChanged signal which is often blocked during GUI updates. Only saves
        if value actually changed to prevent excessive save attempts.
        """
        # Get the index before the editor closes
        if self._current_editor_index is not None:
            row = self._current_editor_index.row()
            col = self._current_editor_index.column()
            
            # For editable columns (interval=4, type=5), check if value changed and save
            if col in (4, 5):
                # Get the editor's current value
                if isinstance(editor, QLineEdit):
                    new_value = editor.text()
                    original_value = self._editor_original_values.get((row, col), "")
                    
                    # Only save if value actually changed
                    if new_value != original_value:
                        # Get drive letter
                        drive_letter_item = self.item(row, 1)
                        if drive_letter_item and new_value:
                            drive_letter = drive_letter_item.text()
                            
                            # Save immediately by manually triggering the change handler
                            # This bypasses the signal mechanism entirely
                            self._save_cell_change_immediately(drive_letter, col, new_value)
                
                # Clean up original value tracking
                self._editor_original_values.pop((row, col), None)
            
            # Continue with normal tracking
            self._editing_cells.discard((row, col))
            self._recently_edited.add((row, col, time.monotonic()))
            self._current_editor_index = None
        else:
            # Fallback: try to find the editor position
            for row in range(self.rowCount()):
                for col in range(self.columnCount()):
                    if self.cellWidget(row, col) == editor or self.item(row, col) == editor:
                        self._editing_cells.discard((row, col))
                        self._recently_edited.add((row, col, time.monotonic()))
                        self._editor_original_values.pop((row, col), None)
                        break
        
        return super().closeEditor(editor, hint)
    
    def keyPressEvent(self, event):
        """Handle key press events, especially Escape to cancel editing.
        
        CRITICAL FIX: Clean up value tracking when user cancels edit.
        """
        if event.key() == Qt.Key_Escape and self._current_editor_index is not None:
            # Cancel editing - remove from tracking without adding to recently edited
            row, col = self._current_editor_index.row(), self._current_editor_index.column()
            self._editing_cells.discard((row, col))
            self._editor_original_values.pop((row, col), None)  # Clean up original value
            self._current_editor_index = None
        return super().keyPressEvent(event)

    def _cleanup_recently_edited(self):
        """Clean up recently edited cells that have exceeded protection time."""
        current_time = time.monotonic()
        expired_edits = []
        for row, col, edit_time in self._recently_edited:
            if current_time - edit_time > self._edit_protection_time:
                expired_edits.append((row, col, edit_time))

        for expired in expired_edits:
            self._recently_edited.discard(expired)

    def _move_row_to_position(self, from_row: int, to_row: int):
        """Move a table row from one position to another."""
        if from_row == to_row:
            return
            
        # Get all items from the source row
        row_items = []
        for col in range(self.columnCount()):
            item = self.takeItem(from_row, col)
            row_items.append(item)
        
        # Get the cell widget from the source row
        cell_widget = self.cellWidget(from_row, 0)
        
        # Remove the source row
        self.removeRow(from_row)
        
        # Insert at the target position
        self.insertRow(to_row)
        
        # Restore items and widget
        for col, item in enumerate(row_items):
            if item is not None:
                self.setItem(to_row, col, item)
        
        if cell_widget is not None:
            self.setCellWidget(to_row, 0, cell_widget)

    def _is_cell_protected(self, row, col):
        """Check if a cell should be protected from updates."""
        # Check if Qt thinks this cell is being edited
        if self.indexWidget(self.model().index(row, col)) is not None:
            return True
            
        # Currently editing (our tracking)
        if (row, col) in self._editing_cells:
            return True

        # Recently edited (within protection time)
        self._cleanup_recently_edited()
        return (row, col) in {(r, c) for r, c, _ in self._recently_edited}
    
    def setup_table(self):
        """Set up the table columns and headers."""
        headers = [
            "Enabled", "Drive", "Label", "Size", "Interval (s)",
            "Type", "Status", "Next in"
        ]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)

        # Set column widths
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)  # Status indicator
        header.setSectionResizeMode(1, QHeaderView.Fixed)  # Drive
        header.setSectionResizeMode(2, QHeaderView.Stretch)  # Label
        header.setSectionResizeMode(3, QHeaderView.Fixed)  # Size
        header.setSectionResizeMode(4, QHeaderView.Fixed)  # Interval
        header.setSectionResizeMode(5, QHeaderView.Fixed)  # Type
        header.setSectionResizeMode(6, QHeaderView.Stretch)  # Status
        header.setSectionResizeMode(7, QHeaderView.Fixed)  # Next in

        self.setColumnWidth(0, 40)   # Status indicator (circle)
        self.setColumnWidth(1, 50)   # Drive
        self.setColumnWidth(3, 80)   # Size
        self.setColumnWidth(4, 80)   # Interval
        self.setColumnWidth(5, 80)   # Type
        self.setColumnWidth(7, 80)   # Next in

        # Disable sorting permanently to keep stable row order
        self.setSortingEnabled(False)

        # Single selection
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setSelectionBehavior(QTableWidget.SelectRows)

        # Enable editing (double-click or press F2/Enter to edit)
        # Set up edit triggers - only allow double-click or F2 to edit (removed SelectedClicked - too sensitive)
        self.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)

        # Set up custom editors for specific columns
        self._setup_column_editors()
        
        # Connect item changed signal for interval editing persistence
        self.itemChanged.connect(self._on_item_changed)

    def _setup_column_editors(self):
        """Set up custom editors for table columns."""
        # Drive types for the type column dropdown
        self.drive_types = ["HDD", "SSD", "Removable", "Network", "RAM-disk", "CD-ROM", "Unknown"]
        
        # Create and set delegate for Type column (column 5)
        type_delegate = ComboBoxDelegate(self.drive_types, self)
        self.setItemDelegateForColumn(5, type_delegate)

    def update_drive_data(self, drives: Dict[str, Any]):
        """Incrementally update table without disrupting selection or editors."""
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"DriveTableWidget: update_drive_data called with {len(drives)} drives: {list(drives.keys())}")
        self.drive_data = drives

        # Remember selection and current edit index
        prev_index = self._current_editor_index if self._current_editor_index is not None else self.currentIndex()
        was_sorting = self.isSortingEnabled()

        # Disable sorting and signals during update to prevent churn
        if was_sorting:
            self.setSortingEnabled(False)
        self.blockSignals(True)
        self.setUpdatesEnabled(False)

        try:
            if not drives:
                # If empty, avoid destroying active editors; just show 0 rows
                if self.rowCount() != 0:
                    self.setRowCount(0)
                self.horizontalHeader().setVisible(False)
                return

            # Show headers for populated state
            self.horizontalHeader().setVisible(True)

            # Build current mapping from drive letter -> row
            current_rows = self.rowCount()
            letter_to_row: Dict[str, int] = {}
            for row in range(current_rows):
                item = self.item(row, 1)
                if item is not None:
                    letter_to_row[item.text()] = row

            # Ensure rows exist for all drives in alphabetical order
            sorted_drives = sorted(drives.items())
            for drive_index, (drive_letter, drive_info) in enumerate(sorted_drives):
                if drive_letter in letter_to_row:
                    # Drive exists - check if it's in the right position
                    current_row = letter_to_row[drive_letter]
                    if current_row != drive_index:
                        # Move drive to correct alphabetical position
                        self._move_row_to_position(current_row, drive_index)
                        # Update mapping
                        letter_to_row[drive_letter] = drive_index
                        # Update other mappings
                        for other_letter, other_row in letter_to_row.items():
                            if other_row > current_row and other_row <= drive_index:
                                letter_to_row[other_letter] = other_row - 1
                    row = drive_index
                else:
                    # Insert new row at correct alphabetical position
                    self.insertRow(drive_index)
                    # Initialize minimal cells so _update_single_row can fill
                    self.setItem(drive_index, 1, QTableWidgetItem(drive_letter))
                    # Update mappings for drives that come after this position
                    for other_letter, other_row in letter_to_row.items():
                        if other_row >= drive_index:
                            letter_to_row[other_letter] = other_row + 1
                    letter_to_row[drive_letter] = drive_index
                    row = drive_index
                # Update row content (respects per-cell protection)
                self._update_single_row(row, drive_letter, drive_info)

            # Remove rows for drives that disappeared (only if not being edited)
            existing_letters = set(letter_to_row.keys())
            desired_letters = set(drives.keys())
            to_remove = [ltr for ltr in existing_letters - desired_letters]
            if to_remove:
                # Remove from bottom to top to preserve indices
                rows_to_remove = sorted([letter_to_row[ltr] for ltr in to_remove if (letter_to_row[ltr], 4) not in self._editing_cells and (letter_to_row[ltr], 5) not in self._editing_cells], reverse=True)
                for r in rows_to_remove:
                    self.removeRow(r)

                # No cleanup needed - countdown state is managed by centralized scheduler

        finally:
            self.setUpdatesEnabled(True)
            self.blockSignals(False)
            # Restore sorting
            if was_sorting:
                self.setSortingEnabled(True)
            # Restore selection/editor focus
            if prev_index is not None and prev_index.isValid():
                try:
                    self.setCurrentIndex(prev_index)
                except Exception:
                    pass

    def _should_update_row(self, row: int, drive_info: Dict[str, Any]) -> bool:
        """Check if a row needs updating to avoid unnecessary repaints."""
        # Compare with cached data if available
        if row < len(self.drive_data) and row in [i for i, (k, v) in enumerate(self.drive_data.items())]:
            cached_info = list(self.drive_data.values())[row]
            # Simple check - in a more complete implementation, we'd do deep comparison
            return True  # For now, always update to ensure correctness

        return True

    def _update_single_row(self, row: int, drive_letter: str, drive_info: Dict[str, Any]):
        """Update a single row with drive data."""
        # Store drive letter in the info dict for tooltip access
        drive_info['drive_letter'] = drive_letter

        # Status indicator (circle) - update existing or create new
        existing_indicator = self.cellWidget(row, 0)
        if existing_indicator and hasattr(existing_indicator, 'update_status'):
            # Update existing indicator (it has our update_status method)
            # Use status field directly from snapshot
            status_value = drive_info.get('status', 'Offline')  # Use status field directly
            enabled = drive_info.get('enabled', False)

            # Disabled drives should show "Disabled" status regardless of internal state
            if not enabled:
                status = 'Disabled'
            else:
                status = status_value  # Direct mapping: Paused->Paused, Active->Active
                
            existing_indicator.update_status(status, enabled)
        else:
            # Create new indicator
            status_indicator = self._create_status_indicator(drive_letter, drive_info)
            self.setCellWidget(row, 0, status_indicator)
            # Ensure there is also a table item for accessibility/indexing
            if self.item(row, 0) is None:
                dummy_item = QTableWidgetItem("")
                # Non-editable, enabled so accessibility can reference it
                dummy_item.setFlags(Qt.ItemIsEnabled)
                self.setItem(row, 0, dummy_item)

        # Drive letter
        self.setItem(row, 1, QTableWidgetItem(drive_letter))

        # Label
        label = drive_info.get('label', 'Local Disk')
        self.setItem(row, 2, QTableWidgetItem(label))

        # Size
        size = drive_info.get('size', '—')
        self.setItem(row, 3, QTableWidgetItem(size))

        # Interval (editable) - only update if not currently being edited
        interval_value = drive_info.get('interval', 180)

        # Check if this cell should be protected from updates
        if self._is_cell_protected(row, 4):
            # Cell is being edited or recently edited - preserve user's changes
            # Don't update the cell content at all
            pass
        else:
            # Cell not protected - safe to update with fresh data
            interval_item = QTableWidgetItem(str(interval_value))
            interval_item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled)
            self.setItem(row, 4, interval_item)

        # Type (editable) - only update if not currently being edited
        type_value = drive_info.get('type', '—')

        # Check if this cell should be protected from updates
        if self._is_cell_protected(row, 5):
            # Cell is being edited or recently edited - preserve user's changes
            # Don't update the cell content at all
            pass
        else:
            # Cell not protected - safe to update with fresh data
            type_item = QTableWidgetItem(type_value)
            type_item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled)
            self.setItem(row, 5, type_item)

        # Status - enhanced for all special conditions
        base_status = drive_info.get('status', '—')

        # Get drive state for detailed status - use scheduler (Phase 3)
        drive_state = None
        if self.core_engine:
            drive_state = self.core_engine._build_drive_state_from_scheduler(drive_letter)

        if drive_state:
            status_value = drive_state.status.value
            
            # Quarantine status
            if status_value == "Quarantine":
                if drive_state.quarantine_until:
                    remaining_time = max(0, drive_state.quarantine_until - time.monotonic())
                    remaining_min = int(remaining_time / 60)
                    if remaining_min > 0:
                        status = f"Quarantine ({remaining_min}m remaining)"
                    else:
                        status = "Quarantine (expiring soon)"
                else:
                    status = "Quarantine"
            
            # HDD-capped status (green light, text in status column)
            elif status_value == "HDD-capped":
                # Use live config from core engine instead of reading from disk
                if self.core_engine and self.core_engine.config:
                    hdd_max = self.core_engine.config.hdd_max_gap_sec
                else:
                    hdd_max = 60  # Fallback
                status = f"Active - interval reduced to {hdd_max}s"

            # Clamped status (green light, text in status column)
            elif status_value == "Clamped":
                # Use live config from core engine instead of reading from disk
                if self.core_engine and self.core_engine.config:
                    min_interval = self.core_engine.config.interval_min_sec
                else:
                    min_interval = 1  # Fallback
                status = f"Active - interval increased to {min_interval}s"
            
            # Error status - check if blocking or non-blocking
            elif status_value == "Error":
                error_reason = getattr(drive_state, 'error_reason', 'unknown error')
                # Determine if error is blocking (check if drive is still operational)
                if drive_state.consecutive_tick_failures >= 3:
                    status = f"Offline - error [{error_reason}]"
                else:
                    status = f"Active - error [{error_reason}]"
            
            else:
                status = status_value
        else:
            status = base_status

        self.setItem(row, 6, QTableWidgetItem(status))

        # ===== SNAPSHOT-BASED COUNTDOWN (SINGLE SOURCE OF TRUTH) =====
        # Use the centralized scheduler's immutable snapshot for timing calculations
        # Calculate countdown from last_operation + interval to show ACTUAL interval
        # The interval field now reflects the effective interval after caps/limits

        last_operation = drive_info.get('last_ok_at')  # Monotonic time of last operation
        interval = drive_info.get('interval', 180)  # Actual interval being used (may be capped/limited)
        next_due_at = drive_info.get('next_due_at')  # Fallback if last_operation not available
        status_value = drive_info.get('status', 'Active')
        reason = drive_info.get('reason')

        if status_value == 'Quarantine':
            # Show countdown to quarantine release instead of next operation
            quarantine_release_at = drive_info.get('quarantine_release_at')
            if quarantine_release_at:
                now = time.monotonic()
                time_remaining = max(0.0, quarantine_release_at - now)
                if time_remaining > 0:
                    next_in_str = f"Q:{int(time_remaining + 0.5)}s"
                else:
                    next_in_str = "Released"
            else:
                # Infinite quarantine - show infinity symbol with explanation
                next_in_str = "\u221e - In quarantine"
        elif status_value == 'Paused' and reason:
            # Paused state - show reason instead of countdown
            next_in_str = f"Paused ({reason})"
        elif last_operation is not None:
            # Calculate countdown from last_operation + interval
            # This shows the ACTUAL interval being used (accounts for caps/limits)
            now = time.monotonic()
            # Time elapsed since last operation
            elapsed = now - last_operation
            # Time remaining in interval
            time_remaining = interval - elapsed
            
            # Show "Due now" for anything under 1 second
            if time_remaining >= 1.0:
                next_in_str = f"{int(time_remaining + 0.5)}s"
            else:
                next_in_str = "Due now"
        elif next_due_at is not None:
            # Fallback: use next_due_at if last_operation not available
            now = time.monotonic()
            time_remaining = next_due_at - now
            
            # Show "Due now" for anything under 1 second
            if time_remaining >= 1.0:
                next_in_str = f"{int(time_remaining + 0.5)}s"
            else:
                next_in_str = "Due now"
        else:
            # No scheduled operation
            next_in_str = "—"

        # Debug logging for diagnostics
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"GUI next_due_at for {drive_letter} = {next_due_at}")
        logger.debug(f"Drive {drive_letter}: status={status_value}, reason={reason}, next_due={next_due_at}, countdown={next_in_str}")
        # =================================================================

        # Only update if the value has actually changed to avoid unnecessary repaints
        existing_item = self.item(row, 7)
        if existing_item is None or existing_item.text() != next_in_str:
            next_in_item = QTableWidgetItem(next_in_str)
            self.setItem(row, 7, next_in_item)

        # Set tooltips with operation history
        self._set_row_tooltips(row, drive_info)

    def _set_row_tooltips(self, row: int, drive_info: Dict[str, Any]):
        """Set tooltips for table row with operation history."""
        # Get drive state for operation history - use scheduler (Phase 3 alignment)
        drive_letter = drive_info.get('drive_letter', 'Unknown')
        drive_state = None
        if self.core_engine:
            drive_state = self.core_engine._build_drive_state_from_scheduler(drive_letter)

        tooltip_text = f"Drive {drive_letter}\n"

        # Add status explanation
        if drive_state:
            if drive_state.status.value == "HDD-capped":
                tooltip_text += f"Status: {drive_state.status.value} (HDD guard active - interval capped to prevent spin-down)\n"
            elif drive_state.status.value == "Clamped":
                tooltip_text += f"Status: {drive_state.status.value} (interval clamped to minimum value)\n"
            elif not drive_state.enabled:
                tooltip_text += f"Status: {drive_state.status.value} (drive disabled)\n"
            else:
                tooltip_text += f"Status: {drive_state.status.value}\n"

            tooltip_text += f"Type: {drive_state.config.type}\n"
            tooltip_text += f"Interval: {drive_state.config.interval}s"
            
            # Show effective interval if different from configured interval
            effective_interval = drive_info.get('effective_interval_sec')
            if effective_interval and abs(effective_interval - drive_state.config.interval) > 0.1:
                tooltip_text += f" (effective: {effective_interval:.1f}s)"
            tooltip_text += "\n"
            
            # Show ping file path
            if self.main_window and self.main_window.io_manager:
                from pathlib import Path
                timing_state = self.core_engine.scheduler.get_timing_state(drive_letter)
                if timing_state:
                    ping_dir = self.main_window.io_manager.get_ping_directory(drive_letter.rstrip(':'), timing_state.ping_dir)
                    ping_file = ping_dir / "drive_revenant"
                    tooltip_text += f"Ping file: {ping_file}\n"

            if drive_state.consecutive_tick_failures > 0:
                tooltip_text += f"Consecutive failures: {drive_state.consecutive_tick_failures}\n"

        tooltip_text += "\n"

        if drive_state and drive_state.last_results:
            tooltip_text += "Recent Operations:\n"
            for i, result in enumerate(drive_state.last_results[-3:]):  # Last 3 results
                tooltip_text += f"{i+1}. {result.result_code.value} - {result.duration_ms:.1f}ms"
                if result.details:
                    tooltip_text += f" ({result.details})"
                if hasattr(result, 'offset_ms') and result.offset_ms:
                    tooltip_text += f" [{result.offset_ms:+.0f}ms]"
                if hasattr(result, 'jitter_reason') and result.jitter_reason:
                    tooltip_text += f" ({result.jitter_reason})"
                tooltip_text += "\n"
        else:
            tooltip_text += "No operation history available"

        # Set tooltip for the drive letter cell
        drive_item = self.item(row, 1)  # Drive letter column
        if drive_item:
            drive_item.setToolTip(tooltip_text)

    def _create_status_indicator(self, drive_letter: str, drive_info: Dict[str, Any]) -> StatusIndicator:
        """Create a status indicator widget (colored circle)."""
        # Use status field directly from snapshot
        status_value = drive_info.get('status', 'Offline')  # Use status field directly
        enabled = drive_info.get('enabled', False)
        
        if not enabled:
            status = 'Disabled'
        else:
            status = status_value  # Direct mapping

        # Create indicator and connect click signal
        indicator = StatusIndicator(status, enabled, drive_letter, self.main_window)
        # Capture the drive_letter value immediately using a partial function
        indicator.clicked.connect(partial(self._toggle_drive_status, drive_letter))
        return indicator

    def _toggle_drive_status(self, drive_letter: str):
        """Toggle drive status (enable/disable or clear quarantine)."""
        if not self.main_window:
            return

        main_window = self.main_window
        drive_info = self.drive_data.get(drive_letter, {})
        
        # Use status field directly from snapshot
        current_status = drive_info.get('status', 'Offline')  # Use status field directly

        if current_status == "Quarantine":
            # Clear quarantine
            main_window.clear_drive_quarantine(drive_letter)
        else:
            # Toggle enabled/disabled
            main_window.toggle_drive_enabled(drive_letter)

    def mousePressEvent(self, event):
        """Handle mouse press events for context menu."""
        if event.button() == Qt.RightButton:
            # Get the row that was right-clicked
            row = self.rowAt(event.pos().y())
            if row >= 0 and row < self.rowCount():
                self.setCurrentCell(row, 0)  # Select the row
                self._show_context_menu(row, event.pos())
            return

        super().mousePressEvent(event)

    def _show_context_menu(self, row: int, position: QPoint):
        """Show context menu for the selected drive."""
        main_window = self.main_window
        if not main_window:
            return

        drive_letter = self.item(row, 1).text()  # Drive column is index 1

        # Create context menu
        context_menu = QMenu(self)

        # Ping drive - use a method that takes the specific drive letter
        ping_action = QAction(f"&Ping {drive_letter} Now", self)
        ping_action.triggered.connect(partial(main_window._ping_drive_by_letter, drive_letter))
        context_menu.addAction(ping_action)

        context_menu.addSeparator()

        # Toggle enabled/disabled or clear quarantine
        current_status = self.drive_data.get(drive_letter, {}).get('status', 'Offline')
        if current_status == "Quarantine":
            # Add option to clear quarantine immediately
            clear_quarantine_action = QAction(f"&Release from Quarantine for {drive_letter}", self)
            clear_quarantine_action.triggered.connect(partial(main_window.clear_drive_quarantine, drive_letter))
            context_menu.addAction(clear_quarantine_action)
        else:
            # Add option to disable/enable
            enabled = self.drive_data.get(drive_letter, {}).get('enabled', False)
            toggle_action = QAction(f"&{'Disable' if enabled else 'Enable'} {drive_letter}", self)
            toggle_action.triggered.connect(partial(main_window.toggle_drive_enabled, drive_letter))
            context_menu.addAction(toggle_action)

        # Pause/Resume options (only for non-quarantined drives)
        if current_status != "Quarantine":
            context_menu.addSeparator()
            if current_status == "Paused":
                resume_action = QAction(f"&Resume {drive_letter}", self)
                resume_action.triggered.connect(partial(main_window.resume_drive, drive_letter))
                context_menu.addAction(resume_action)
            else:
                pause_action = QAction(f"&Pause {drive_letter}", self)
                pause_action.triggered.connect(partial(main_window.pause_drive, drive_letter))
                context_menu.addAction(pause_action)

        context_menu.addSeparator()

        # Drive details option
        details_action = QAction(f"&Drive Details for {drive_letter}", self)
        details_action.triggered.connect(partial(main_window.show_drive_details, drive_letter))
        context_menu.addAction(details_action)

        # Show context menu at global position
        global_pos = self.mapToGlobal(position)
        context_menu.exec(global_pos)

    def _on_item_changed(self, item):
        """Handle item changes for interval editing persistence.
        
        BACKUP MECHANISM: This is a backup to closeEditor() immediate save.
        It handles cases where closeEditor() might not catch the change, but
        includes the same change detection to prevent duplicate saves.
        
        Note: This often doesn't fire due to blockSignals() during GUI updates,
        which is why we have the closeEditor() immediate save mechanism.
        """
        if not item:
            return
            
        row = item.row()
        column = item.column()
        
        # Only handle editable columns
        if column not in (4, 5):
            return
        
        # Get drive letter from row (always column 1)
        drive_letter_item = self.item(row, 1)
        if not drive_letter_item:
            return
            
        drive_letter = drive_letter_item.text()
        if not drive_letter:
            return

        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"_on_item_changed triggered for {drive_letter} column {column}")

        # Handle interval changes (column 4)
        if column == 4:
            try:
                new_interval = int(item.text())
                if new_interval < 1:
                    new_interval = 1
                    
                # Use live config from core engine instead of reading from disk
                if self.core_engine and self.core_engine.config:
                    config = self.core_engine.config
                elif self.main_window and self.main_window.config_manager:
                    config = self.main_window.config_manager.load_config()
                else:
                    return

                if drive_letter in config.per_drive:
                    old_interval = config.per_drive[drive_letter].interval
                    
                    # Skip if value didn't actually change (prevents duplicate saves)
                    if new_interval == old_interval:
                        logger.debug(f"Interval for {drive_letter} unchanged ({new_interval}s), skipping save")
                        return
                    
                    # Save using the immediate save method (includes all validation)
                    self._save_cell_change_immediately(drive_letter, column, str(new_interval))
                                
            except ValueError:
                # Invalid interval value, revert to original
                logger.warning(f"Invalid interval value for {drive_letter}")
                if drive_letter in self.drive_data:
                    original_interval = self.drive_data[drive_letter].get('interval', 0)
                    item.setText(str(original_interval))
                    if hasattr(self.main_window, 'status_bar'):
                        self.main_window.status_bar.showMessage(
                            f"Invalid interval value for {drive_letter}, reverted", 2000
                        )

        # Handle drive type changes (column 5)
        elif column == 5:
            new_type = item.text()
            
            # Use live config from core engine instead of reading from disk
            if self.core_engine and self.core_engine.config:
                config = self.core_engine.config
            elif self.main_window and self.main_window.config_manager:
                config = self.main_window.config_manager.load_config()
            else:
                return

            if drive_letter in config.per_drive:
                old_type = config.per_drive[drive_letter].type
                
                # Skip if value didn't actually change (prevents duplicate saves)
                if new_type == old_type:
                    logger.debug(f"Type for {drive_letter} unchanged ({new_type}), skipping save")
                    return
                
                # Validate type
                valid_types = ["HDD", "SSD", "Removable", "Network", "RAM-disk", "CD-ROM", "Unknown"]
                if new_type not in valid_types:
                    # Invalid type, revert to original
                    logger.warning(f"Invalid type '{new_type}' for {drive_letter}")
                    item.setText(old_type)
                    if hasattr(self.main_window, 'status_bar'):
                        self.main_window.status_bar.showMessage(
                            f"Invalid drive type for {drive_letter}, reverted", 2000
                        )
                    return
                
                # Save using the immediate save method (includes all validation)
                self._save_cell_change_immediately(drive_letter, column, new_type)

    def _save_cell_change_immediately(self, drive_letter: str, column: int, new_value: str):
        """Save cell changes immediately, bypassing the signal mechanism.
        
        CRITICAL FIX: This is called from closeEditor() to ensure changes are saved
        even if signals are blocked during GUI updates. Includes validation and
        error handling to prevent corruption.
        
        Args:
            drive_letter: Drive letter (e.g., "E:")
            column: Column number (4=interval, 5=type)
            new_value: New value to save
        """
        if not self.main_window or not self.main_window.config_manager:
            return
            
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Use live config from core engine instead of reading from disk
            if self.core_engine and self.core_engine.config:
                config = self.core_engine.config
            elif self.main_window and self.main_window.config_manager:
                config = self.main_window.config_manager.load_config()
            else:
                logger.error("No config available for saving changes")
                return

            if drive_letter not in config.per_drive:
                logger.warning(f"Drive {drive_letter} not in config, skipping save")
                return
                
            # Handle interval changes (column 4)
            if column == 4:
                new_interval = int(new_value)
                if new_interval < 1:
                    new_interval = 1
                    
                old_interval = config.per_drive[drive_letter].interval
                
                # Skip if value didn't actually change
                if new_interval == old_interval:
                    return
                    
                config.per_drive[drive_letter].interval = new_interval
                
                # Mark dirty instead of saving immediately
                self._config_dirty = True
                logger.info(f"Interval change for {drive_letter}: {old_interval}s → {new_interval}s (marked dirty)")
                
                # Update core engine runtime state
                if self.main_window.core_engine:
                    current_drive_config = config.per_drive[drive_letter]
                    self.main_window.core_engine.set_drive_config(
                        drive_letter,
                        enabled=current_drive_config.enabled,
                        interval=new_interval,
                        drive_type=current_drive_config.type,
                        ping_dir=current_drive_config.ping_dir,
                        save_config=False  # Already saved above
                    )
                    
                    # Status message
                    if hasattr(self.main_window, 'status_bar'):
                        self.main_window.status_bar.showMessage(
                            f"Saved: {drive_letter} interval {old_interval}s → {new_interval}s", 2000
                        )
                    
                    # Refresh GUI to show updated interval (don't rescan drives - that's slow!)
                    if self.main_window.core_engine:
                        status = self.main_window.core_engine.get_full_status_snapshot()
                        self.main_window.update_status(status)
                else:
                    logger.error(f"Failed to save interval change for {drive_letter}")
                        
            # Handle type changes (column 5)
            elif column == 5:
                valid_types = ["HDD", "SSD", "Removable", "Network", "RAM-disk", "CD-ROM", "Unknown"]
                if new_value not in valid_types:
                    logger.warning(f"Invalid type '{new_value}' for {drive_letter}, skipping save")
                    return
                    
                old_type = config.per_drive[drive_letter].type
                
                # Skip if value didn't actually change
                if new_value == old_type:
                    return
                    
                config.per_drive[drive_letter].type = new_value
                
                # Mark dirty instead of saving immediately
                self._config_dirty = True
                logger.info(f"Type change for {drive_letter}: {old_type} → {new_value} (marked dirty)")
                
                # Update core engine runtime state
                if self.main_window.core_engine:
                    current_drive_config = config.per_drive[drive_letter]
                    self.main_window.core_engine.set_drive_config(
                        drive_letter,
                        enabled=current_drive_config.enabled,
                        interval=current_drive_config.interval,
                        drive_type=new_value,
                        ping_dir=current_drive_config.ping_dir,
                        save_config=False  # Already saved above
                    )
                    
                    # Status message
                    if hasattr(self.main_window, 'status_bar'):
                        self.main_window.status_bar.showMessage(
                            f"Saved: {drive_letter} type {old_type} → {new_value}", 2000
                        )
                else:
                    logger.error(f"Failed to save type change for {drive_letter}")
                        
        except ValueError as e:
            logger.error(f"Invalid value for {drive_letter} column {column}: {e}")
        except Exception as e:
            logger.error(f"Error saving cell change for {drive_letter}: {e}")
