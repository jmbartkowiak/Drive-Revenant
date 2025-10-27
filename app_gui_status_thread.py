# app_gui_status_thread.py
# Version: 1.0.5
# Status update thread for Drive Revenant GUI

import time
import logging
from typing import Optional

from PySide6.QtCore import QThread, Signal

from app_core import CoreEngine

class StatusUpdateThread(QThread):
    """Thread for updating GUI status from core engine."""

    status_updated = Signal(dict)

    def __init__(self, core_engine: CoreEngine, drive_table=None, config=None):
        super().__init__()
        self.core_engine = core_engine
        self.drive_table = drive_table  # Reference to table for edit detection
        self.config = config
        self.running = True
        self.last_update = 0
        # Use configurable intervals, fallback to defaults if config not available
        self.fast_update_interval = config.gui_update_interval_ms if config else 250
        self.slow_update_interval = config.gui_update_interval_editing_ms if config else 1000

    def run(self):
        """Update status with adaptive timing based on editing state."""
        logger = logging.getLogger(__name__)
        # Emit an initial full snapshot to populate UI immediately
        try:
            if self.core_engine:
                initial = self.core_engine.get_full_status_snapshot()
                logger.debug(f"StatusUpdateThread: Emitting initial snapshot with {len(initial.get('drives', {}))} drives")
                self.status_updated.emit(initial)
        except Exception:
            pass

        while self.running:
            if self.core_engine:
                # Get status snapshot (use full snapshot to ensure intervals are included)
                status = self.core_engine.get_full_status_snapshot()
                
                # Always emit status (includes upcoming_operations which change frequently)
                if status:
                    logger.debug(f"StatusUpdateThread: Emitting snapshot with {len(status.get('drives', {}))} drives")
                    self.status_updated.emit(status)

            # Adaptive timing: slow down updates when editing is active or recent
            current_time = time.monotonic()
            has_active_editing = False

            if self.drive_table:
                # Check current editing
                has_active_editing = bool(self.drive_table._editing_cells)

                # Also check recently edited (for extended protection)
                if not has_active_editing:
                    self.drive_table._cleanup_recently_edited()
                    has_active_editing = bool(self.drive_table._recently_edited)

            if has_active_editing:
                # Someone is editing or recently edited - use slower updates
                interval = self.slow_update_interval
            else:
                # No editing activity - use fast updates for responsiveness
                interval = self.fast_update_interval

            self.msleep(interval)
    
    def stop(self):
        """Stop the status update thread."""
        self.running = False
        self.wait()
