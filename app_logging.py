# app_logging.py
# Version: 1.0.4
# Logging system for Drive Revenant with human-readable log rotation, NDJSON stream,
# event formatting with half-second indicators, and structured telemetry.

import json
import time
import logging
import logging.handlers
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime, timezone
from dataclasses import asdict
import threading

from app_types import ScheduledOperation, ResultCode, DriveState

if TYPE_CHECKING:
    from app_io import IOResult

logger = logging.getLogger(__name__)


class SizeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Custom rotating file handler that uses numbered rotation: Log_current1.txt to Log_current5.txt."""

    def doRollover(self):
        """Perform rollover with numbered file naming scheme."""
        # Close current stream if open
        if self.stream:
            self.stream.close()
            self.stream = None

        base, ext = os.path.splitext(self.baseFilename)   # ".../Log_current1", ".txt"

        # Parse base to get the 'Log_current' root; we always target index 1
        # e.g. base == ".../Log_current1" -> root == ".../Log_current"
        if base.endswith("1"):
            root = base[:-1]
        else:
            # Defensive: if misconfigured, still compute a sensible root and proceed
            root = base.rstrip("0123456789")

        max_keep = self.backupCount if self.backupCount > 0 else 5

        # Delete the max file if present (Log_current{max_keep}.txt)
        last = f"{root}{max_keep}{ext}"
        if os.path.exists(last):
            os.remove(last)

        # Shift N-1 -> N (descending)
        for i in range(max_keep - 1, 0, -1):
            src = f"{root}{i}{ext}"
            dst = f"{root}{i + 1}{ext}"
            if os.path.exists(src):
                if os.path.exists(dst):
                    os.remove(dst)
                os.rename(src, dst)

        # After shifting, reopen Log_current1.txt fresh
        self.mode = "w"
        self.stream = self._open()

class EventLogger:
    """Handles structured event logging with NDJSON output."""
    
    def __init__(self, log_dir: Path, config):
        self.log_dir = log_dir
        self.config = config
        self.ndjson_enabled = config.log_ndjson
        
        # NDJSON file
        self.ndjson_file: Optional[Path] = None
        self.ndjson_lock = threading.Lock()
        
        if self.ndjson_enabled:
            self.ndjson_file = self.log_dir / "events.ndjson"
    
    def log_operation(self, operation: ScheduledOperation, io_result: "IOResult", 
                     drive_state: DriveState, current_time: float):
        """Log an I/O operation event."""
        if not self.ndjson_enabled:
            return
        
        # Calculate wall time
        wall_time = datetime.now(timezone.utc)
        
        # Create event record
        event = {
            "timestamp": wall_time.isoformat(),
            "monotonic_time": current_time,
            "event_type": "io_operation",
            "drive_letter": operation.drive_letter,
            "operation_type": operation.operation_type.value,
            "result_code": io_result.result_code.value,
            "duration_s": round(io_result.duration_ms / 1000.0, 3),
            "offset_s": round(io_result.offset_ms / 1000.0, 3),
            "jitter_reason": io_result.jitter_reason,
            "details": io_result.details,
            "drive_type": drive_state.config.type,
            "interval_sec": drive_state.config.interval,
            "tick_counter": drive_state.tick_counter,
            "attempt_count": getattr(drive_state, "last_tick_attempts", 1),
            "failure_class": getattr(io_result, "failure_class", None),
            "tick_failure_count": getattr(drive_state, "consecutive_tick_failures", 0)
        }
        
        # Add tie-break information
        if operation.tie_epoch is not None:
            event["tie_epoch"] = operation.tie_epoch
        if operation.tie_rank is not None:
            event["tie_rank"] = operation.tie_rank
        if operation.tie_seed64 is not None:
            event["tie_seed64"] = operation.tie_seed64

        # Add pack size for same-tick operations
        if operation.pack_size is not None:
            event["pack_size"] = operation.pack_size

        # Add HDD guard information if applicable
        if drive_state.config.type == "HDD":
            event["hdd_guard"] = True
            event["late_slack_used"] = getattr(drive_state, "late_slack_used", False)
            event["hdd_guard_violation"] = getattr(drive_state, "hdd_guard_violation", False)
        
        self._write_ndjson_event(event)
    
    def log_retry_attempt(self, drive_letter: str, attempt: int, failure_class: str, backoff_ms: int):
        """Log a retry attempt to the human-readable log."""
        logger.info(f"Drive {drive_letter} retry attempt {attempt} after {failure_class} failure, backoff {backoff_ms}ms")
    
    def log_quarantine_transition(self, drive_letter: str, reason: str, tick_failures: int, quarantine_sec: int):
        """Log quarantine entry/exit to both human and NDJSON logs."""
        wall_time = datetime.now(timezone.utc)
        
        # Human log
        logger.warning(f"Drive {drive_letter} entered quarantine: {reason} (failed {tick_failures} ticks, quarantine {quarantine_sec}s)")
        
        # NDJSON log
        if self.ndjson_enabled:
            event = {
                "timestamp": wall_time.isoformat(),
                "event_type": "quarantine_transition",
                "drive_letter": drive_letter,
                "reason": reason,
                "tick_failures": tick_failures,
                "quarantine_sec": quarantine_sec
            }
            self._write_ndjson_event(event)
    
    def log_scheduler_event(self, event_type: str, details: Dict[str, Any], current_time: float):
        """Log a scheduler event."""
        if not self.ndjson_enabled:
            return

        wall_time = datetime.now(timezone.utc)

        event = {
            "timestamp": wall_time.isoformat(),
            "monotonic_time": current_time,
            "event_type": "scheduler",
            "scheduler_event": event_type,
            **details
        }

        self._write_ndjson_event(event)
    
    def log_policy_change(self, policy_type: str, old_value: Any, new_value: Any, current_time: float):
        """Log a policy change event."""
        if not self.ndjson_enabled:
            return
        
        wall_time = datetime.now(timezone.utc)
        
        event = {
            "timestamp": wall_time.isoformat(),
            "monotonic_time": current_time,
            "event_type": "policy_change",
            "policy_type": policy_type,
            "old_value": old_value,
            "new_value": new_value
        }
        
        self._write_ndjson_event(event)
    
    def log_config_change(self, change_type: str, details: Dict[str, Any], current_time: float):
        """Log a configuration change event."""
        if not self.ndjson_enabled:
            return
        
        wall_time = datetime.now(timezone.utc)
        
        event = {
            "timestamp": wall_time.isoformat(),
            "monotonic_time": current_time,
            "event_type": "config_change",
            "change_type": change_type,
            **details
        }
        
        self._write_ndjson_event(event)
    
    def _write_ndjson_event(self, event: Dict[str, Any]):
        """Write an event to the NDJSON file."""
        if not self.ndjson_file:
            return
        
        try:
            with self.ndjson_lock:
                with open(self.ndjson_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(event, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.error(f"Failed to write NDJSON event: {e}")

class HumanLogger:
    """Handles human-readable log rotation and formatting."""
    
    def __init__(self, log_dir: Path, config):
        self.log_dir = log_dir
        self.config = config
        self.max_size_kb = config.log_max_kb
        self.history_count = config.log_history_count
        
        # Ensure logs directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Current/active file is ALWAYS "1"
        self.current_log = self.log_dir / "Log_current1.txt"
        self.log_lock = threading.Lock()
        
        # Initialize logging
        self._setup_logging()
    
    def _setup_logging(self):
        """Set up the logging system."""
        # Create formatter
        self.formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Create custom file handler that properly rotates logs
        file_handler = SizeRotatingFileHandler(
            self.current_log,
            maxBytes=self.max_size_kb * 1024,
            backupCount=self.history_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(self.formatter)
        file_handler.setLevel(logging.INFO)

        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(self.formatter)
        console_handler.setLevel(logging.INFO)

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        
        # Clear existing handlers to prevent duplication
        root_logger.handlers.clear()
        
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

        # Configure our logger
        logger.setLevel(logging.INFO)
    
    def format_operation_log(self, operation: ScheduledOperation, io_result: "IOResult",
                           drive_state: DriveState) -> str:
        """Format an operation for human-readable log."""
        # Get half-second indicator
        wall_time = datetime.now()
        half_second = "5" if int(wall_time.timestamp() * 2) % 2 else "0"
        
        # Format timestamp with half-second indicator
        timestamp = wall_time.strftime("%Y-%m-%d %H:%M:%S")
        timestamp_with_half = f"{timestamp}.{half_second}"
        
        # Format operation details
        op_type = operation.operation_type.value.upper()
        result = io_result.result_code.value
        duration = f"{io_result.duration_ms/1000.0:.3f}s"
        
        # Format offset and jitter
        offset_str = f"{io_result.offset_ms/1000.0:+.3f}s" if io_result.offset_ms != 0 else "0s"
        jitter_str = f"({io_result.jitter_reason})" if io_result.jitter_reason != "in_window" else ""
        
        # Format drive info
        drive_info = f"{operation.drive_letter} {drive_state.config.type}"
        interval_info = f"i{drive_state.config.interval}s"
        
        # Format details
        details = io_result.details if io_result.details else ""
        
        # Combine into log line
        log_line = (f"{timestamp_with_half} {op_type} {result} {drive_info} "
                   f"{interval_info} {duration} {offset_str} {jitter_str} {details}")
        
        return log_line.strip()
    
    def log_operation(self, operation: ScheduledOperation, io_result: "IOResult",
                     drive_state: DriveState):
        """Log an operation to the human-readable log."""
        try:
            log_line = self.format_operation_log(operation, io_result, drive_state)
            
            with self.log_lock:
                with open(self.current_log, 'a', encoding='utf-8') as f:
                    f.write(log_line + '\n')
                    
        except Exception as e:
            logger.error(f"Failed to write human log: {e}")
    
    def log_system_event(self, event_type: str, message: str, details: Dict[str, Any] = None):
        """Log a system event to the human-readable log."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if details:
                details_str = " ".join(f"{k}={v}" for k, v in details.items())
                log_line = f"{timestamp} SYSTEM {event_type} {message} {details_str}"
            else:
                log_line = f"{timestamp} SYSTEM {event_type} {message}"
            
            with self.log_lock:
                with open(self.current_log, 'a', encoding='utf-8') as f:
                    f.write(log_line + '\n')
                    
        except Exception as e:
            logger.error(f"Failed to write system event log: {e}")
    
    def clear_logs(self) -> bool:
        """Clear current logs and start fresh."""
        try:
            with self.log_lock:
                # Ensure folder exists
                self.log_dir.mkdir(parents=True, exist_ok=True)

                # Remove all numbered logs Log_current1..N
                max_keep = self.history_count if self.history_count > 0 else 5
                for i in range(1, max_keep + 1):
                    p = self.log_dir / f"Log_current{i}.txt"
                    if p.exists():
                        p.unlink()

                # Recreate Log_current1.txt empty
                (self.log_dir / "Log_current1.txt").touch()

                # Rebind the file handler to Log_current1.txt
                current_handler = None
                for h in logging.getLogger().handlers:
                    if isinstance(h, (logging.handlers.RotatingFileHandler, SizeRotatingFileHandler)):
                        current_handler = h
                        break
                if current_handler:
                    current_handler.close()
                    logging.getLogger().removeHandler(current_handler)

                    new_handler = SizeRotatingFileHandler(
                        self.log_dir / "Log_current1.txt",
                        maxBytes=self.max_size_kb * 1024,
                        backupCount=self.history_count,
                        encoding='utf-8'
                    )
                    new_handler.setFormatter(self.formatter)
                    new_handler.setLevel(logging.INFO)
                    logging.getLogger().addHandler(new_handler)

                self.log_system_event("CLEAR", "Logs cleared by user")
                return True
        except Exception as e:
            logger.error(f"Failed to clear logs: {e}")
            return False
    
    def get_log_files(self) -> List[Path]:
        """Get list of available log files."""
        files = []
        max_keep = self.history_count if self.history_count > 0 else 5
        for i in range(1, max_keep + 1):
            p = self.log_dir / f"Log_current{i}.txt"
            if p.exists():
                files.append(p)
        return files

class LoggingManager:
    """Manages both human and NDJSON logging."""

    def __init__(self, log_dir: Path, config):
        self.log_dir = log_dir
        self.config = config

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Initialize loggers
        self.human_logger = HumanLogger(log_dir, config)
        self.event_logger = EventLogger(log_dir, config)

        # Log startup
        self.human_logger.log_system_event("STARTUP", "Drive Revenant started")

        # Initialize debug logger for development
        self._init_debug_logger()

    def _init_debug_logger(self):
        """Initialize debug logger for development and troubleshooting."""
        debug_log_path = self.log_dir / "debug.log"

        # Create debug logger
        self.debug_logger = logging.getLogger('debug')
        self.debug_logger.setLevel(logging.DEBUG)

        # Remove existing handlers to avoid duplicates
        self.debug_logger.handlers.clear()

        # Create file handler for debug log
        debug_handler = logging.FileHandler(debug_log_path, encoding='utf-8')
        debug_handler.setLevel(logging.DEBUG)

        # Create formatter
        debug_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        debug_handler.setFormatter(debug_formatter)

        self.debug_logger.addHandler(debug_handler)
        self.debug_logger.propagate = False  # Don't propagate to root logger

        self.debug_logger.info("Debug logging initialized")

    def log_debug(self, message: str, **kwargs):
        """Log debug message for development."""
        if hasattr(self, 'debug_logger'):
            self.debug_logger.debug(message, extra=kwargs)

    def log_drive_scan(self, drive_letter: str, operation: str, details: str):
        """Log drive scanning operations."""
        self.log_debug(f"Drive scan {operation}: {drive_letter} - {details}")

    def log_operation_attempt(self, drive_letter: str, operation_type: str, result: str, details: str):
        """Log operation attempts for debugging."""
        self.log_debug(f"Operation attempt: {drive_letter} {operation_type} -> {result}", extra={
            'drive': drive_letter,
            'operation': operation_type,
            'result': result,
            'details': details
        })
    
    def log_operation(self, operation: ScheduledOperation, io_result: "IOResult", 
                     drive_state: DriveState, current_time: float):
        """Log an operation to both human and NDJSON logs."""
        # Human-readable log
        self.human_logger.log_operation(operation, io_result, drive_state)
        
        # NDJSON log
        self.event_logger.log_operation(operation, io_result, drive_state, current_time)
    
    def log_system_event(self, event_type: str, message: str, details: Dict[str, Any] = None):
        """Log a system event."""
        self.human_logger.log_system_event(event_type, message, details)
    
    def log_scheduler_event(self, event_type: str, details: Dict[str, Any], current_time: float):
        """Log a scheduler event."""
        self.event_logger.log_scheduler_event(event_type, details, current_time)
    
    def log_policy_change(self, policy_type: str, old_value: Any, new_value: Any, current_time: float):
        """Log a policy change."""
        self.event_logger.log_policy_change(policy_type, old_value, new_value, current_time)
    
    def log_config_change(self, change_type: str, details: Dict[str, Any], current_time: float):
        """Log a configuration change."""
        self.event_logger.log_config_change(change_type, details, current_time)
    
    def clear_logs(self) -> bool:
        """Clear all logs and start fresh."""
        return self.human_logger.clear_logs()
    
    def get_log_files(self) -> List[Path]:
        """Get list of available log files."""
        return self.human_logger.get_log_files()
    
    def get_ndjson_file(self) -> Optional[Path]:
        """Get the NDJSON events file path."""
        return self.event_logger.ndjson_file
    
    def shutdown(self):
        """Shutdown logging system."""
        self.human_logger.log_system_event("SHUTDOWN", "Drive Revenant shutting down")
        
        # Close any open files
        logging.shutdown()
