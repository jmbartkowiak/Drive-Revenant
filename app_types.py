# app_types.py
# Version: 2.0.3
# Shared type definitions for Drive Revenant to avoid circular imports, including centralized scheduling models.
#
# Version History:
# 1.2.0 - 2025-10-10: Fixed DriveSnapshot constructor signature for GUI integration
#                    - Added 'type' field to DriveSnapshot for drive type display
#                    - Updated test compatibility for DriveSnapshot usage
# 1.1.0 - Previous version with centralized scheduling models

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

class OperationType(Enum):
    READ = "read"
    WRITE = "write"

class ResultCode(Enum):
    OK = "OK"
    PARTIAL_FLUSH = "PARTIAL_FLUSH"
    SKIP_LOCKED = "SKIP_LOCKED"
    QUARANTINE = "QUARANTINE"
    ERROR = "ERROR"

class DriveStatus(Enum):
    ACTIVE = "Active"
    PAUSED = "Paused"
    OFFLINE = "Offline"
    ERROR = "Error"
    QUARANTINE = "Quarantine"
    CLAMPED = "Clamped"
    HDD_CAPPED = "HDD-capped"

@dataclass
class DriveConfig:
    """Configuration for a single drive with tracking fields."""
    enabled: bool = False
    interval: int = 180  # seconds
    type: str = "Unknown"  # HDD, SSD, RAM-disk, Unknown
    ping_dir: Optional[str] = None  # None means use default X:\.drive_revenant\
    volume_guid: Optional[str] = None  # Volume GUID for tracking across letter changes
    last_seen_timestamp: Optional[float] = None  # Unix timestamp when drive was last accessible
    total_size_bytes: Optional[int] = None  # Total drive size for identification

@dataclass
class DriveTimingState:
    """Complete drive state owned by Scheduler - single source of truth."""
    # Timing (existing)
    next_due_at: Optional[float] = None  # Monotonic time of next scheduled operation
    last_ok_at: Optional[float] = None   # Monotonic time of last successful operation
    effective_interval_sec: float = 180.0  # Effective interval after HDD/clamp adjustments
    status_reason: Optional[str] = None  # HDD_CAPPED, CLAMPED, etc.
    
    # Configuration (NEW - moved from DriveConfig)
    enabled: bool = False
    interval_sec: int = 180  # User-configured interval
    type: str = "Unknown"  # HDD, SSD, etc.
    ping_dir: Optional[str] = None
    
    # Status (NEW - moved from DriveState)
    status: DriveStatus = DriveStatus.OFFLINE
    pause_reason: Optional[str] = None  # "user", "battery", "idle"
    
    # I/O tracking (NEW - moved from DriveState)
    last_operation: Optional[float] = None
    quarantine_until: Optional[float] = None
    measured_speed: Optional[float] = None
    volume_guid: Optional[str] = None
    last_results: List = field(default_factory=list)
    
    # Telemetry (NEW - moved from DriveState)
    late_slack_used: bool = False
    hdd_guard_violation: bool = False
    consecutive_tick_failures: int = 0
    last_tick_attempts: int = 0
    tick_counter: int = 0
    quarantine_count: int = 0  # Number of times quarantined (0-11), resets on success

@dataclass
class DriveState:
    """Runtime state for a drive - I/O and error tracking only."""
    letter: str
    config: DriveConfig
    enabled: bool = False
    status: DriveStatus = DriveStatus.OFFLINE
    # I/O state only - timing moved to Scheduler
    last_operation: Optional[float] = None  # monotonic time
    quarantine_until: Optional[float] = None
    measured_speed: Optional[float] = None  # MB/s
    volume_guid: Optional[str] = None
    last_results: List = field(default_factory=list)  # Will be IOResult objects
    # Telemetry flags for HDD guard/jitter
    late_slack_used: bool = False
    hdd_guard_violation: bool = False
    # Tick-level failure tracking
    consecutive_tick_failures: int = 0
    last_tick_attempts: int = 0  # For telemetry
    tick_counter: int = 0  # For tick counting
    # Pause reason tracking
    pause_reason: Optional[str] = None  # "user", "battery", "idle", or None

@dataclass(frozen=True)
class DriveSnapshot:
    """Immutable snapshot of drive state for GUI consumption."""
    state: str  # "normal" | "paused" | "quarantined"
    reason: Optional[str]  # "battery" | "idle" | "user" | "error" | null
    interval_sec: int  # Configured interval
    effective_interval_sec: float  # Actual interval being used (after capping/clamping)
    interval_display: float  # User-configured interval for countdown display
    last_ok_at: Optional[float]  # monotonic time
    next_due_at: Optional[float]  # monotonic time
    failure_count: int
    quarantine_release_at: Optional[float]  # monotonic time
    type: str  # "HDD" | "SSD" | "Removable" | "Network" | "RAM-disk" | "CD-ROM" | "Unknown"
    consecutive_tick_failures: int = 0  # Number of consecutive tick failures
    last_tick_attempts: int = 0  # Number of attempts in last tick
    tick_counter: int = 0  # For tick counting

@dataclass(frozen=True)
class StatusSnapshot:
    """Immutable snapshot of all drive states for GUI consumption."""
    generated_at: float  # monotonic time
    version: int
    drives: Dict[str, DriveSnapshot]

@dataclass
class ScheduledOperation:
    """A scheduled I/O operation."""
    drive_letter: str
    operation_time: float  # monotonic
    operation_type: OperationType
    offset_ms: float
    jitter_reason: str  # "in_window", "expanded", "overflow"
    # Telemetry fields for same-tick packing
    pack_size: Optional[int] = None  # Number of drives in same-tick set
    tie_epoch: Optional[str] = None  # YYYY-MM-DD for tie-breaking
    tie_rank: Optional[int] = None  # u64 rank for tie-breaking
    tie_seed64: Optional[str] = None  # hex seed for tie-breaking

@dataclass
class PolicyState:
    """Current policy state affecting scheduling."""
    global_pause: bool = False
    battery_pause: bool = False
    idle_pause: bool = False
    reasons: List[str] = field(default_factory=list)
