# app_core.py
# Version: 2.0.7
# Core scheduling engine for Drive Revenant with Scheduler as single source of truth.
# All drive state now managed by centralized Scheduler with DriveTimingState.
# Features: deterministic jitter planning, HDD guard logic, policy arbitration, and immutable snapshots.

import time
import threading
import queue
import hashlib
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path

from app_config import AppConfig
from app_types import OperationType, ResultCode, DriveStatus, DriveState, ScheduledOperation, PolicyState, DriveConfig, DriveSnapshot, StatusSnapshot, DriveTimingState
from app_io import IOResult

logger = logging.getLogger(__name__)

# Retry constants for outer retry logic
MAX_OUTER_ATTEMPTS = 3  # Per-tick retry budget
OUTER_RETRY_BACKOFF_MS = [0, 50, 100]  # Backoff delays between attempts
TICK_FAILURES_FOR_QUARANTINE = 3  # Failed ticks before quarantine
# Note: CLI countdown interval is now an instance variable of CoreEngine

class Clock:
    """Clock abstraction for testing and consistent timing."""

    def monotonic(self) -> float:
        """Get monotonic time in seconds."""
        return time.monotonic()

    def wall(self) -> float:
        """Get wall clock time in seconds since epoch."""
        return time.time()

class FakeClock:
    """Fake clock for testing."""

    def __init__(self, start_time: float = 0.0):
        self._time = start_time

    def monotonic(self) -> float:
        return self._time

    def wall(self) -> float:
        return self._time

    def advance(self, delta: float):
        """Advance fake time."""
        self._time += delta

class Scheduler:
    """Centralized scheduler that owns all timing and state mutation."""

    def __init__(self, config: AppConfig, clock: Optional[Clock] = None):
        self.config = config
        self.clock = clock or Clock()
        self._lock = threading.Lock()
        self._version = 0
        self._snapshot: Optional[StatusSnapshot] = None

        # NEW: Own all timing state - single source of truth
        self._drive_timing: Dict[str, DriveTimingState] = {}

        # Global spacing tracking
        self._last_global_read_at = 0.0
        self._last_global_write_at = 0.0

        # Grid settings from config
        self.grid_ms = config.scheduler_grid_ms
        self.min_read_spacing_ms = config.scheduler_min_read_spacing_ms
        self.min_write_spacing_ms = config.scheduler_min_write_spacing_ms

        logger.info(f"Scheduler initialized: grid={self.grid_ms}ms, read_spacing={self.min_read_spacing_ms}ms, write_spacing={self.min_write_spacing_ms}ms")

    def get_timing_state(self, drive_letter: str) -> Optional[DriveTimingState]:
        """Get timing state for a drive."""
        with self._lock:
            return self._drive_timing.get(drive_letter)
    
    def set_drive_config(self, drive_letter: str, enabled: bool, interval_sec: int, 
                         drive_type: str, ping_dir: Optional[str]):
        """Update drive configuration in scheduler."""
        with self._lock:
            timing = self._drive_timing.setdefault(drive_letter, DriveTimingState())
            timing.enabled = enabled
            timing.interval_sec = interval_sec
            timing.type = drive_type
            timing.ping_dir = ping_dir
            self._version += 1

    def set_drive_status(self, drive_letter: str, status: DriveStatus, 
                         pause_reason: Optional[str] = None):
        """Update drive status in scheduler."""
        with self._lock:
            timing = self._drive_timing.setdefault(drive_letter, DriveTimingState())
            timing.status = status
            timing.pause_reason = pause_reason
            self._version += 1

    def record_operation_result(self, drive_letter: str, current_time: float, 
                                io_result, tick_success: bool):
        """Record I/O operation result in scheduler."""
        with self._lock:
            timing = self._drive_timing.get(drive_letter)
            if not timing:
                return
            
            timing.last_operation = current_time
            if io_result:
                timing.last_results.append(io_result)
                if len(timing.last_results) > 10:
                    timing.last_results = timing.last_results[-10:]
            
            if tick_success:
                timing.consecutive_tick_failures = 0
                timing.last_ok_at = current_time
            else:
                timing.consecutive_tick_failures += 1
            
            self._version += 1

    def get_all_drive_states(self) -> Dict[str, DriveTimingState]:
        """Get all drive states (for iteration, planning)."""
        with self._lock:
            return dict(self._drive_timing)

    def get_snapshot(self) -> StatusSnapshot:
        """Get immutable snapshot of current state."""
        with self._lock:
            if self._snapshot is None:
                # Create empty snapshot
                self._snapshot = StatusSnapshot(
                    generated_at=self.clock.monotonic(),
                    version=self._version,
                    drives={}
                )
            return self._snapshot

    def update_drive_state(self, drive_letter: str, state: str, reason: Optional[str] = None,
                          interval_sec: int = 180, effective_interval_sec: float = 180.0,
                          interval_display: float = 180.0, last_ok_at: Optional[float] = None,
                          next_due_at: Optional[float] = None, failure_count: int = 0,
                          quarantine_release_at: Optional[float] = None, type: str = "Unknown",
                          status_reason: Optional[str] = None, consecutive_tick_failures: int = 0,
                          last_tick_attempts: int = 0, tick_counter: int = 0,
                          quarantine_count: Optional[int] = None):
        """Update drive state and publish new snapshot."""
        with self._lock:
            self._version += 1

            # Store timing in _drive_timing - single source of truth
            timing = self._drive_timing.setdefault(drive_letter, DriveTimingState())
            timing.next_due_at = next_due_at
            timing.last_ok_at = last_ok_at
            timing.effective_interval_sec = effective_interval_sec
            timing.status_reason = status_reason
            timing.quarantine_until = quarantine_release_at
            
            # Update status based on state
            if state == "quarantined":
                timing.status = DriveStatus.QUARANTINE
            elif state == "normal":
                timing.status = DriveStatus.ACTIVE
            elif state == "paused":
                timing.status = DriveStatus.PAUSED

            # Create drive snapshot
            drive_snapshot = DriveSnapshot(
                state=state,
                reason=reason,
                interval_sec=interval_sec,
                effective_interval_sec=effective_interval_sec,
                interval_display=interval_display,
                last_ok_at=last_ok_at,
                next_due_at=next_due_at,
                failure_count=failure_count,
                quarantine_release_at=quarantine_release_at,
                type=type,
            consecutive_tick_failures=consecutive_tick_failures,
            last_tick_attempts=last_tick_attempts,
            tick_counter=tick_counter
        )
        
        # Update quarantine count if provided
        if quarantine_count is not None:
            timing.quarantine_count = quarantine_count

            # Update snapshot
            if self._snapshot is None:
                self._snapshot = StatusSnapshot(
                    generated_at=self.clock.monotonic(),
                    version=self._version,
                    drives={}
                )

            # Create new drives dict (immutable)
            new_drives = dict(self._snapshot.drives)
            new_drives[drive_letter] = drive_snapshot

            self._snapshot = StatusSnapshot(
                generated_at=self.clock.monotonic(),
                version=self._version,
                drives=new_drives
            )

    def plan_next_operation(self, drive_letter: str, base_interval_sec: float,
                           last_ok_at: Optional[float] = None) -> float:
        """Plan next operation time with global spacing and deterministic jitter."""
        now = self.clock.monotonic()

        # Compute cycle anchor for deterministic jitter
        cycle_id = int(now // base_interval_sec) if last_ok_at else 0

        # Deterministic jitter using stable seed
        jitter_seed = f"{self.config.install_id}:{drive_letter}:{cycle_id}".encode()
        jitter_hash = hashlib.blake2s(jitter_seed).digest()
        jitter_ms = int.from_bytes(jitter_hash[:4], "little") % (self.config.jitter_sec * 1000)
        jitter_offset = jitter_ms / 1000.0

        # Pre-candidate time
        if last_ok_at:
            candidate = max(last_ok_at + base_interval_sec, now) + jitter_offset
        else:
            candidate = now + jitter_offset

        # Apply global spacing constraints
        candidate = self._apply_global_spacing(candidate, drive_letter)

        # Align to grid
        candidate = self._align_to_grid(candidate)

        return candidate

    def _apply_global_spacing(self, candidate: float, drive_letter: str) -> float:
        """Apply global spacing constraints to candidate time."""
        now = self.clock.monotonic()

        # For now, simple implementation - in full version would check operation type
        # and enforce min spacing between same-type operations globally

        # Update global timestamps (simplified)
        if "read" in drive_letter.lower():  # Simplified check
            min_spacing = self.min_read_spacing_ms / 1000.0
            if now - self._last_global_read_at < min_spacing:
                candidate = max(candidate, self._last_global_read_at + min_spacing)
            self._last_global_read_at = candidate
        else:  # Assume write
            min_spacing = self.min_write_spacing_ms / 1000.0
            if now - self._last_global_write_at < min_spacing:
                candidate = max(candidate, self._last_global_write_at + min_spacing)
            self._last_global_write_at = candidate

        return candidate

    def _align_to_grid(self, time_value: float) -> float:
        """Align time to grid."""
        grid_size = self.grid_ms / 1000.0
        return round(time_value / grid_size) * grid_size

    def handle_failure(self, drive_letter: str, current_failures: int) -> Tuple[bool, Optional[float]]:
        """Handle drive failure with exponential quarantine backoff."""
        new_failures = current_failures + 1

        if new_failures >= self.config.error_quarantine_after:
            # Get current quarantine count from timing state
            timing = self.get_timing_state(drive_letter)
            quarantine_count = timing.quarantine_count if timing else 0
            
            # Exponential backoff: 30 * (2^quarantine_count), max at 2^11
            base_duration = 30  # seconds
            exponent = min(quarantine_count, 11)  # Cap at 2^11
            quarantine_duration = base_duration * (2 ** exponent)
            release_at = self.clock.monotonic() + quarantine_duration
            
            # Increment quarantine count for next time
            new_quarantine_count = min(quarantine_count + 1, 11)

            self.update_drive_state(
                drive_letter=drive_letter,
                state="quarantined",
                reason="error",
                quarantine_release_at=release_at,
                failure_count=new_failures,
                quarantine_count=new_quarantine_count
            )

            logger.warning(f"Drive {drive_letter} quarantined for {quarantine_duration}s (attempt {new_quarantine_count}, 2^{exponent})")
            return True, release_at  # quarantined

        return False, None  # not quarantined yet

    def handle_success(self, drive_letter: str, current_failures: int):
        """Handle successful operation - reset quarantine counter."""
        self.update_drive_state(
            drive_letter=drive_letter,
            state="normal",
            reason=None,
            failure_count=max(0, current_failures - 1),  # Decay failure count
            quarantine_count=0  # Reset on success
        )

    def check_quarantine_release(self, drive_letter: str, quarantine_release_at: Optional[float]) -> bool:
        """Check if quarantined drive should be released."""
        if quarantine_release_at is None:
            return False
        now = self.clock.monotonic()
        if now >= quarantine_release_at:
            self.update_drive_state(
                drive_letter=drive_letter,
                state="normal",
                reason=None,
                failure_count=0,
                quarantine_release_at=None
            )
            return True
        return False

class JitterPlanner:
    """Handles jitter planning with deterministic tie-breaking and HDD guard logic."""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.jitter_sec = config.jitter_sec
        self.hdd_max_gap_sec = config.hdd_max_gap_sec
        self.deadline_margin_sec = config.deadline_margin_sec
        self.grid_sec = 0.5  # 500ms grid
        
        # Daily tie-breaking state
        self._daily_seed: Optional[bytes] = None
        self._tie_epoch: Optional[str] = None
        self._update_daily_seed()
    
    def _update_daily_seed(self):
        """Update daily seed for tie-breaking (call at startup and midnight)."""
        local_date = datetime.now().date()
        epoch_str = local_date.strftime("%Y-%m-%d")
        
        if self._tie_epoch != epoch_str:
            self._tie_epoch = epoch_str
            self._daily_seed = self._compute_daily_seed(local_date)
            logger.info(f"Updated daily tie-break seed for {epoch_str}")
    
    def _compute_daily_seed(self, local_date: datetime.date) -> bytes:
        """Compute daily seed using BLAKE2s with install_id and date."""
        dstr = local_date.strftime("%Y%m%d").encode("ascii")
        key = uuid.UUID(self.config.install_id).bytes
        h = hashlib.blake2s(key=key, person=b"kap-tie1")
        h.update(dstr)
        return h.digest()[:8]  # 64-bit seed
    
    def _align_to_grid(self, time_value):
        """Align time value to 250-500ms grid for consistent scheduling."""
        # Grid alignment: round to nearest 0.25s (250ms) or 0.5s (500ms)
        # Use 0.25s grid for more precise scheduling
        grid_size = 0.25  # 250ms
        return round(time_value / grid_size) * grid_size
    
    def _get_drive_identity(self, drive_state: DriveState) -> str:
        """Get stable drive identity for tie-breaking."""
        if drive_state.volume_guid:
            return drive_state.volume_guid.upper()
        else:
            return drive_state.letter.upper()
    
    def _compute_drive_rank(self, drive_identity: str) -> int:
        """Compute deterministic rank for a drive."""
        if self._daily_seed is None:
            self._update_daily_seed()
        
        h = hashlib.blake2s(key=self._daily_seed)
        h.update(drive_identity.encode("utf-8"))
        return int.from_bytes(h.digest()[:8], "little")
    
    def _get_effective_interval(self, drive_state: DriveState) -> Tuple[float, Optional[str]]:
        """Get effective interval with HDD guard applied and update drive config.
        
        Returns (effective_interval, status_reason) where status_reason is None, "HDD_CAPPED", or "CLAMPED".
        Also updates drive_state.config.interval to reflect the effective interval.
        """
        user_interval = drive_state.config.interval
        min_interval = max(user_interval, self.config.interval_min_sec)
        status_reason = None
        
        if drive_state.config.type == "HDD":
            # Apply HDD guard: cap the interval to prevent excessive gaps
            hdd_cap = self.hdd_max_gap_sec - self.deadline_margin_sec
            # First apply minimum, then cap if needed
            effective = min(min_interval, hdd_cap)
            # But ensure we never go below the global minimum
            effective = max(effective, self.config.interval_min_sec)
            
            if effective < user_interval:
                status_reason = "HDD_CAPPED"
            elif effective > user_interval:
                status_reason = "CLAMPED"
        else:
            effective = min_interval
            if min_interval > user_interval:
                status_reason = "CLAMPED"
        
        # Update the drive config to reflect the effective interval
        # This ensures the GUI and all other components see the actual interval being used
        drive_state.config.interval = int(effective)
        
        return effective, status_reason
    
    def _is_hdd_guard_violation(self, drive_state: DriveState, candidate_time: float) -> bool:
        """Check if placing at candidate_time would violate HDD guard."""
        if drive_state.config.type != "HDD":
            return False
        
        if drive_state.last_operation is None:
            return False
        
        time_since_last = candidate_time - drive_state.last_operation
        return time_since_last > self.hdd_max_gap_sec
    
    def check_hdd_violation(self, candidate_time: float, last_operation: Optional[float], 
                           drive_state: DriveState) -> bool:
        """Check if operation would violate HDD guard.
        
        Used to detect when an operation is too late for HDD protection.
        """
        if last_operation is None or not self._is_hdd(drive_state):
            return False
        return (candidate_time - last_operation) > self.hdd_max_gap_sec
    
    def _is_hdd(self, drive_state: DriveState) -> bool:
        """Determine if drive is HDD."""
        return drive_state.config.type.upper() == "HDD"
    
    def _get_hdd_candidate_offsets(self, jitter_window: float) -> List[float]:
        """Get candidate offsets for HDDs (earlier-first with late slack)."""
        candidates = []
        
        # Earlier-only offsets: 0, -0.5, -1.0, ...
        for i in range(int(jitter_window / self.grid_sec) + 1):
            offset = -i * self.grid_sec
            if abs(offset) <= jitter_window:
                candidates.append(offset)
        
        # Add tiny late slack if within deadline margin
        if self.deadline_margin_sec >= self.grid_sec:
            candidates.append(self.grid_sec)
        
        return candidates
    
    def _get_standard_candidate_offsets(self, jitter_window: float) -> List[float]:
        """Get candidate offsets for non-HDD drives (balanced)."""
        candidates = [0.0]  # Start with nominal
        
        # Balanced offsets: +0.5, -0.5, +1.0, -1.0, ...
        for i in range(1, int(jitter_window / self.grid_sec) + 1):
            for sign in (+1, -1):
                offset = sign * i * self.grid_sec
                if abs(offset) <= jitter_window:
                    candidates.append(offset)
        
        return candidates
    
    def _check_spacing_constraints(self, candidate_time: float, operation_type: OperationType, 
                                 scheduled_ops: List[ScheduledOperation]) -> bool:
        """Check if candidate_time satisfies spacing constraints."""
        WRITE_GAP = 1.0
        ANY_GAP = 0.5
        
        for op in scheduled_ops:
            time_diff = abs(candidate_time - op.operation_time)
            
            if operation_type == OperationType.WRITE and op.operation_type == OperationType.WRITE:
                if time_diff < WRITE_GAP:
                    return False
            else:
                if time_diff < ANY_GAP:
                    return False
        
        return True
    
    def _pack_same_tick_operations(self, drives_at_tick: List[DriveState],
                                 nominal_time: float, scheduled_ops: List[ScheduledOperation]) -> List[ScheduledOperation]:
        """Pack multiple drives that have the same canonical tick time."""
        if not drives_at_tick:
            return []

        # Separate writes and reads
        writes = [d for d in drives_at_tick if d.config.type in ["HDD", "RAM-disk"] or
                 (d.config.type == "Unknown" and not self.config.treat_unknown_as_ssd)]
        reads = [d for d in drives_at_tick if d not in writes]

        new_ops = []
        placed = []  # (drive_letter, offset, operation_type)

        # Get current tie-breaking information
        current_date = datetime.now().date()
        daily_seed = self._compute_daily_seed(current_date)
        tie_epoch = current_date.strftime("%Y-%m-%d")

        # Place writes first
        if writes:
            # Sort by anchor priority: slower first, then HDD over SSD, then by rank
            def anchor_sort_key(drive):
                speed_key = float('inf') if drive.measured_speed is None else drive.measured_speed
                type_key = 0 if drive.config.type == "HDD" else 1
                rank_key = self._compute_drive_rank(self._get_drive_identity(drive))
                return (speed_key, type_key, rank_key)

            writes_sorted = sorted(writes, key=anchor_sort_key)
            anchor = writes_sorted[0]

            # Place anchor at 0 offset
            anchor_time = nominal_time
            if self._check_spacing_constraints(anchor_time, OperationType.WRITE, scheduled_ops + new_ops):
                # Add telemetry for same-tick packing
                anchor_rank = self._compute_drive_rank(self._get_drive_identity(anchor))

                new_ops.append(ScheduledOperation(
                    drive_letter=anchor.letter,
                    operation_time=anchor_time,
                    operation_type=OperationType.WRITE,
                    offset_ms=0.0,
                    jitter_reason="in_window",
                    pack_size=len(drives_at_tick),
                    tie_epoch=tie_epoch,
                    tie_rank=anchor_rank,
                    tie_seed64=daily_seed.hex()
                ))
                placed.append((anchor.letter, 0.0, OperationType.WRITE))

            # Place remaining writes at ±1.0s, ±2.0s, ...
            for i, drive in enumerate(writes_sorted[1:], start=1):
                for sign in (+1, -1):
                    offset = sign * 1.0 * i
                    if abs(offset) <= self.jitter_sec:
                        candidate_time = nominal_time + offset
                        if self._check_spacing_constraints(candidate_time, OperationType.WRITE, scheduled_ops + new_ops):
                            # Add telemetry for same-tick packing
                            drive_rank = self._compute_drive_rank(self._get_drive_identity(drive))

                            new_ops.append(ScheduledOperation(
                                drive_letter=drive.letter,
                                operation_time=candidate_time,
                                operation_type=OperationType.WRITE,
                                offset_ms=offset * 1000,
                                jitter_reason="in_window",
                                pack_size=len(drives_at_tick),
                                tie_epoch=tie_epoch,
                                tie_rank=drive_rank,
                                tie_seed64=daily_seed.hex()
                            ))
                            placed.append((drive.letter, offset, OperationType.WRITE))
                            break

        # Place reads at 0.5s, -0.5s, 1.5s, -1.5s, ...
        read_slots = [0.5] + [s * 0.5 for k in range(1, 20) for s in (+(2*k+1), -(2*k+1))]

        # Sort reads by rank
        reads_sorted = sorted(reads, key=lambda d: self._compute_drive_rank(self._get_drive_identity(d)))

        for drive in reads_sorted:
            for offset in read_slots:
                if abs(offset) <= self.jitter_sec:
                    candidate_time = nominal_time + offset
                    if self._check_spacing_constraints(candidate_time, OperationType.READ, scheduled_ops + new_ops):
                        # Add telemetry for same-tick packing
                        drive_rank = self._compute_drive_rank(self._get_drive_identity(drive))

                        new_ops.append(ScheduledOperation(
                            drive_letter=drive.letter,
                            operation_time=candidate_time,
                            operation_type=OperationType.READ,
                            offset_ms=offset * 1000,
                            jitter_reason="in_window",
                            pack_size=len(drives_at_tick),
                            tie_epoch=tie_epoch,
                            tie_rank=drive_rank,
                            tie_seed64=daily_seed.hex()
                        ))
                        placed.append((drive.letter, offset, OperationType.READ))
                        break

        # Mark HDD guard telemetry on drive states (for logging later)
        for letter, offset, op_type in placed:
            ds = next((d for d in drives_at_tick if d.letter == letter), None)
            if ds and ds.config.type == "HDD":
                if offset > 0 and offset <= self.config.deadline_margin_sec:
                    ds.late_slack_used = True
        
        return new_ops
    
    def plan_next_operation(self, drive_state: DriveState, current_time: float, 
                          scheduled_ops: List[ScheduledOperation]) -> Optional[ScheduledOperation]:
        """Plan the next operation for a drive with jitter and spacing constraints."""
        if not drive_state.enabled:
            return None
        
        # Update daily seed if needed
        self._update_daily_seed()
        
        # Get effective interval - this is now pure and returns (interval, status_reason)
        effective_interval, status_reason = self._get_effective_interval(drive_state)
        
        # Update drive state status based on effective interval calculation
        if status_reason == "CLAMPED":
            drive_state.status = DriveStatus.CLAMPED
        elif status_reason == "HDD_CAPPED":
            drive_state.status = DriveStatus.HDD_CAPPED
        elif drive_state.status in [DriveStatus.CLAMPED, DriveStatus.HDD_CAPPED] and status_reason is None:
            # Reset to normal if no longer clamped/capped
            drive_state.status = DriveStatus.ACTIVE
        
        # ONLY Strategy B: last_operation + interval
        if drive_state.last_operation is None:
            # First operation - schedule at current_time + interval
            canonical_time = current_time + effective_interval
            logger.debug(f"Drive {drive_state.letter}: First operation, canonical_time={canonical_time:.2f}")
        else:
            # Subsequent operations - schedule at last_operation + interval
            canonical_time = drive_state.last_operation + effective_interval
            logger.debug(f"Drive {drive_state.letter}: Next operation, last_op={drive_state.last_operation:.2f}, canonical_time={canonical_time:.2f}")
        
        # Determine operation type
        if drive_state.config.type in ["HDD", "RAM-disk"]:
            operation_type = OperationType.WRITE
        else:
            operation_type = OperationType.READ
        
        # Apply minimal jitter - use only nominal time to preserve exact countdown
        candidates = [0.0]  # Only nominal time - no jitter offsets

        # Try to place the operation
        for offset in candidates:
            candidate_time = canonical_time + offset

            # Check HDD guard violation
            if self._is_hdd_guard_violation(drive_state, candidate_time):
                continue

            # Check spacing constraints
            if self._check_spacing_constraints(candidate_time, operation_type, scheduled_ops):
                jitter_reason = "in_window"
                if abs(offset) > self.jitter_sec:
                    jitter_reason = "expanded"

                # Get tie-breaking information for single-drive operations
                current_date = datetime.now().date()
                daily_seed = self._compute_daily_seed(current_date)
                tie_epoch = current_date.strftime("%Y-%m-%d")
                drive_rank = self._compute_drive_rank(self._get_drive_identity(drive_state))

                # For operations with proper canonical_time (not fallback), use minimal clamping
                # This allows the full interval countdown to be preserved
                if drive_state.last_operation is not None:
                    # We have a valid last_operation, so candidate_time should represent the full interval
                    operation_time = max(candidate_time, current_time + 0.05)  # Very minimal clamp for safety
                else:
                    # Fallback case - use original clamping
                    operation_time = max(candidate_time, current_time + 0.5)
                
                # Align to 250-500ms grid for consistent scheduling
                operation_time = self._align_to_grid(operation_time)

                return ScheduledOperation(
                    drive_letter=drive_state.letter,
                    operation_time=operation_time,
                    operation_type=operation_type,
                    offset_ms=offset * 1000,
                    jitter_reason=jitter_reason,
                    pack_size=1,  # Single drive operation
                    tie_epoch=tie_epoch,
                    tie_rank=drive_rank,
                    tie_seed64=daily_seed.hex()
                )
        
        # If no candidate fits, try overflow
        # Find the nearest feasible time outside the window
        nearest_time = canonical_time
        min_distance = float('inf')

        for op in scheduled_ops:
            # Try placing just before or after each existing operation
            for direction in (-1, 1):
                if operation_type == OperationType.WRITE:
                    test_time = op.operation_time + direction * 1.0
                else:
                    test_time = op.operation_time + direction * 0.5

                if self._check_spacing_constraints(test_time, operation_type, scheduled_ops):
                    distance = abs(test_time - canonical_time)
                    if distance < min_distance:
                        min_distance = distance
                        nearest_time = test_time

        # Get tie-breaking information for overflow operations
        current_date = datetime.now().date()
        daily_seed = self._compute_daily_seed(current_date)
        tie_epoch = current_date.strftime("%Y-%m-%d")
        drive_rank = self._compute_drive_rank(self._get_drive_identity(drive_state))

        # For overflow operations, use minimal clamping if we have a valid last_operation
        if drive_state.last_operation is not None:
            operation_time = max(nearest_time, current_time + 0.05)
        else:
            operation_time = max(nearest_time, current_time + 0.5)
        
        # Align to 250-500ms grid for consistent scheduling
        operation_time = self._align_to_grid(operation_time)

        return ScheduledOperation(
            drive_letter=drive_state.letter,
            operation_time=operation_time,
            operation_type=operation_type,
            offset_ms=(nearest_time - canonical_time) * 1000,
            jitter_reason="overflow",
            pack_size=1,  # Single drive overflow
            tie_epoch=tie_epoch,
            tie_rank=drive_rank,
            tie_seed64=daily_seed.hex()
        )

class CoreEngine:
    """Main scheduling engine for Drive Revenant."""

    def __init__(self, config: AppConfig, io_manager=None, config_manager=None, logging_manager=None):
        self.config = config
        self.io_manager = io_manager
        self.config_manager = config_manager
        self.logging_manager = logging_manager
        self.jitter_planner = JitterPlanner(config)

        # New centralized scheduler
        self.scheduler = Scheduler(config)
        logger.info(f"CoreEngine initialized with scheduler: grid={config.scheduler_grid_ms}ms, "
                   f"read_spacing={config.scheduler_min_read_spacing_ms}ms, "
                   f"write_spacing={config.scheduler_min_write_spacing_ms}ms")

        # PHASE 3 COMPLETE: Scheduler is now the single source of truth
        self.scheduled_operations: List[ScheduledOperation] = []
        self.policy_state = PolicyState()

        # Threading
        self.scheduler_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.operation_queue = queue.Queue()

        # Callbacks
        self.status_callback: Optional[Callable] = None
        self.log_callback: Optional[Callable] = None

        # Status update optimization
        self._last_status_emit = 0.0
        self._status_emit_interval = 1.0  # Emit status updates every 1 second for smooth countdown
        self._last_drive_states_hash = None
        # Periodic CLI logging of next_due countdowns (configurable interval from config)
        self._last_next_due_log = 0.0
        self._cli_countdown_interval = self.config.cli_countdown_interval_sec
        
        # Drive state cache for incremental updates
        self._drive_state_cache: Dict[str, Dict[str, Any]] = {}
        self._drive_info_cache: Dict[str, Dict[str, Any]] = {}
        
        # Scheduler optimization caches
        self._policy_cache_time = 0.0
        self._policy_cache_interval = 5.0  # Cache policy state for 5 seconds
        self._cached_policy_state = None
        self._last_plan_time = 0.0
        self._plan_cache_interval = 1.0  # Cache planning for 1 second

        # Initialize drive states
        self._initialize_drive_states()
        
        # Ensure all drives have their effective intervals calculated
        self._recalculate_all_effective_intervals()
    
    def _build_drive_state_from_scheduler(self, letter: str) -> Optional[DriveState]:
        """PHASE 3 HELPER: Build DriveState from scheduler data (transitional).
        
        This helper allows legacy code expecting DriveState to work with scheduler data.
        Will be removed once all code is refactored to use DriveTimingState directly.
        """
        timing = self.scheduler.get_timing_state(letter)
        if not timing:
            return None
        
        # Build DriveConfig from scheduler data
        from app_types import DriveConfig
        config = DriveConfig(
            enabled=timing.enabled,
            interval=timing.interval_sec,
            type=timing.type,
            ping_dir=timing.ping_dir
        )
        
        # Build DriveState from scheduler data
        drive_state = DriveState(
            letter=letter,
            config=config,
            enabled=timing.enabled,
            status=timing.status,
            last_operation=timing.last_operation,
            quarantine_until=timing.quarantine_until,
            measured_speed=timing.measured_speed,
            volume_guid=timing.volume_guid,
            last_results=timing.last_results,
            late_slack_used=timing.late_slack_used,
            hdd_guard_violation=timing.hdd_guard_violation,
            consecutive_tick_failures=timing.consecutive_tick_failures,
            last_tick_attempts=timing.last_tick_attempts,
            tick_counter=timing.tick_counter,
            pause_reason=timing.pause_reason
        )
        
        return drive_state
    
    def _recalculate_all_effective_intervals(self):
        """Recalculate effective intervals for all drives and update their configs."""
        # PHASE 3: Read from scheduler instead of drive_states
        all_timing_states = self.scheduler.get_all_drive_states()
        for letter, timing in all_timing_states.items():
            if timing.enabled:
                # Build DriveState for compatibility with jitter_planner
                drive_state = self._build_drive_state_from_scheduler(letter)
                if not drive_state:
                    continue
                # Calculate and apply effective interval
                effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
                
                # Update drive state status based on effective interval calculation
                if status_reason == "CLAMPED":
                    drive_state.status = DriveStatus.CLAMPED
                elif status_reason == "HDD_CAPPED":
                    drive_state.status = DriveStatus.HDD_CAPPED
                elif drive_state.status in [DriveStatus.CLAMPED, DriveStatus.HDD_CAPPED] and status_reason is None:
                    # Reset to normal if no longer clamped/capped
                    drive_state.status = DriveStatus.ACTIVE
                
                # DUAL-WRITE Phase 2: Update old scheduler method
                existing_timing = self.scheduler.get_timing_state(letter)
                next_due_at = existing_timing.next_due_at if existing_timing else None
                if next_due_at is None and drive_state.enabled and drive_state.status == DriveStatus.ACTIVE:
                    current_time = self.scheduler.clock.monotonic()
                    next_due_at = current_time + drive_state.config.interval
                
                self.scheduler.update_drive_state(
                    drive_letter=letter,
                    state="normal",
                    next_due_at=next_due_at,
                    interval_sec=drive_state.config.interval,  # This now contains the effective interval
                    effective_interval_sec=effective_interval,
                    type=drive_state.config.type,
                    status_reason=status_reason
                )
                
                # DUAL-WRITE Phase 2: Update new scheduler methods
                self.scheduler.set_drive_config(
                    drive_letter=letter,
                    enabled=drive_state.enabled,
                    interval_sec=drive_state.config.interval,
                    drive_type=drive_state.config.type,
                    ping_dir=drive_state.config.ping_dir
                )
                self.scheduler.set_drive_status(
                    drive_letter=letter,
                    status=drive_state.status,
                    pause_reason=drive_state.pause_reason
                )
                
                logger.debug(f"Recalculated effective interval for {letter}: {drive_state.config.interval}s")
    
    def _remove_stale_drives(self, current_timestamp: float):
        """Remove drives that are confirmed permanently gone.
        
        Only removes drives that meet BOTH conditions:
        1. Haven't been seen for configured days (stale)
        2. At max quarantine level (11) - indicates persistent failure
        
        This prevents removal of drives that are temporarily offline.
        """
        if self.config.drive_stale_removal_days <= 0:
            logger.debug("Stale drive removal disabled (drive_stale_removal_days <= 0)")
            return
        
        stale_threshold = current_timestamp - (self.config.drive_stale_removal_days * 86400)
        stale_drives = []
        
        for letter, drive_config in list(self.config.per_drive.items()):
            timing = self.scheduler.get_timing_state(letter)
            
            # Remove if:
            # 1. Not seen for X days AND
            # 2. At max quarantine level (11) - indicates persistent failure
            last_seen = drive_config.last_seen_timestamp
            at_max_quarantine = timing and timing.quarantine_count >= 11
            
            if last_seen and last_seen < stale_threshold and at_max_quarantine:
                days_since_seen = (current_timestamp - last_seen) / 86400
                stale_drives.append((letter, days_since_seen, timing.quarantine_count))
        
        for letter, days, q_count in stale_drives:
            logger.warning(f"Removing permanently failed drive {letter} (not seen {days:.1f}d, quarantine level {q_count})")
            del self.config.per_drive[letter]
            # Also remove from scheduler to clean up GUI
            # (Note: Scheduler's get_all_drive_states will no longer return this drive)
        
        if stale_drives:
            logger.info(f"Removed {len(stale_drives)} permanently failed drive(s) from configuration")
            if self.config_manager:
                self.config_manager.save_config(self.config)
                logger.info("Saved configuration after stale drive removal")
    
    def _initialize_drive_states(self):
        """Initialize drive states from configuration."""
        # Clear drive info cache to ensure fresh data on initialization
        self._drive_info_cache = {}
        logger.debug("Cleared drive info cache for initialization")
        
        # First scan should be FULL to discover any new drives
        available_drives = self._scan_and_update_drives(mode="full")

        for letter, drive_config in self.config.per_drive.items():
            # Determine if drive is currently available
            is_available = letter in available_drives

            # Create drive state for all configured drives
            drive_state = DriveState(
                letter=letter,
                config=drive_config,
                enabled=drive_config.enabled,
                status=DriveStatus.ACTIVE if (drive_config.enabled and is_available) else DriveStatus.OFFLINE
            )

            # Update drive type if we detected it and it's currently available
            if is_available:
                detected_info = available_drives[letter]
                if detected_info["type"] != "Unknown" and drive_config.type == "Unknown":
                    drive_state.config.type = detected_info["type"]
                    logger.debug(f"Updated drive {letter} type to {detected_info['type']}")

            # Add drive to scheduler for GUI visibility
            status_str = "normal" if drive_state.status == DriveStatus.ACTIVE else "offline"
            effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
            
            # Update drive state status based on effective interval calculation
            if status_reason == "CLAMPED":
                drive_state.status = DriveStatus.CLAMPED
            elif status_reason == "HDD_CAPPED":
                drive_state.status = DriveStatus.HDD_CAPPED
            elif drive_state.status in [DriveStatus.CLAMPED, DriveStatus.HDD_CAPPED] and status_reason is None:
                # Reset to normal if no longer clamped/capped
                drive_state.status = DriveStatus.ACTIVE
            
            # Set initial next_due_at to current time + interval for enabled ACTIVE drives only
            next_due_at = None
            if drive_state.enabled and drive_state.status == DriveStatus.ACTIVE:
                current_time = self.scheduler.clock.monotonic()
                next_due_at = current_time + drive_state.config.interval
            
            # DUAL-WRITE Phase 2: Set config and status FIRST for proper synchronization
            self.scheduler.set_drive_config(
                drive_letter=letter,
                enabled=drive_config.enabled,
                interval_sec=drive_state.config.interval,
                drive_type=drive_config.type,
                ping_dir=drive_config.ping_dir
            )
            self.scheduler.set_drive_status(
                drive_letter=letter,
                status=drive_state.status,
                pause_reason=drive_state.pause_reason
            )
            
            # DUAL-WRITE Phase 2: Then update old scheduler method (will be replaced in Phase 3)
            self.scheduler.update_drive_state(
                drive_letter=letter,
                state=status_str,
                next_due_at=next_due_at,
                interval_sec=drive_state.config.interval,  # Use the updated interval after effective calculation
                effective_interval_sec=effective_interval,
                failure_count=0,
                type=drive_config.type,
                status_reason=status_reason
            )

    def _scan_and_update_drives(self, mode: str = "quick") -> Dict[str, Dict[str, Any]]:
        """Scan for available drives and update configuration.
        
        Args:
            mode: "quick" (only check configured drives) or "full" (scan all E-Z)
        """
        if not self.io_manager:
            logger.error("I/O manager not available for drive scanning")
            return {}

        logger.info(f"Scanning for available external drives (mode={mode})...")
        if self.logging_manager:
            self.logging_manager.log_debug(f"Starting drive scan (mode={mode})")

        try:
            from app_utils import normalize_drive_letter
            available_drives_raw = self.io_manager.scan_available_drives(
                mode=mode,
                config_drives=self.config.per_drive if mode == "quick" else None
            )
            
            # Normalize all drive letters to ensure consistency (E:, F:, etc.)
            available_drives = {}
            for letter, info in available_drives_raw.items():
                normalized_letter = normalize_drive_letter(letter)
                if normalized_letter:
                    available_drives[normalized_letter] = info
                    logger.debug(f"Normalized drive letter {letter} -> {normalized_letter}")
                else:
                    logger.warning(f"Failed to normalize drive letter: {letter}")
            
            logger.debug(f"Normalized {len(available_drives)} drive letters")

            # Update configuration with newly discovered drives
            current_timestamp = time.time()
            for drive_letter, drive_info in available_drives.items():
                if self.logging_manager:
                    self.logging_manager.log_drive_scan(drive_letter, "discovered", f"type={drive_info['type']}")

                if drive_letter not in self.config.per_drive:
                    # Check if this is a forced drive letter
                    is_forced = False
                    if hasattr(self.config, 'forced_drive_letters') and self.config.forced_drive_letters:
                        forced_letters = [l.strip().upper() for l in self.config.forced_drive_letters.split(',')]
                        forced_letters_normalized = [f"{l}:" if not l.endswith(':') else l for l in forced_letters if l]
                        is_forced = drive_letter in forced_letters_normalized
                    
                    # Calculate last_seen: forced drives get 13 days grace (stale at 15d = 2d until removal)
                    # Normal drives get current time (stale at 15d)
                    if is_forced:
                        grace_period_sec = 2 * 86400  # 2 days before stale threshold (15d - 13d = 2d)
                        last_seen_ts = current_timestamp - ((self.config.drive_stale_removal_days - 2) * 86400)
                        logger.info(f"Forced drive {drive_letter} detected - setting last_seen to 13 days ago (2d grace period)")
                    else:
                        last_seen_ts = current_timestamp
                    
                    # Add new drive with default settings and tracking info
                    self.config.per_drive[drive_letter] = DriveConfig(
                        enabled=False,  # Start disabled for safety
                        interval=self.config.default_interval_sec,
                        type=drive_info["type"],
                        ping_dir=None,
                        volume_guid=drive_info.get('volume_guid'),
                        last_seen_timestamp=last_seen_ts,
                        total_size_bytes=drive_info.get('total_size_bytes')
                    )
                    
                    if is_forced:
                        logger.warning(f"Discovered FORCED drive {drive_letter} ({drive_info['type']}) - will be removed in 2 days if offline")
                    else:
                        logger.info(f"Discovered new drive {drive_letter} ({drive_info['type']})")
                else:
                    # Update existing drive's tracking information
                    self.config.per_drive[drive_letter].last_seen_timestamp = current_timestamp
                    self.config.per_drive[drive_letter].volume_guid = drive_info.get('volume_guid')
                    self.config.per_drive[drive_letter].total_size_bytes = drive_info.get('total_size_bytes')
                    logger.debug(f"Updated tracking info for {drive_letter}")
            
            # Remove stale drives (drives not seen for configured number of days)
            self._remove_stale_drives(current_timestamp)

            # Mark drives as offline if not currently available
            for drive_letter in self.config.per_drive:
                if drive_letter not in available_drives:
                    if self.logging_manager:
                        self.logging_manager.log_drive_scan(drive_letter, "offline", "not currently available")
                    logger.debug(f"Drive {drive_letter} is not currently available (marked offline)")

                    # PHASE 3: Update scheduler to mark drive as offline
                    drive_state = self._build_drive_state_from_scheduler(drive_letter)
                    if drive_state:
                        effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
                        self.scheduler.update_drive_state(
                            drive_letter=drive_letter,
                            state="offline",
                            interval_sec=drive_state.config.interval,
                            effective_interval_sec=effective_interval,
                            failure_count=drive_state.consecutive_tick_failures,
                            type=drive_state.config.type
                        )

            # Save updated configuration only when new drives are discovered
            # PHASE 3: Check if this is initial scan or new drives found
            all_timing_states = self.scheduler.get_all_drive_states()
            is_initial_scan = len(all_timing_states) == 0
            new_drives_found = any(drive_letter not in all_timing_states for drive_letter in available_drives)
            
            # Only save config if new drives were found AND this is not the initial scan
            # The initial scan should not trigger a config save as it's just loading existing drives
            if new_drives_found and not is_initial_scan:
                if self.config_manager:
                    self.config_manager.save_config(self.config)
                    logger.info(f"Saved configuration with {len(available_drives)} drives")
                else:
                    logger.warning("Config manager not available for saving configuration")

            if self.logging_manager:
                self.logging_manager.log_debug(f"Drive scan completed: {len(available_drives)} drives found")

            return available_drives

        except Exception as e:
            logger.error(f"Error scanning drives: {e}")
            if self.logging_manager:
                self.logging_manager.log_debug(f"Drive scan failed: {e}")
            return {}
    
    def start(self):
        """Start the scheduling engine."""
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            logger.warning("Scheduler already running")
            return
        
        self.stop_event.clear()
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        logger.info("Core engine started")
    
    def stop(self, timeout_ms: int = 500):
        """Stop the scheduling engine."""
        if not self.scheduler_thread or not self.scheduler_thread.is_alive():
            return
        
        self.stop_event.set()
        self.scheduler_thread.join(timeout=timeout_ms / 1000.0)
        
        if self.scheduler_thread.is_alive():
            logger.warning("Scheduler thread did not stop within timeout")
        else:
            logger.info("Core engine stopped")
    
    def _scheduler_loop(self):
        """Main scheduler loop running in background thread."""
        logger.info("Scheduler loop started")
        
        while not self.stop_event.is_set():
            try:
                current_time = time.monotonic()

                # Update policy state (with caching)
                self._update_policy_state_cached(current_time)

                # STEP 1: Plan operations FIRST
                # This ensures all drives have valid next_due_at before execution
                self._plan_operations_cached(current_time)

                # STEP 2: Execute operations that are due
                # This no longer clears next_due immediately
                self._execute_due_operations(current_time)

                # Print next_due countdowns to CLI at configured interval
                if (current_time - self._last_next_due_log) >= self._cli_countdown_interval:
                    self._log_next_due_countdowns(current_time)
                    self._last_next_due_log = current_time

                # Emit status update only if there are actual changes or it's been a while
                if self._should_emit_status_update(current_time):
                    if self.status_callback:
                        self.status_callback(self.get_full_status_snapshot())
                    self._last_status_emit = current_time

                # Sleep until next check (500ms)
                self.stop_event.wait(0.5)

            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                self.stop_event.wait(1.0)  # Wait longer on error
        
        logger.info("Scheduler loop ended")
    
    def _update_policy_state(self):
        """Update policy state based on current conditions."""
        # Preserve existing global pause state instead of resetting
        old_global_pause = self.policy_state.global_pause
        self.policy_state = PolicyState()
        self.policy_state.global_pause = old_global_pause
        
        # Check global pause
        if self.policy_state.global_pause:
            self.policy_state.reasons.append("Global pause")

        # Check battery pause
        if self.config.pause_on_battery and self._is_on_battery_power():
            self.policy_state.battery_pause = True
            self.policy_state.reasons.append("Battery power")

        # Check idle pause
        if self.config.idle_pause_min > 0 and self._is_system_idle():
            self.policy_state.idle_pause = True
            self.policy_state.reasons.append("System idle")

        # Update scheduler with policy state changes for all drives
        pause_reason = None
        if self.policy_state.battery_pause:
            pause_reason = "battery"
        elif self.policy_state.idle_pause:
            pause_reason = "idle"
        elif self.policy_state.global_pause:
            pause_reason = "global"

        # PHASE 3: Read from scheduler instead of drive_states
        all_timing_states = self.scheduler.get_all_drive_states()
        for drive_letter, timing in all_timing_states.items():
            if timing.enabled and timing.status != DriveStatus.QUARANTINE:
                # Build DriveState for compatibility
                drive_state = self._build_drive_state_from_scheduler(drive_letter)
                if not drive_state:
                    continue
                    
                # Check if this drive was paused by user or global pause (not by policy)
                was_user_or_global_paused = (drive_state.status == DriveStatus.PAUSED and 
                                           drive_state.pause_reason in ["user", "global"])
                
                if pause_reason and not was_user_or_global_paused:
                    # Update to paused state (policy-based pause)
                    drive_state.status = DriveStatus.PAUSED
                    drive_state.pause_reason = pause_reason
                    effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
                    self.scheduler.update_drive_state(
                        drive_letter=drive_letter,
                        state="paused",
                        reason=pause_reason,
                        interval_sec=drive_state.config.interval,
                        effective_interval_sec=effective_interval,
                        last_ok_at=drive_state.last_operation,
                        next_due_at=None,  # Clear next_due_at when pausing
                        failure_count=drive_state.consecutive_tick_failures,
                        type=drive_state.config.type
                    )
                    # PHASE 3: Also update new scheduler methods
                    self.scheduler.set_drive_status(drive_letter, DriveStatus.PAUSED, pause_reason)
                        
                elif not pause_reason and not was_user_or_global_paused:
                    # Update to active state (only if not user/global-paused)
                    if drive_state.status == DriveStatus.PAUSED:
                        drive_state.status = DriveStatus.ACTIVE
                        drive_state.pause_reason = None
                        effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
                        self.scheduler.update_drive_state(
                            drive_letter=drive_letter,
                            state="normal",
                            reason="normal",
                            interval_sec=drive_state.config.interval,
                            effective_interval_sec=effective_interval,
                            last_ok_at=drive_state.last_operation,
                            next_due_at=None,  # Clear next_due_at to trigger replanning
                            failure_count=drive_state.consecutive_tick_failures,
                            type=drive_state.config.type
                        )
                        # PHASE 3: Also update new scheduler methods
                        self.scheduler.set_drive_status(drive_letter, DriveStatus.ACTIVE, None)
                # If was_user_or_global_paused, leave the drive state unchanged
    
    def _is_on_battery_power(self) -> bool:
        """Check if system is running on battery power."""
        try:
            import ctypes
            from ctypes import wintypes
            
            # Get system power status
            class SYSTEM_POWER_STATUS(ctypes.Structure):
                _fields_ = [
                    ("ACLineStatus", wintypes.BYTE),
                    ("BatteryFlag", wintypes.BYTE),
                    ("BatteryLifePercent", wintypes.BYTE),
                    ("SystemStatusFlag", wintypes.BYTE),
                    ("BatteryLifeTime", wintypes.DWORD),
                    ("BatteryFullLifeTime", wintypes.DWORD),
                ]
            
            power_status = SYSTEM_POWER_STATUS()
            result = ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power_status))
            
            if result:
                # ACLineStatus: 0 = offline (battery), 1 = online (AC), 255 = unknown
                return power_status.ACLineStatus == 0
            
            return False
            
        except Exception as e:
            logger.debug(f"Failed to check battery status: {e}")
            return False
    
    def _is_system_idle(self) -> bool:
        """Check if system is idle (simplified implementation)."""
        try:
            import ctypes
            from ctypes import wintypes
            
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.UINT),
                    ("dwTime", wintypes.DWORD),
                ]
            
            last_input = LASTINPUTINFO()
            last_input.cbSize = ctypes.sizeof(LASTINPUTINFO)
            
            result = ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input))
            
            if result:
                # Get current tick count
                current_tick = ctypes.windll.kernel32.GetTickCount()
                idle_time_ms = current_tick - last_input.dwTime
                idle_time_min = idle_time_ms / (1000 * 60)  # Convert to minutes
                
                return idle_time_min >= self.config.idle_pause_min
            
            return False
            
        except Exception as e:
            logger.debug(f"Failed to check idle status: {e}")
            return False
    
    def _plan_operations(self, current_time: float):
        """Plan operations for all drives."""
        # Check if globally paused - if so, don't plan any operations and set drive statuses to paused
        if self.policy_state.global_pause:
            # PHASE 3: Read from scheduler
            paused_letters = []
            for letter, timing in self.scheduler.get_all_drive_states().items():
                if timing.enabled and timing.status != DriveStatus.QUARANTINE:
                    # Build DriveState for jitter_planner compatibility
                    drive_state = self._build_drive_state_from_scheduler(letter)
                    if not drive_state:
                        continue
                    
                    drive_state.status = DriveStatus.PAUSED
                    drive_state.pause_reason = "global"
                    paused_letters.append(letter)
                    
                    # Update scheduler
                    effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
                    self.scheduler.update_drive_state(
                        drive_letter=letter,
                        state="paused",
                        reason="global",
                        interval_sec=drive_state.config.interval,
                        effective_interval_sec=effective_interval,
                        last_ok_at=drive_state.last_operation,
                        next_due_at=None,
                        failure_count=drive_state.consecutive_tick_failures,
                        type=drive_state.config.type
                    )
                    # PHASE 3: Also use new scheduler method
                    self.scheduler.set_drive_status(letter, DriveStatus.PAUSED, "global")
            
            # Clear scheduled operations for globally paused drives
            if paused_letters:
                self.scheduled_operations = [
                    op for op in self.scheduled_operations 
                    if op.drive_letter not in paused_letters
                ]
            return

        # Group drives by canonical tick time (only for drives needing new operations)
        tick_groups: Dict[float, List[DriveState]] = {}

        # PHASE 3: Read from scheduler
        for letter, timing in self.scheduler.get_all_drive_states().items():
            if not timing.enabled:
                continue

            # Skip quarantined drives
            if timing.status == DriveStatus.QUARANTINE:
                continue
            
            # Skip drives that already have FUTURE scheduled operations
            if timing.next_due_at is not None and timing.next_due_at > current_time:
                logger.debug(f"Skipping {letter} (next_due_at={timing.next_due_at:.2f} > now={current_time:.2f})")
                continue
            
            # Plan for drives with None OR past-due next_due_at
            logger.debug(f"Planning {letter} (next_due_at={timing.next_due_at}, needs planning)")
            
            # Build DriveState for compatibility with jitter_planner
            drive_state = self._build_drive_state_from_scheduler(letter)
            if not drive_state:
                continue
            
            # All drives without next_due need operations planned
            canonical_time = current_time
            
            # Snap to grid
            grid_time = round(canonical_time / self.jitter_planner.grid_sec) * self.jitter_planner.grid_sec
            
            if grid_time not in tick_groups:
                tick_groups[grid_time] = []
            tick_groups[grid_time].append(drive_state)
        
        # Plan operations for each tick group
        new_operations = []
        for tick_time, drives in tick_groups.items():
            if len(drives) == 1:
                # Single drive - use standard planning
                drive = drives[0]
                timing_state = self.scheduler.get_timing_state(drive.letter)
                next_due = timing_state.next_due_at if timing_state else None
                logger.debug(f"Planning operation for drive {drive.letter} (next_due={next_due})")
                op = self.jitter_planner.plan_next_operation(drive, current_time, self.scheduled_operations + new_operations)
                if op:
                    new_operations.append(op)
                    logger.debug(f"Planned operation for {drive.letter} at {op.operation_time:.2f}")
                else:
                    logger.warning(f"Failed to plan operation for {drive.letter}")
            else:
                # Multiple drives - use packing
                logger.debug(f"Planning packed operations for {len(drives)} drives at tick {tick_time}")
                packed_ops = self.jitter_planner._pack_same_tick_operations(drives, tick_time, self.scheduled_operations + new_operations)
                new_operations.extend(packed_ops)

                # Log same-tick packing event
                if self.logging_manager and packed_ops:
                    self.logging_manager.log_scheduler_event(
                        "same_tick_packing",
                        {
                            "tick_time": tick_time,
                            "pack_size": len(drives),
                            "drives": [d.letter for d in drives]
                        },
                        current_time
                    )
        
        # Add new operations to schedule
        self.scheduled_operations.extend(new_operations)

        # Update next_due for each drive based on planned operations
        for op in new_operations:
            # PHASE 3: Read from scheduler
            drive_state = self._build_drive_state_from_scheduler(op.drive_letter)
            if drive_state:
                # Update scheduler with new next_due_at
                effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
                
                # Update drive state status based on effective interval calculation
                if status_reason == "CLAMPED":
                    drive_state.status = DriveStatus.CLAMPED
                elif status_reason == "HDD_CAPPED":
                    drive_state.status = DriveStatus.HDD_CAPPED
                elif drive_state.status in [DriveStatus.CLAMPED, DriveStatus.HDD_CAPPED] and status_reason is None:
                    # Reset to normal if no longer clamped/capped
                    drive_state.status = DriveStatus.ACTIVE
                
                self.scheduler.update_drive_state(
                    drive_letter=op.drive_letter,
                    state="normal",
                    interval_sec=drive_state.config.interval,
                    effective_interval_sec=effective_interval,
                    interval_display=drive_state.config.interval,  # User's configured interval for countdown
                    last_ok_at=drive_state.last_operation,
                    next_due_at=op.operation_time,
                    failure_count=drive_state.consecutive_tick_failures,
                    type=drive_state.config.type,
                    status_reason=status_reason
                )

                logger.info(f"COUNTDOWN FIX: Planned {op.drive_letter} next_due_at={op.operation_time:.3f} (interval={effective_interval:.1f}s)")

        # Sort by operation time
        self.scheduled_operations.sort(key=lambda op: op.operation_time)
    
    def _generate_upcoming_preview(self, current_time: float, target_count: int = 5) -> List[Dict[str, Any]]:
        """Generate preview of upcoming operations using lightweight simulation.
        
        Simulates the next few planning cycles without committing operations to self.scheduled_operations.
        Uses the same jitter/packing/spacing rules as the real scheduler.
        
        Args:
            current_time: Current monotonic time
            target_count: Target number of operations to generate
            
        Returns:
            List of preview operations: [{"drive": "G:", "time": 12345.67, "is_preview": True}, ...]
        """
        # PHASE 3: Read from scheduler
        all_timing_states = self.scheduler.get_all_drive_states()
        if not all_timing_states:
            return []
        
        # Calculate preview horizon
        preview_horizon = self.config.hdd_max_gap_sec * 5 + 1
        
        # Get currently scheduled operations (real ones)
        real_operations = list(self.scheduled_operations)
        preview_operations = []
        
        # Create a copy of drive states for simulation
        sim_drive_states = {}
        for letter, timing in all_timing_states.items():
            if timing.enabled and timing.status not in [DriveStatus.PAUSED, DriveStatus.QUARANTINE]:
                drive_state = self._build_drive_state_from_scheduler(letter)
                if drive_state:
                    sim_drive_states[letter] = drive_state
        
        if not sim_drive_states:
            return []
        
        # Simulate planning cycles until we have enough operations or hit the time horizon
        sim_time = current_time
        max_sim_time = current_time + preview_horizon
        
        # Track the last scheduled time for each drive to prevent rapid rescheduling
        drive_last_scheduled = {}
        
        # Initialize with real scheduled operations
        for op in real_operations:
            drive_last_scheduled[op.drive_letter] = op.operation_time
        
        while len(preview_operations) < target_count and sim_time < max_sim_time:
            # Find drives that need operations planned
            drives_needing_ops = []
            for letter, drive_state in sim_drive_states.items():
                # Check if this drive already has a scheduled operation in the preview window
                has_future_op = False
                
                # Check real_operations (ScheduledOperation objects)
                for op in real_operations:
                    if op.drive_letter == letter and op.operation_time > sim_time:
                        has_future_op = True
                        break
                
                # Check preview_operations (dict objects)
                if not has_future_op:
                    for op in preview_operations:
                        if op["drive"] == letter and op["time"] > sim_time:
                            has_future_op = True
                            break
                
                # Check if drive was recently scheduled (within its interval)
                if not has_future_op and letter in drive_last_scheduled:
                    last_scheduled_time = drive_last_scheduled[letter]
                    min_interval = drive_state.config.interval * 0.9  # 90% of interval as minimum
                    if sim_time - last_scheduled_time < min_interval:
                        has_future_op = True  # Skip this drive for now
                
                if not has_future_op:
                    drives_needing_ops.append(drive_state)
            
            if not drives_needing_ops:
                # All drives have operations planned, advance time
                sim_time += 1.0
                continue
            
            # Plan operations for drives that need them
            for drive_state in drives_needing_ops:
                # Use existing jitter planner to maintain consistency
                all_scheduled_ops = real_operations + [ScheduledOperation(
                    drive_letter=op["drive"],
                    operation_time=op["time"],
                    operation_type=OperationType.READ,  # Default for preview
                    offset_ms=0,
                    jitter_reason="preview",
                    pack_size=1,
                    tie_epoch="",
                    tie_rank=0,
                    tie_seed64=""
                ) for op in preview_operations]
                
                preview_op = self.jitter_planner.plan_next_operation(drive_state, sim_time, all_scheduled_ops)
                if preview_op and preview_op.operation_time <= max_sim_time:
                    preview_operations.append({
                        "drive": preview_op.drive_letter,
                        "time": preview_op.operation_time,
                        "is_preview": True
                    })
                    # Track when this drive was last scheduled
                    drive_last_scheduled[preview_op.drive_letter] = preview_op.operation_time
            
            # Advance simulation time
            sim_time += 0.5
        
        # Sort all operations by time
        all_ops = []
        for op in real_operations:
            all_ops.append({
                "drive": op.drive_letter,
                "time": op.operation_time,
                "is_preview": False
            })
        all_ops.extend(preview_operations)
        all_ops.sort(key=lambda x: x["time"])
        
        # Return first target_count operations
        return all_ops[:target_count]
    
    def _execute_due_operations(self, current_time: float):
        """Execute operations that are due."""
        due_operations = []
        
        # Find due operations
        while self.scheduled_operations and self.scheduled_operations[0].operation_time <= current_time:
            due_operations.append(self.scheduled_operations.pop(0))
        
        # Clear next_due_at for each drive so they can be re-planned after execution
        for op in due_operations:
            # Direct update to timing state (cleaner than full update_drive_state call)
            timing = self.scheduler.get_timing_state(op.drive_letter)
            if timing:
                old_next_due = timing.next_due_at
                timing.next_due_at = None
                logger.info(f"COUNTDOWN FIX: Cleared next_due_at for {op.drive_letter} (was {old_next_due}, now None) to enable re-planning")
            else:
                logger.error(f"COUNTDOWN FIX: No timing state found for {op.drive_letter} - cannot clear next_due_at!")
        
        # Execute each due operation
        for op in due_operations:
            self._execute_operation(op, current_time)
    
    def _execute_operation(self, operation: ScheduledOperation, current_time: float):
        """Execute a single operation with outer retry logic."""
        # PHASE 3: Read from scheduler
        drive_state = self._build_drive_state_from_scheduler(operation.drive_letter)
        if not drive_state:
            logger.error(f"No drive state found for {operation.drive_letter}")
            return
        
        # Check if drive is in quarantine
        if drive_state.quarantine_until and current_time < drive_state.quarantine_until:
            logger.info(f"Drive {operation.drive_letter} in quarantine until {drive_state.quarantine_until}")
            return
        
        # Outer retry loop (3 attempts max)
        tick_success = False
        final_result = None
        attempt_count = 0
        
        for attempt in range(MAX_OUTER_ATTEMPTS):
            attempt_count = attempt + 1
            drive_state.last_tick_attempts = attempt_count
            
            # Apply backoff delay (except for first attempt)
            if attempt > 0:
                backoff_ms = OUTER_RETRY_BACKOFF_MS[attempt] if attempt < len(OUTER_RETRY_BACKOFF_MS) else 100
                time.sleep(backoff_ms / 1000.0)
                
                # Log retry attempt
                if self.log_callback and hasattr(self.log_callback, 'log_retry_attempt'):
                    self.log_callback.log_retry_attempt(operation.drive_letter, attempt_count, 
                                                      final_result.failure_class if final_result else "UNKNOWN", 
                                                      backoff_ms)
            
            # Execute the I/O operation via I/O manager
            io_result = self._perform_io_operation(drive_state, operation)
            final_result = io_result
            
            # Check result and failure_class
            if io_result.failure_class == "DEVICE_GONE":
                # Device is gone, don't retry
                logger.warning(f"Drive {operation.drive_letter} device gone, stopping retries")
                break
            elif io_result.result_code in (ResultCode.OK, ResultCode.PARTIAL_FLUSH):
                # Success, stop retrying
                tick_success = True
                break
            elif io_result.failure_class in ("LOCKED", "IO_FATAL"):
                # Retryable error, continue loop
                logger.debug(f"Drive {operation.drive_letter} attempt {attempt_count} failed: {io_result.failure_class}")
                continue
            else:
                # Other errors, continue retrying
                logger.debug(f"Drive {operation.drive_letter} attempt {attempt_count} failed: {io_result.result_code}")
                continue
        
        # HDD guard violation check (compute before updating last_operation)
        # Use centralized HDD logic from JitterPlanner
        drive_state.hdd_guard_violation = self.jitter_planner.check_hdd_violation(
            current_time, drive_state.last_operation, drive_state
        )

        # Update drive state
        drive_state.last_operation = current_time
        # DO NOT clear next_due here!
        # It will be re-planned in the next loop iteration

        # Store the IOResult in last_results (keep only last 10)
        if final_result:
            drive_state.last_results.append(final_result)
            if len(drive_state.last_results) > 10:
                drive_state.last_results = drive_state.last_results[-10:]

        # Update tick-level failure counting
        if tick_success:
            drive_state.consecutive_tick_failures = 0

            # Update scheduler on success
            effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
            
            # Update drive state status based on effective interval calculation
            if status_reason == "CLAMPED":
                drive_state.status = DriveStatus.CLAMPED
            elif status_reason == "HDD_CAPPED":
                drive_state.status = DriveStatus.HDD_CAPPED
            elif drive_state.status in [DriveStatus.CLAMPED, DriveStatus.HDD_CAPPED] and status_reason is None:
                # Reset to normal if no longer clamped/capped
                drive_state.status = DriveStatus.ACTIVE
            
            # DUAL-WRITE Phase 2: Update old scheduler method
            self.scheduler.update_drive_state(
                drive_letter=operation.drive_letter,
                state="normal",
                interval_sec=drive_state.config.interval,
                effective_interval_sec=effective_interval,
                interval_display=drive_state.config.interval,  # User's configured interval for countdown
                last_ok_at=current_time,
                next_due_at=None,  # Clear so drive can be re-planned
                failure_count=0,  # Reset on success
                type=drive_state.config.type,
                status_reason=status_reason
            )
            
            # DUAL-WRITE Phase 2: Also record in new scheduler method
            self.scheduler.record_operation_result(
                drive_letter=operation.drive_letter,
                current_time=current_time,
                io_result=final_result,
                tick_success=True
            )
            self.scheduler.set_drive_status(
                drive_letter=operation.drive_letter,
                status=drive_state.status,
                pause_reason=drive_state.pause_reason
            )
        else:
            drive_state.consecutive_tick_failures += 1
            
            # DUAL-WRITE Phase 2: Record failure in new scheduler method
            self.scheduler.record_operation_result(
                drive_letter=operation.drive_letter,
                current_time=current_time,
                io_result=final_result,
                tick_success=False
            )

            # Check for quarantine based on tick failures
            if drive_state.consecutive_tick_failures >= TICK_FAILURES_FOR_QUARANTINE:
                drive_state.quarantine_until = current_time + self.config.error_quarantine_sec
                drive_state.status = DriveStatus.QUARANTINE

                # Update scheduler with quarantine
                effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
                self.scheduler.update_drive_state(
                    drive_letter=operation.drive_letter,
                    state="quarantined",
                    reason="error",
                    interval_sec=drive_state.config.interval,
                    effective_interval_sec=effective_interval,
                    last_ok_at=drive_state.last_operation,
                    next_due_at=None,
                    failure_count=drive_state.consecutive_tick_failures,
                    quarantine_release_at=drive_state.quarantine_until,
                    type=drive_state.config.type
                )
                
                # DUAL-WRITE Phase 2: Update status in new scheduler method
                self.scheduler.set_drive_status(
                    drive_letter=operation.drive_letter,
                    status=DriveStatus.QUARANTINE,
                    pause_reason=None
                )

                logger.warning(f"Drive {operation.drive_letter} quarantined after {drive_state.consecutive_tick_failures} failed ticks")
            else:
                # Update scheduler with failure count but not quarantined yet
                effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
                self.scheduler.update_drive_state(
                    drive_letter=operation.drive_letter,
                    state="normal",  # Still normal until quarantine threshold
                    interval_sec=drive_state.config.interval,
                    effective_interval_sec=effective_interval,
                    last_ok_at=drive_state.last_operation,
                    next_due_at=None,
                    failure_count=drive_state.consecutive_tick_failures,
                    type=drive_state.config.type
                )
                
                # Log quarantine transition
                if self.log_callback and hasattr(self.log_callback, 'log_quarantine_transition'):
                    self.log_callback.log_quarantine_transition(operation.drive_letter, 
                                                              f"Failed {drive_state.consecutive_tick_failures} ticks",
                                                              drive_state.consecutive_tick_failures,
                                                              self.config.error_quarantine_sec)

        # Log the operation
        if self.log_callback and final_result:
            self.log_callback(operation, final_result, current_time)
    
    def _perform_io_operation(self, drive_state: DriveState, operation: ScheduledOperation) -> IOResult:
        """Perform the actual I/O operation via the I/O manager."""
        if not self.io_manager:
            logger.error(f"No I/O manager available for drive {operation.drive_letter}")
            return IOResult(
                result_code=ResultCode.ERROR,
                duration_ms=0.0,
                details="I/O manager not available"
            )

        logger.debug(f"Performing {operation.operation_type.value} on {operation.drive_letter}")
        return self.io_manager.perform_operation(drive_state, operation)
    
    def get_full_status_snapshot(self) -> Dict[str, Any]:
        """Get full status snapshot for all drives (no change filtering).

        Intended for initial UI population to avoid empty tables when no changes
        are detected yet by the incremental snapshot mechanism.
        """
        snapshot = {
            "drives": {},
            "next_operation": None,
            "policy_reasons": self.policy_state.reasons,
            "upcoming_operations": []
        }

        # Next operation
        if self.scheduled_operations:
            next_op = self.scheduled_operations[0]
            snapshot["next_operation"] = {
                "drive": next_op.drive_letter,
                "time": next_op.operation_time,
                "type": next_op.operation_type.value
            }

        # PHASE 3: Read all drives from scheduler
        all_timing_states = self.scheduler.get_all_drive_states()
        for letter, timing in all_timing_states.items():
            drive_state = self._build_drive_state_from_scheduler(letter)
            if not drive_state:
                continue
            drive_snapshot = self._get_drive_status_snapshot(letter, drive_state)
            # Add status field to match main snapshot format
            drive_snapshot["status"] = drive_state.status.value
            snapshot["drives"][letter] = drive_snapshot
            # Also update cache so subsequent incremental snapshots work as expected
            self._update_drive_state_cache(letter, drive_state)

        # Generate upcoming operations preview
        current_time = time.monotonic()
        snapshot["upcoming_operations"] = self._generate_upcoming_preview(current_time, target_count=5)

        return snapshot

    def _should_emit_status_update(self, current_time: float) -> bool:
        """Check if status update should be emitted (either time-based or state changed)."""
        # Always emit if enough time has passed
        if current_time - self._last_status_emit >= self._status_emit_interval:
            return True

        # Check if drive states have changed
        current_hash = self._compute_drive_states_hash()
        if current_hash != self._last_drive_states_hash:
            self._last_drive_states_hash = current_hash
            return True

        return False

    def _compute_drive_states_hash(self) -> str:
        """Compute a hash of current drive states for change detection."""
        import hashlib

        # PHASE 3: Read from scheduler
        state_parts = []
        all_timing_states = self.scheduler.get_all_drive_states()
        for letter, timing in sorted(all_timing_states.items()):
            state_parts.append(f"{letter}:{timing.enabled}:{timing.status.value}:{timing.next_due_at}")

        state_string = "|".join(state_parts)
        return hashlib.md5(state_string.encode()).hexdigest()

    def _format_drive_size(self, drive_letter: str, drive_info: Dict[str, Any]) -> str:
        """Format drive size for display."""
        try:
            # Try to get disk usage information using psutil
            import psutil
            drive_path = Path(f"{drive_letter}:\\")
            if drive_path.exists():
                usage = psutil.disk_usage(str(drive_path))
                total_gb = usage.total // (1024**3)
                return f"{total_gb:.0f} GB"
            else:
                return "Unknown"
        except (ImportError, Exception):
            return "Unknown"

    def _has_drive_state_changed(self, letter: str, drive_state: DriveState) -> bool:
        """Check if drive state has changed since last update."""
        if letter not in self._drive_state_cache:
            return True
        
        cached = self._drive_state_cache[letter]
        return (
            cached.get("enabled") != drive_state.enabled or
            cached.get("status") != drive_state.status.value or
            cached.get("next_due") != (self.scheduler.get_timing_state(letter).next_due_at if self.scheduler.get_timing_state(letter) else None) or
            cached.get("consecutive_tick_failures") != drive_state.consecutive_tick_failures or
            cached.get("last_results_count") != len(drive_state.last_results)
        )

    def _get_drive_status_snapshot(self, letter: str, drive_state: DriveState) -> Dict[str, Any]:
        """Get status snapshot for a single drive."""
        # Convert last_results from IOResult objects to summary format for UI
        last_results_summary = []
        for io_result in drive_state.last_results[-3:]:  # Last 3 results
            last_results_summary.append({
                "result_code": io_result.result_code.value,
                "duration_ms": io_result.duration_ms,
                "details": io_result.details[:50] + "..." if len(io_result.details) > 50 else io_result.details
            })

        # Get drive information from IOManager (with caching)
        drive_info = self._get_cached_drive_info(letter)

        # Get timing state from scheduler for accurate next_due_at
        timing_state = self.scheduler.get_timing_state(letter)
        
        return {
            "enabled": drive_state.enabled,
            "status": drive_state.status.value,
            "type": drive_state.config.type,
            "interval": drive_state.config.interval,
            "next_due_at": timing_state.next_due_at if timing_state else None,  # GUI expects next_due_at
            "next_due": timing_state.next_due_at if timing_state else None,  # Legacy compatibility
            "last_ok_at": drive_state.last_operation,  # GUI expects last_ok_at
            "last_operation": drive_state.last_operation,  # Legacy compatibility
            "quarantine_release_at": drive_state.quarantine_until,  # GUI expects this for quarantine countdown
            "reason": drive_state.pause_reason,  # GUI expects this for pause reason display
            "last_results": last_results_summary,
            "consecutive_tick_failures": drive_state.consecutive_tick_failures,
            "last_tick_attempts": drive_state.last_tick_attempts,
            "label": drive_info["label"],
            "size": drive_info["size"],
            "drive_letter": letter  # Include drive letter for reference
        }

    def _get_cached_drive_info(self, letter: str) -> Dict[str, Any]:
        """Get drive information with caching to reduce I/O calls."""
        # Normalize drive letter to ensure consistency
        from app_utils import normalize_drive_letter
        letter = normalize_drive_letter(letter)
        
        # Check cache first
        if letter in self._drive_info_cache:
            cached_info = self._drive_info_cache[letter]
            # Cache for 14 seconds to avoid excessive I/O calls
            if time.time() - cached_info.get("cache_time", 0) < 14:
                logger.debug(f"Using cached drive info for {letter}: {cached_info['info']}")
                return cached_info["info"]
        
        # Get fresh drive information
        drive_info = {}
        if self.io_manager:
            try:
                # Strip colon from drive letter for get_drive_info
                drive_letter_clean = letter.rstrip(':')
                logger.debug(f"Fetching fresh drive info for {letter} (cleaned: {drive_letter_clean})")
                io_drive_info = self.io_manager.get_drive_info(drive_letter_clean)
                
                if io_drive_info.get("accessible", False):
                    volume_info = io_drive_info.get("volume_info", {})
                    drive_info = {
                        "label": volume_info.get("volume_name", "Local Disk"),
                        "size": self._format_drive_size(drive_letter_clean, io_drive_info)
                    }
                    logger.debug(f"Drive {letter} info retrieved: label={drive_info['label']}, size={drive_info['size']}")
                else:
                    drive_info = {
                        "label": "Local Disk",
                        "size": "Unknown"
                    }
                    logger.warning(f"Drive {letter} not accessible: {io_drive_info.get('error', 'Unknown error')}")
            except Exception as e:
                logger.error(f"Failed to get drive info for {letter}: {e}", exc_info=True)
                drive_info = {
                    "label": "Local Disk",
                    "size": "Unknown"
                }
        else:
            logger.error(f"No I/O manager available to get drive info for {letter}")
            drive_info = {
                "label": "Local Disk",
                "size": "Unknown"
            }
        
        # Cache the result
        self._drive_info_cache[letter] = {
            "info": drive_info,
            "cache_time": time.time()
        }
        
        return drive_info

    def _update_drive_state_cache(self, letter: str, drive_state: DriveState):
        """Update the drive state cache."""
        self._drive_state_cache[letter] = {
            "enabled": drive_state.enabled,
            "status": drive_state.status.value,
            "next_due": self.scheduler.get_timing_state(letter).next_due_at if self.scheduler.get_timing_state(letter) else None,
            "consecutive_tick_failures": drive_state.consecutive_tick_failures,
            "last_results_count": len(drive_state.last_results)
        }

    def _update_policy_state_cached(self, current_time: float):
        """Update policy state with caching to reduce redundant checks."""
        # Only update policy state if cache has expired
        if (current_time - self._policy_cache_time) >= self._policy_cache_interval:
            self._update_policy_state()
            self._policy_cache_time = current_time

    def _plan_operations_cached(self, current_time: float):
        """Plan operations with caching to reduce redundant planning."""
        # PHASE 3: Read from scheduler
        all_timing_states = self.scheduler.get_all_drive_states()
        needs_planning = any(
            timing.enabled and timing.next_due_at is None
            for timing in all_timing_states.values()
        )
        
        if needs_planning or (current_time - self._last_plan_time) >= self._plan_cache_interval:
            self._plan_operations(current_time)
            self._last_plan_time = current_time

    def _log_next_due_countdowns(self, current_time: float):
        """Log next due countdowns to CLI (optimized)."""
        try:
            # PHASE 3: Read from scheduler
            all_timing_states = self.scheduler.get_all_drive_states()
            parts = []
            for letter in sorted(all_timing_states.keys()):
                timing = all_timing_states[letter]
                if timing.next_due_at is not None:
                    secs = max(0, int(timing.next_due_at - current_time))
                    parts.append(f"{letter}:+{secs}s")
                else:
                    parts.append(f"{letter}:—")
            if parts:
                logger.info("Next due: " + ", ".join(parts))
        except Exception:
            pass

    def set_global_pause(self, paused: bool):
        """Set global pause state.
        
        DEPRECATED: Use pause_all_drives() or resume_all_drives() instead.
        This method is kept for backward compatibility but may not properly
        update all scheduler states. New code should use the individual
        drive-based methods which ensure consistent state updates.
        """
        old_paused = self.policy_state.global_pause
        self.policy_state.global_pause = paused

        if paused and not old_paused:
            # PHASE 3: Read from scheduler
            all_timing_states = self.scheduler.get_all_drive_states()
            for letter, timing in all_timing_states.items():
                if (timing.enabled and 
                    timing.status != DriveStatus.QUARANTINE and
                    timing.pause_reason != "user"):
                    self.scheduler.set_drive_status(letter, DriveStatus.PAUSED, "global")
        elif not paused and old_paused:
            # PHASE 3: Read from scheduler
            all_timing_states = self.scheduler.get_all_drive_states()
            for letter, timing in all_timing_states.items():
                if timing.status == DriveStatus.PAUSED and timing.pause_reason == "global":
                    drive_state = self._build_drive_state_from_scheduler(letter)
                    if not drive_state:
                        continue
                    drive_state.status = DriveStatus.ACTIVE
                    drive_state.pause_reason = None
                    # Update scheduler
                    self.scheduler.update_drive_state(
                        drive_letter=letter,
                        state="normal",
                        reason="normal",
                        interval_sec=drive_state.config.interval,
                        last_ok_at=drive_state.last_operation,
                        next_due_at=None,
                        failure_count=drive_state.consecutive_tick_failures,
                        type=drive_state.config.type
                    )
                    self.scheduler.set_drive_status(letter, DriveStatus.ACTIVE, None)

        # Force immediate status update when pause state changes
        if self.status_callback:
            self.status_callback(self.get_full_status_snapshot())

        logger.info(f"Global pause set to {paused}")

    def pause_drive(self, letter: str):
        """Pause a specific drive."""
        # PHASE 3: Read from scheduler
        drive_state = self._build_drive_state_from_scheduler(letter)
        if drive_state:
            if drive_state.status != DriveStatus.QUARANTINE:
                drive_state.status = DriveStatus.PAUSED
                drive_state.pause_reason = "user"  # Track that this was user-initiated

                # DUAL-WRITE Phase 2: Update old scheduler method
                effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
                self.scheduler.update_drive_state(
                    drive_letter=letter,
                    state="paused",
                    reason="user",
                    interval_sec=drive_state.config.interval,
                    effective_interval_sec=effective_interval,
                    last_ok_at=drive_state.last_operation,
                    next_due_at=None,  # Clear next_due_at - drive is paused
                    failure_count=drive_state.consecutive_tick_failures,
                    type=drive_state.config.type
                )
                
                # DUAL-WRITE Phase 2: Update new scheduler method
                self.scheduler.set_drive_status(
                    drive_letter=letter,
                    status=DriveStatus.PAUSED,
                    pause_reason="user"
                )

                # Clear scheduled operations for this drive
                self.scheduled_operations = [
                    op for op in self.scheduled_operations 
                    if op.drive_letter != letter
                ]

                logger.info(f"Drive {letter} paused and scheduled operations cleared")
                # Force immediate status update
                if self.status_callback:
                    self.status_callback(self.get_full_status_snapshot())
            else:
                logger.warning(f"Cannot pause quarantined drive {letter}")
        else:
            logger.error(f"Drive {letter} not found")

    def resume_drive(self, letter: str):
        """Resume a specific drive."""
        # PHASE 3: Read from scheduler
        drive_state = self._build_drive_state_from_scheduler(letter)
        if drive_state:
            if drive_state.status == DriveStatus.PAUSED:
                drive_state.status = DriveStatus.ACTIVE
                drive_state.pause_reason = None  # Clear pause reason

                # DUAL-WRITE Phase 2: Update old scheduler method
                effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
                self.scheduler.update_drive_state(
                    drive_letter=letter,
                    state="normal",
                    interval_sec=drive_state.config.interval,
                    effective_interval_sec=effective_interval,
                    last_ok_at=drive_state.last_operation,
                    next_due_at=None,  # Clear next_due_at to trigger replanning
                    failure_count=drive_state.consecutive_tick_failures,
                    type=drive_state.config.type
                )
                
                # DUAL-WRITE Phase 2: Update new scheduler method
                self.scheduler.set_drive_status(
                    drive_letter=letter,
                    status=DriveStatus.ACTIVE,
                    pause_reason=None
                )

                logger.info(f"Drive {letter} resumed")
                # Force immediate status update
                if self.status_callback:
                    self.status_callback(self.get_full_status_snapshot())
            else:
                logger.warning(f"Drive {letter} is not paused (status: {drive_state.status.value})")
        else:
            logger.error(f"Drive {letter} not found")

    def pause_all_drives(self):
        """Pause all enabled drives by calling pause_selected_drives."""
        # PHASE 3: Read from scheduler
        all_active_drives = [
            letter for letter, timing in self.scheduler.get_all_drive_states().items()
            if timing.enabled and timing.status not in [DriveStatus.PAUSED, DriveStatus.QUARANTINE]
        ]
        
        # Use the same logic as pause_selected_drives
        return self.pause_selected_drives(all_active_drives)

    def resume_all_drives(self):
        """Resume ALL paused drives by calling resume_selected_drives."""
        # PHASE 3: Read from scheduler
        all_paused_drives = [
            letter for letter, timing in self.scheduler.get_all_drive_states().items()
            if timing.status == DriveStatus.PAUSED
        ]
        
        # Use the same logic as resume_selected_drives
        return self.resume_selected_drives(all_paused_drives)

    def pause_selected_drives(self, drive_letters: List[str]):
        """Pause selected drives."""
        paused_count = 0
        paused_letters = []
        
        for letter in drive_letters:
            # PHASE 3: Read from scheduler
            timing = self.scheduler.get_timing_state(letter)
            if timing and timing.enabled and timing.status not in [DriveStatus.PAUSED, DriveStatus.QUARANTINE]:
                self.pause_drive(letter)
                paused_count += 1
                paused_letters.append(letter)
        
        # Clear scheduled operations for paused drives
        self.scheduled_operations = [
            op for op in self.scheduled_operations 
            if op.drive_letter not in paused_letters
        ]
        
        return paused_count

    def resume_selected_drives(self, drive_letters: List[str]):
        """Resume selected drives."""
        resumed_count = 0
        for letter in drive_letters:
            # PHASE 3: Read from scheduler
            timing = self.scheduler.get_timing_state(letter)
            if timing and timing.status == DriveStatus.PAUSED:
                self.resume_drive(letter)
                resumed_count += 1
        return resumed_count
    
    def set_drive_config(self, letter: str, enabled: bool, interval: int,
                        drive_type: str, ping_dir: Optional[str], save_config: bool = True):
        """Update drive configuration."""
        # PHASE 3: Read from scheduler
        drive_state = self._build_drive_state_from_scheduler(letter)
        if drive_state:
            # Capture old interval BEFORE modifying config
            old_interval = drive_state.config.interval

            drive_state.config.enabled = enabled
            drive_state.config.interval = interval
            drive_state.config.type = drive_type
            drive_state.config.ping_dir = ping_dir
            drive_state.enabled = enabled

            # BUG FIX: Calculate effective interval BEFORE writing to scheduler
            effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
            
            # Update status based on enabled state and clamping/capping
            if enabled:
                # When enabling, set to ACTIVE (or CLAMPED/HDD_CAPPED if applicable)
                if status_reason == "CLAMPED":
                    drive_state.status = DriveStatus.CLAMPED
                elif status_reason == "HDD_CAPPED":
                    drive_state.status = DriveStatus.HDD_CAPPED
                else:
                    # No clamping/capping - drive is ACTIVE
                    drive_state.status = DriveStatus.ACTIVE
            else:
                # When disabling, set to OFFLINE
                drive_state.status = DriveStatus.OFFLINE

            # Set next_due_at for newly enabled ACTIVE drives
            next_due_at = None
            if enabled and drive_state.status == DriveStatus.ACTIVE:
                current_time = self.scheduler.clock.monotonic()
                next_due_at = current_time + drive_state.config.interval
            
            # DUAL-WRITE Phase 2: Update old scheduler method
            self.scheduler.update_drive_state(
                drive_letter=letter,
                state=drive_state.status.value,
                next_due_at=next_due_at,
                interval_sec=drive_state.config.interval,  # Now contains effective value
                effective_interval_sec=effective_interval,
                type=drive_state.config.type,
                status_reason=status_reason
            )
            
            # DUAL-WRITE Phase 2: Update new scheduler config method with EFFECTIVE interval
            self.scheduler.set_drive_config(
                drive_letter=letter,
                enabled=enabled,
                interval_sec=drive_state.config.interval,  # Use effective, not user's original
                drive_type=drive_type,
                ping_dir=ping_dir
            )
            # Update status in scheduler
            self.scheduler.set_drive_status(
                drive_letter=letter,
                status=drive_state.status,
                pause_reason=drive_state.pause_reason
            )

            # Only reset timing architecture if interval changed
            if interval != old_interval:
                # Timing state is now managed by scheduler
                drive_state.last_operation = None  # Force fresh start with new interval
                logger.debug(f"Drive {letter} interval changed {old_interval}→{interval}s, reset timing state")
            else:
                logger.debug(f"Drive {letter} config updated, preserving timing state")
            
            # Update in-memory configuration with EFFECTIVE interval
            if self.config_manager and letter in self.config.per_drive:
                self.config.per_drive[letter].enabled = enabled
                self.config.per_drive[letter].interval = drive_state.config.interval  # Use effective, not user's original
                self.config.per_drive[letter].type = drive_type
                self.config.per_drive[letter].ping_dir = ping_dir
                
                # Save to disk only if explicitly requested
                if save_config:
                    self.config_manager.save_config(self.config)
                    logger.debug(f"Updated and saved config for drive {letter}")
                else:
                    logger.debug(f"Updated in-memory config for drive {letter} (not saved to disk)")
        else:
            logger.error(f"Drive {letter} not found")

    def clear_drive_quarantine(self, letter: str):
        """Clear quarantine status for a specific drive."""
        # PHASE 3: Read from scheduler
        drive_state = self._build_drive_state_from_scheduler(letter)
        if drive_state:
            drive_state.quarantine_until = None
            drive_state.consecutive_tick_failures = 0
            drive_state.status = DriveStatus.ACTIVE

            # Update scheduler
            effective_interval, status_reason = self.jitter_planner._get_effective_interval(drive_state)
            self.scheduler.update_drive_state(
                drive_letter=letter,
                state="normal",
                interval_sec=drive_state.config.interval,
                effective_interval_sec=effective_interval,
                interval_display=drive_state.config.interval,
                last_ok_at=drive_state.last_operation,
                next_due_at=None,
                failure_count=0,
                type=drive_state.config.type,
                quarantine_count=0  # Reset quarantine counter on manual clear
            )
            # PHASE 3: Also use new scheduler method
            self.scheduler.set_drive_status(letter, DriveStatus.ACTIVE, None)            
            logger.info(f"Cleared quarantine for drive {letter}")
        else:
            logger.error(f"Drive {letter} not found")

    def rescan_drives(self, mode: str = "quick") -> bool:
        """Rescan for available drives and update configuration.
        
        Args:
            mode: "quick" (config drives only) or "full" (E-Z scan)
        """
        try:
            available_drives = self._scan_and_update_drives(mode=mode)
            
            # Recalculate effective intervals for all drives after rescan
            self._recalculate_all_effective_intervals()
            
            logger.info(f"Drive rescan completed: {len(available_drives)} drives found")
            return True
        except Exception as e:
            logger.error(f"Error during drive rescan: {e}")
            return False
    
    def full_rescan_clear_all(self) -> bool:
        """Clear all existing drives and perform a complete fresh scan.
        
        This method:
        1. Clears all existing drive configurations
        2. Clears scheduler state
        3. Performs a fresh full scan
        4. Re-initializes all drive states
        
        Returns:
            bool: True if successful, False if error occurred
        """
        try:
            logger.info("Starting full rescan with complete drive state reset")
            
            # Clear all existing drive configurations
            self.config.per_drive.clear()
            logger.info("Cleared all existing drive configurations")
            
            # Clear scheduler state
            self.scheduler._drive_timing.clear()
            self.scheduler._version = 0
            self.scheduler._snapshot = None
            logger.info("Cleared scheduler state")
            
            # Clear scheduled operations
            self.scheduled_operations.clear()
            logger.info("Cleared scheduled operations")
            
            # Perform fresh full scan
            available_drives = self._scan_and_update_drives(mode="full")
            logger.info(f"Fresh scan completed: {len(available_drives)} drives discovered")
            
            # Re-initialize drive states
            self._initialize_drive_states()
            logger.info("Re-initialized all drive states")
            
            # Recalculate effective intervals
            self._recalculate_all_effective_intervals()
            logger.info("Recalculated effective intervals")
            
            logger.info(f"Full rescan completed successfully: {len(available_drives)} drives configured")
            return True
            
        except Exception as e:
            logger.error(f"Error during full rescan: {e}")
            return False
    
    def ping_drive_now(self, letter: str) -> bool:
        """Perform immediate ping: write-if-missing, then read and verify without shifting schedule."""
        # PHASE 3: Read from scheduler
        drive_state = self._build_drive_state_from_scheduler(letter)
        if not drive_state:
            return False
        
        if not drive_state.enabled:
            return False
        
        if not self.io_manager:
            return False
        
        try:
            # Resolve ping directory and file
            ping_dir = self.io_manager.get_ping_directory(letter, drive_state.config.ping_dir)
            if not self.io_manager.ensure_ping_directory(ping_dir):
                return False
            ping_file = ping_dir / "drive_revenant"
            
            # If missing, perform a write operation (one-shot)
            if not ping_file.exists():
                write_op = ScheduledOperation(
                    drive_letter=letter,
                    operation_time=time.monotonic(),
                    operation_type=OperationType.WRITE,
                    offset_ms=0.0,
                    jitter_reason="manual"
                )
                write_res = self.io_manager.perform_operation(drive_state, write_op)
                if write_res.result_code != ResultCode.OK and write_res.result_code != ResultCode.PARTIAL_FLUSH:
                    return False
            
            # Always perform a read operation (one-shot)
            read_op = ScheduledOperation(
                drive_letter=letter,
                operation_time=time.monotonic(),
                operation_type=OperationType.READ,
                offset_ms=0.0,
                jitter_reason="manual"
            )
            read_res = self.io_manager.perform_operation(drive_state, read_op)
            if read_res.result_code != ResultCode.OK:
                return False
            
            # Verify file content non-empty
            try:
                content = ping_file.read_text(encoding='utf-8')
            except Exception:
                return False
            if not content.strip():
                return False
            
            # Log user-initiated ping
            if self.logging_manager:
                self.logging_manager.log_system_event("PING_NOW", f"User pinged {letter}")
            
            return True
        except Exception:
            return False
