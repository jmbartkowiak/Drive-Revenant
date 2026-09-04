# app_gui_status_thread.py
# Version: 1.1.0
# Status update thread for Drive Revenant GUI.
#
# Emits snapshots only when the scheduler state actually changed or once per
# second for countdown ticking, so the table is not rebuilt on every poll.

import time
import logging
from typing import Optional

from PySide6.QtCore import QThread, Signal

from app_core import CoreEngine


class StatusUpdateThread(QThread):
    """Thread for updating GUI status from core engine."""

    status_updated = Signal(dict)

    # Minimum cadence for emitting a snapshot so the countdown column keeps
    # ticking without a full repaint on every (possibly 100ms) poll.
    MIN_COUNTDOWN_TICK_S = 1.0

    def __init__(self, core_engine: CoreEngine, drive_table=None, config=None):
        super().__init__()
        self.core_engine = core_engine
        self.drive_table = drive_table  # Reference to table for edit detection
        self.config = config
        self.running = True
        self.last_update = 0
        # Use configurable intervals, fallback to defaults if config not available
        self.fast_update_interval = config.gui_update_interval_ms if config else 500
        self.slow_update_interval = config.gui_update_interval_editing_ms if config else 1000

    def run(self):
        """Update status with adaptive timing based on editing state."""
        logger = logging.getLogger(__name__)
        last_version = None
        last_tick = 0.0

        # Emit an initial full snapshot to populate UI immediately
        try:
            if self.core_engine:
                initial = self.core_engine.get_full_status_snapshot()
                last_version = initial.get('snapshot_version')
                logger.debug(f"StatusUpdateThread: Emitting initial snapshot with {len(initial.get('drives', {}))} drives")
                self.status_updated.emit(initial)
        except Exception:
            pass

        while self.running:
            if self.core_engine:
                # Get status snapshot (use full snapshot to ensure intervals are included)
                try:
                    status = self.core_engine.get_full_status_snapshot()

                    # Emit only when the state changed or at least once per second so
                    # the countdown column keeps ticking without a repaint storm.
                    now = time.monotonic()
                    version = status.get('snapshot_version') if status else None
                    if status and (version != last_version or (now - last_tick) >= self.MIN_COUNTDOWN_TICK_S):
                        last_version = version
                        last_tick = now
                        logger.debug(f"StatusUpdateThread: Emitting snapshot with {len(status.get('drives', {}))} drives")
                        self.status_updated.emit(status)
                except Exception as e:
                    # Never let a transient snapshot error kill the update thread;
                    # otherwise the GUI table silently stops refreshing.
                    logger.warning(f"StatusUpdateThread: snapshot failed: {e}")

            # Adaptive timing: slow down updates while a cell is being edited.
            # Read-only check so the background thread never mutates the widget.
            has_active_editing = bool(self.drive_table._editing_cells) if self.drive_table else False

            if has_active_editing:
                # Someone is editing - use slower updates
                interval = self.slow_update_interval
            else:
                # No editing activity - use fast updates for responsiveness
                interval = self.fast_update_interval

            self.msleep(interval)

    def stop(self):
        """Stop the status update thread."""
        self.running = False
        # Bounded wait so a shutdown can't hang on a slow WMI/status query.
        self.wait(5000)
