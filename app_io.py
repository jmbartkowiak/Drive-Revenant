# app_io.py
# Version: 1.2.0
# I/O operations module for Drive Revenant with durability timing, lock retry logic,
# result taxonomy (OK, PARTIAL_FLUSH, SKIP_LOCKED), hardware-signal drive type detection
# (Win32 storage IOCTLs + WMI, no PowerShell), and drive_revenant file management.

import os
import time
import threading
import tempfile
import ctypes
import struct
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import logging

from app_types import OperationType, ResultCode, DriveState, ScheduledOperation

# Windows error codes for failure classification
ERROR_NOT_READY = 21
ERROR_DEVICE_NOT_CONNECTED = 1167
ERROR_MEDIA_CHANGED = 1110
ERROR_PATH_NOT_FOUND = 3
ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32

logger = logging.getLogger(__name__)

# --- Win32 storage detection constants (no PowerShell, no admin) ---

# IOCTL_STORAGE_QUERY_PROPERTY = CTL_CODE(0x2D, 0x0500, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
# IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = CTL_CODE(0x56, 0x0000, METHOD_BUFFERED, FILE_ANY_ACCESS)
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000

# STORAGE_PROPERTY_ID values (ntddstor.h)
STORAGE_DEVICE_PROPERTY = 0
STORAGE_DEVICE_SEEK_PENALTY_PROPERTY = 7
# STORAGE_QUERY_TYPE
PROPERTY_STANDARD_QUERY = 0

# STORAGE_BUS_TYPE values (ntddstor.h) — subset used for classification
BUS_TYPE_USB = 0x07
BUS_TYPE_SAS = 0x0A
BUS_TYPE_SATA = 0x0B
BUS_TYPE_FILE_BACKED_VIRTUAL = 0x0F
BUS_TYPE_SPACES = 0x10
BUS_TYPE_NVME = 0x11
BUS_TYPE_SCM = 0x12

# MSFT_PhysicalDisk.MediaType (root\Microsoft\Windows\Storage)
WMI_MEDIA_TYPE = {0: None, 3: "HDD", 4: "SSD", 5: "SCM"}

# CreateFileW flags
GENERIC_NONE = 0
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# ctypes prototypes (set lazily to avoid import-time side effects)
_kernel32 = ctypes.windll.kernel32
_kernel32.CreateFileW.restype = ctypes.c_void_p
_kernel32.CreateFileW.argtypes = [
    ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
]
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
_kernel32.DeviceIoControl.argtypes = [
    ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
    ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p,
]
_kernel32.DeviceIoControl.restype = ctypes.c_int


class _STORAGE_PROPERTY_QUERY(ctypes.Structure):
    _fields_ = [
        ("PropertyId", ctypes.c_uint32),
        ("QueryType", ctypes.c_uint32),
        ("AdditionalParameters", ctypes.c_ubyte * 1),
    ]


class _DEVICE_SEEK_PENALTY_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_uint32),
        ("Size", ctypes.c_uint32),
        ("IncursSeekPenalty", ctypes.c_ubyte),  # BOOLEAN: TRUE=HDD, FALSE=SSD
    ]


@dataclass
class IOResult:
    """Result of an I/O operation."""
    result_code: ResultCode
    duration_ms: float
    details: str = ""
    offset_ms: float = 0.0
    jitter_reason: str = ""
    failure_class: Optional[str] = None
    pack_size: Optional[int] = None

class IOManager:
    """Manages I/O operations for drive keep-alive."""
    
    def __init__(self, config):
        self.config = config
        self.max_flush_ms = config.max_flush_ms
        self.lock_retry_ms = config.lock_retry_ms
        self.fsync_enabled = config.fsync
        # SAFE mode: when True, operations are simulated and no real writes happen.
        self.simulate_writes = bool(getattr(config, 'simulate_writes', True))
        
        # Track ping directories per drive
        self.ping_dirs: Dict[str, Path] = {}
        
        # Cache for drive type detection to avoid repeated storage queries
        self._drive_type_cache: Dict[str, str] = {}
        self._cache_timestamp: float = 0
        self._cache_ttl: float = 30.0  # Cache for 30 seconds
        self._scan_prefetched_until: float = 0.0  # Window after batch prefetch where we trust cache only
        
        # Volume info cache to reduce redundant file system calls
        self._volume_info_cache: Dict[str, Dict[str, Any]] = {}
        self._volume_cache_timestamp: float = 0
        self._volume_cache_ttl: float = 60.0  # 1 minute
        
        # Lock for thread safety
        self._lock = threading.Lock()
    
    def _classify_failure(self, exception: Exception) -> str:
        """Classify failure based on Windows error codes and exception type."""
        # Prefer the exception's own winerror (reliable). ctypes.get_last_error()
        # only reflects the last use_last_error=True call and can be stale.
        error_code = getattr(exception, 'winerror', None)
        if error_code is None:
            error_code = ctypes.get_last_error()

        # Check for device-related errors
        if error_code in (ERROR_NOT_READY, ERROR_DEVICE_NOT_CONNECTED, ERROR_MEDIA_CHANGED):
            return "DEVICE_GONE"

        # Check for path-related errors (device gone)
        if error_code == ERROR_PATH_NOT_FOUND:
            return "DEVICE_GONE"

        # Check for locking/sharing errors
        if error_code in (ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION):
            return "LOCKED"
        
        if hasattr(exception, 'errno'):
            # Common errno values that indicate device issues
            if exception.errno in (2, 5, 6, 19, 21, 22, 28, 30, 32, 116, 121):  # Various "device not ready" type errors
                return "DEVICE_GONE"
            if exception.errno in (13, 16):  # Permission denied, device busy
                return "LOCKED"
        
        # Check exception message for common patterns
        error_msg = str(exception).lower()
        if any(phrase in error_msg for phrase in ['device not ready', 'not ready', 'device not connected', 'media changed', 'path not found']):
            return "DEVICE_GONE"
        if any(phrase in error_msg for phrase in ['access denied', 'sharing violation', 'permission denied', 'locked']):
            return "LOCKED"
        
        # Default to IO_FATAL for other errors
        return "IO_FATAL"
    
    def get_ping_directory(self, drive_letter: str, custom_ping_dir: Optional[str] = None) -> Path:
        """Get the ping directory for a drive."""
        if custom_ping_dir:
            return Path(custom_ping_dir)
        
        # Use default: X:\.drive_revenant\
        return Path(f"{drive_letter}\\.drive_revenant")
    
    def set_simulate_writes(self, value: bool) -> None:
        """Enable/disable SAFE mode (simulate operations, no real writes)."""
        self.simulate_writes = bool(value)

    def ensure_ping_directory(self, ping_dir: Path) -> bool:
        """Ensure the ping directory exists."""
        try:
            ping_dir.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"Failed to create ping directory {ping_dir}: {e}")
            return False
    
    def perform_operation(self, drive_state: DriveState, operation: ScheduledOperation) -> IOResult:
        """Perform the I/O operation for a drive."""
        start_time = time.monotonic()

        try:
            logger.debug(f"Starting I/O operation: {drive_state.letter} {operation.operation_type.value}")

            # SAFE mode: simulate the operation without touching the drive. No
            # directory is created and no bytes are read or written.
            if self.simulate_writes:
                logger.debug(f"{drive_state.letter}: SAFE mode — simulating {operation.operation_type.value} operation")
                return IOResult(
                    result_code=ResultCode.OK,
                    duration_ms=0.0,
                    details="Simulated (SAFE mode)",
                    offset_ms=operation.offset_ms,
                    jitter_reason=operation.jitter_reason,
                    pack_size=operation.pack_size
                )

            # Get ping directory
            ping_dir = self.get_ping_directory(drive_state.letter, drive_state.config.ping_dir)

            # Ensure directory exists
            if not self.ensure_ping_directory(ping_dir):
                error_msg = "Failed to create ping directory"
                logger.error(f"{drive_state.letter}: {error_msg}")
                return IOResult(
                    result_code=ResultCode.ERROR,
                    duration_ms=(time.monotonic() - start_time) * 1000,
                    details=error_msg,
                    offset_ms=operation.offset_ms,
                    jitter_reason=operation.jitter_reason,
                    pack_size=operation.pack_size
                )

            # Perform the operation
            if operation.operation_type == OperationType.READ:
                result = self._perform_read_operation(ping_dir, start_time)
            else:
                result = self._perform_write_operation(ping_dir, start_time)

            # Add operation metadata
            result.offset_ms = operation.offset_ms
            result.jitter_reason = operation.jitter_reason

            logger.debug(f"I/O operation completed: {drive_state.letter} {operation.operation_type.value} -> {result.result_code.value}")
            return result

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            error_msg = f"Unexpected error during I/O operation: {e}"
            logger.error(f"{drive_state.letter}: {error_msg}")
            return IOResult(
                result_code=ResultCode.ERROR,
                duration_ms=duration_ms,
                details=error_msg,
                offset_ms=operation.offset_ms,
                jitter_reason=operation.jitter_reason,
                pack_size=operation.pack_size
            )
    
    def _perform_read_operation(self, ping_dir: Path, start_time: float) -> IOResult:
        """Perform a read operation on drive_revenant."""
        ping_file = ping_dir / "drive_revenant"
        
        # Check if file exists - don't create it during read operations
        if not ping_file.exists():
            duration_ms = (time.monotonic() - start_time) * 1000
            return IOResult(
                result_code=ResultCode.ERROR,
                duration_ms=duration_ms,
                details="Ping file does not exist",
                failure_class="MISSING_FILE"
            )
        
        # Perform the read with retry logic
        return self._read_with_retry(ping_file, start_time)
    
    def _perform_write_operation(self, ping_dir: Path, start_time: float) -> IOResult:
        """Perform a write operation on drive_revenant."""
        ping_file = ping_dir / "drive_revenant"
        
        # Generate content with half-second indicator
        current_time = time.time()
        half_second = "5" if int(current_time * 2) % 2 else "0"
        content = f"{int(current_time)}.{half_second}"
        
        # Perform the write with retry logic
        return self._write_with_retry(ping_file, content, start_time)
    
    def _read_with_retry(self, file_path: Path, start_time: float) -> IOResult:
        """Read file with lock retry logic."""
        retry_start = time.monotonic()
        last_error = None
        
        while (time.monotonic() - retry_start) * 1000 < self.lock_retry_ms:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                duration_ms = (time.monotonic() - start_time) * 1000
                return IOResult(
                    result_code=ResultCode.OK,
                    duration_ms=duration_ms,
                    details=f"Read {len(content)} bytes"
                )
                
            except (PermissionError, OSError) as e:
                last_error = e
                # Classify the failure
                failure_class = self._classify_failure(e)
                
                # If device is gone, don't retry
                if failure_class == "DEVICE_GONE":
                    duration_ms = (time.monotonic() - start_time) * 1000
                    return IOResult(
                        result_code=ResultCode.ERROR,
                        duration_ms=duration_ms,
                        details=f"Device gone: {e}",
                        failure_class=failure_class
                    )
                
                # Wait a bit before retry
                time.sleep(0.01)
                continue
        
        # Retry budget exhausted
        duration_ms = (time.monotonic() - start_time) * 1000
        failure_class = self._classify_failure(last_error) if last_error else "IO_FATAL"
        return IOResult(
            result_code=ResultCode.SKIP_LOCKED,
            duration_ms=duration_ms,
            details=f"File locked after {self.lock_retry_ms}ms retry: {last_error}",
            failure_class=failure_class
        )
    
    def _write_with_retry(self, file_path: Path, content: str, start_time: float) -> IOResult:
        """Write file with lock retry logic and durability timing."""
        retry_start = time.monotonic()
        last_error = None
        
        while (time.monotonic() - retry_start) * 1000 < self.lock_retry_ms:
            try:
                # Write to temporary file first for atomicity
                temp_file = file_path.with_suffix('.tmp')
                
                with open(temp_file, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                # Measure flush time
                flush_start = time.monotonic()
                
                if self.fsync_enabled:
                    try:
                        # Flush and sync the temp file before moving
                        with open(temp_file, 'r+b') as f:
                            f.flush()
                            os.fsync(f.fileno())
                    except Exception as e:
                        logger.warning(f"Failed to flush temp file: {e}")
                
                flush_duration_ms = (time.monotonic() - flush_start) * 1000
                
                # Atomic move
                temp_file.replace(file_path)
                
                # Check if flush exceeded budget
                if flush_duration_ms > self.max_flush_ms:
                    duration_ms = (time.monotonic() - start_time) * 1000
                    return IOResult(
                        result_code=ResultCode.PARTIAL_FLUSH,
                        duration_ms=duration_ms,
                        details=f"Flush took {flush_duration_ms:.1f}ms (limit: {self.max_flush_ms}ms)"
                    )
                
                duration_ms = (time.monotonic() - start_time) * 1000
                return IOResult(
                    result_code=ResultCode.OK,
                    duration_ms=duration_ms,
                    details=f"Wrote {len(content)} bytes, flush: {flush_duration_ms:.1f}ms"
                )
                
            except (PermissionError, OSError) as e:
                last_error = e
                # Classify the failure
                failure_class = self._classify_failure(e)
                
                # Clean up temp file if it exists
                try:
                    temp_file.unlink(missing_ok=True)
                except:
                    pass
                
                # If device is gone, don't retry
                if failure_class == "DEVICE_GONE":
                    duration_ms = (time.monotonic() - start_time) * 1000
                    return IOResult(
                        result_code=ResultCode.ERROR,
                        duration_ms=duration_ms,
                        details=f"Device gone during write: {e}",
                        failure_class=failure_class
                    )
                
                # Wait a bit before retry
                time.sleep(0.01)
                continue
        
        # Retry budget exhausted
        duration_ms = (time.monotonic() - start_time) * 1000
        failure_class = self._classify_failure(last_error) if last_error else "IO_FATAL"
        return IOResult(
            result_code=ResultCode.SKIP_LOCKED,
            duration_ms=duration_ms,
            details=f"File locked after {self.lock_retry_ms}ms retry: {last_error}",
            failure_class=failure_class
        )
    
    def verify_ping_file(self, drive_letter: str, custom_ping_dir: Optional[str] = None) -> bool:
        """Verify that drive_revenant exists and is readable (for manual ping verification)."""
        try:
            ping_dir = self.get_ping_directory(drive_letter, custom_ping_dir)
            ping_file = ping_dir / "drive_revenant"
            
            if not ping_file.exists():
                return False
            
            # Try to read the file
            with open(ping_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return len(content) > 0
            
        except Exception as e:
            logger.error(f"Failed to verify ping file for {drive_letter}: {e}")
            return False
    
    def cleanup_ping_files(self, drive_letters: list) -> Dict[str, bool]:
        """Clean up ping files for specified drives (optional maintenance)."""
        results = {}
        
        for letter in drive_letters:
            try:
                ping_dir = self.get_ping_directory(letter)
                ping_file = ping_dir / "drive_revenant"
                
                if ping_file.exists():
                    ping_file.unlink()
                    results[letter] = True
                else:
                    results[letter] = True  # Already clean
                    
            except Exception as e:
                logger.error(f"Failed to cleanup ping file for {letter}: {e}")
                results[letter] = False
        
        return results
    
    def scan_available_drives(self, mode: str = "quick", config_drives: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        """Scan for available drives and return drive information.
        
        Args:
            mode: "quick" (only check drives in config_drives) or "full" (scan all E-Z)
            config_drives: Dict of DriveConfig objects to check in quick mode
        
        Returns:
            Dict of drive_letter -> drive_info for available drives
        """
        available_drives = {}

        # Determine which letters to check
        if mode == "quick" and config_drives:
            # Quick mode: only check drives in config
            letters_to_check = list(config_drives.keys())
            
            # Add forced drive letters if configured
            if hasattr(self.config, 'forced_drive_letters') and self.config.forced_drive_letters:
                forced_letters_raw = self.config.forced_drive_letters.split(',')
                forced_letters = []
                for letter in forced_letters_raw:
                    letter = letter.strip().upper()
                    if letter and not letter.endswith(':'):
                        letter = f"{letter}:"
                    if letter and letter not in letters_to_check:
                        forced_letters.append(letter)
                        letters_to_check.append(letter)
                
                if forced_letters:
                    logger.info(f"Added {len(forced_letters)} forced drive letters: {forced_letters}")
            
            logger.info(f"Quick scan mode: checking {len(letters_to_check)} drives (config + forced)")
        else:
            # Full mode: scan all possible letters E-Z
            letters_to_check = [f"{chr(letter)}:" for letter in range(ord('E'), ord('Z') + 1)]
            logger.info(f"Full scan mode: checking {len(letters_to_check)} possible drive letters")

        # Get all drive types in one batch operation (much faster)
        logger.debug("Getting drive types in batch...")
        all_drive_types = self._get_detailed_drive_types()
        if all_drive_types:
            # Update cache with all drive types at once
            current_time = time.time()
            self._drive_type_cache.update(all_drive_types)
            self._cache_timestamp = current_time
            # During the active scan, avoid re-running detection; trust cache
            self._scan_prefetched_until = current_time + 300.0  # 5 minutes
            logger.debug(f"Cached {len(all_drive_types)} drive types")

        # Check each drive letter
        for drive_letter in letters_to_check:
            try:
                logger.debug(f"Scanning drive {drive_letter}")
                # Strip colon from drive letter for get_drive_info
                drive_letter_clean = drive_letter.rstrip(':')
                drive_info = self.get_drive_info(drive_letter_clean)

                if drive_info["exists"] and drive_info["accessible"]:
                    # Determine if this is an external/removable drive
                    if self._is_external_drive(drive_letter, drive_info):
                        available_drives[drive_letter] = drive_info
                        logger.info(f"Found external drive: {drive_letter} ({drive_info['type']})")
                    else:
                        logger.debug(f"Skipping internal/system drive: {drive_letter}")
                else:
                    error_msg = drive_info.get('error', 'Unknown error')
                    logger.debug(f"Drive {drive_letter} not accessible: {error_msg}")
            except Exception as e:
                logger.error(f"Error scanning drive {drive_letter}: {e}")
                # Continue scanning other drives even if one fails

        logger.info(f"Drive scan completed: {len(available_drives)} external drives found")
        return available_drives

    def _is_external_drive(self, drive_letter: str, drive_info: Dict[str, Any]) -> bool:
        """Determine if a drive is external/removable (not internal system drive)."""
        try:
            # Get Windows drive type
            drive_path = Path(f"{drive_letter}\\")
            import ctypes
            from ctypes import wintypes

            drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(drive_path))

            # DRIVE_REMOVABLE (2) or DRIVE_CDROM (5) are external
            if drive_type in [2, 5]:  # USB drives, CD/DVD drives
                return True

            # For DRIVE_FIXED (3), check if it's not a system drive
            if drive_type == 3:  # Fixed drive
                # Check volume information for system indicators
                volume_info = drive_info.get("volume_info", {})

                # Check if it's a system drive by looking at volume name or file system
                volume_name = volume_info.get("volume_name", "").lower()
                file_system = volume_info.get("file_system", "").lower()

                # Avoid system drives (Windows, System, etc.)
                system_indicators = ["windows", "system", "boot", "recovery"]
                if any(indicator in volume_name for indicator in system_indicators):
                    return False

                # Also check drive letter - avoid C: and D: as they're typically system drives
                if drive_letter.upper() in ["C:", "D:"]:
                    return False

                # For other fixed drives, assume they're external unless proven otherwise
                return True

            # Network drives (4) and RAM disks (6) are not external
            return False

        except Exception as e:
            logger.debug(f"Error determining if {drive_letter} is external: {e}")
            # Default to not external if we can't determine
            return False

    def get_drive_info(self, drive_letter: str) -> Dict[str, Any]:
        """Get information about a drive for device probing."""
        logger.debug(f"Getting drive info for {drive_letter}")

        try:
            drive_path = Path(f"{drive_letter}:\\")

            # Check if drive exists and is accessible
            if not drive_path.exists():
                logger.debug(f"Drive {drive_letter} does not exist")
                return {
                    "exists": False,
                    "accessible": False,
                    "type": "Unknown"
                }

            # Check if we can actually access the drive
            try:
                # Probe media access without enumerating the whole root
                next(iter(drive_path.iterdir()), None)
            except (PermissionError, OSError) as e:
                logger.debug(f"Drive {drive_letter} not accessible: {e}")
                return {
                    "exists": True,
                    "accessible": False,
                    "type": "Unknown",
                    "error": str(e)
                }

            # Get drive type using the hardware-signal detection chain
            drive_type = self._detect_drive_type_simplified(drive_letter)
            
            # Apply treat_unknown_as_ssd setting if available
            if drive_type == "Unknown" and hasattr(self, 'config') and self.config.treat_unknown_as_ssd:
                drive_type = "SSD"
                logger.debug(f"Treating unknown drive {drive_letter} as SSD due to treat_unknown_as_ssd setting")

            # Get volume information
            volume_info = self._get_volume_info(drive_path)
            
            # Get total drive size
            total_size_bytes = None
            try:
                import shutil
                usage = shutil.disk_usage(str(drive_path))
                total_size_bytes = usage.total
            except Exception as e:
                logger.debug(f"Failed to get drive size for {drive_letter}: {e}")
            
            # Get volume GUID (Windows-specific)
            volume_guid = None
            try:
                import ctypes
                from ctypes import wintypes
                guid_buffer = ctypes.create_unicode_buffer(50)
                result_guid = ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(
                    str(drive_path),
                    guid_buffer,
                    50
                )
                if result_guid:
                    volume_guid = guid_buffer.value.strip('\\').strip()
            except Exception as e:
                logger.debug(f"Failed to get volume GUID for {drive_letter}: {e}")

            result = {
                "exists": True,
                "accessible": True,
                "type": drive_type,
                "volume_info": volume_info,
                "volume_guid": volume_guid,
                "total_size_bytes": total_size_bytes
            }

            logger.debug(f"Drive {drive_letter} info: {result}")
            return result

        except Exception as e:
            logger.error(f"Failed to get drive info for {drive_letter}: {e}")
            return {
                "exists": False,
                "accessible": False,
                "type": "Unknown",
                "error": str(e)
            }
    
    def _detect_drive_type_simplified(self, drive_letter: str) -> str:
        """Detect drive type using the hardware-signal detection chain."""
        try:
            # Check cache first (should be populated by scan_available_drives)
            current_time = time.time()
            # Use drive letter with colon for cache lookup
            drive_key = f"{drive_letter}:"

            # If we recently prefetched for a scan, always use cache
            if current_time < self._scan_prefetched_until and drive_key in self._drive_type_cache:
                logger.debug(f"Using prefetched drive type for {drive_letter}: {self._drive_type_cache[drive_key]}")
                return self._drive_type_cache[drive_key]

            if (current_time - self._cache_timestamp) < self._cache_ttl and drive_key in self._drive_type_cache:
                logger.debug(f"Using cached drive type for {drive_letter}: {self._drive_type_cache[drive_key]}")
                return self._drive_type_cache[drive_key]

            # If not in cache, detect directly (shouldn't happen during normal scan)
            logger.debug(f"Drive type not in cache for {drive_letter}, detecting directly...")
            drive_type = self._detect_drive_type(drive_letter)
            self._drive_type_cache[drive_key] = drive_type
            self._cache_timestamp = current_time
            return drive_type

        except Exception as e:
            logger.error(f"Error in drive type detection for {drive_letter}: {e}")
            return "Unknown"
    
    # --- Drive type detection (Win32 storage IOCTLs + WMI, no PowerShell) ---

    def _open_storage_handle(self, path: str, *, volume: bool = False) -> Optional[int]:
        """Open a device/volume handle with query-only access (no admin)."""
        flags = FILE_FLAG_BACKUP_SEMANTICS if volume else 0
        handle = _kernel32.CreateFileW(
            path, GENERIC_NONE, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None, OPEN_EXISTING, flags | FILE_ATTRIBUTE_NORMAL, None,
        )
        if not handle or handle == INVALID_HANDLE_VALUE:
            return None
        return handle

    def _device_io_control(self, handle: int, ioctl: int,
                           query: Optional[_STORAGE_PROPERTY_QUERY] = None,
                           out_size: int = 0) -> Optional[bytes]:
        """Run DeviceIoControl and return the output buffer, or None on failure."""
        in_ptr = ctypes.byref(query) if query is not None else None
        in_size = ctypes.sizeof(query) if query is not None else 0
        out_buf = (ctypes.c_ubyte * out_size)() if out_size else None
        returned = ctypes.c_ulong()
        ok = _kernel32.DeviceIoControl(
            handle, ioctl, in_ptr, in_size,
            out_buf, out_size if out_buf is not None else 0,
            ctypes.byref(returned), None,
        )
        if not ok:
            return None
        return bytes(out_buf[:returned.value]) if out_buf is not None else b""

    def _get_volume_disk_numbers(self, volume_path: str) -> List[int]:
        """Map a volume path (e.g. \\\\.\\C:) to its physical disk numbers."""
        handle = self._open_storage_handle(volume_path, volume=True)
        if handle is None:
            return []
        try:
            out = self._device_io_control(handle, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, None, 4096)
            if not out or len(out) < 4:
                return []
            count = struct.unpack_from("<I", out, 0)[0]
            disk_numbers = []
            for i in range(count):
                # VOLUME_DISK_EXTENTS: DWORD count @0, then DISK_EXTENT[]. First extent
                # sits at offset 8 (4-byte header + 4-byte padding); DISK_EXTENT is 24 bytes
                # (DiskNumber @0, LARGE_INTEGER StartingOffset @8, ExtentLength @16).
                off = 8 + i * 24
                if off + 4 > len(out):
                    break
                disk_numbers.append(struct.unpack_from("<I", out, off)[0])
            return disk_numbers
        finally:
            _kernel32.CloseHandle(handle)

    def _get_disk_numbers_wmi(self, drive_letter: str) -> List[int]:
        """Fallback letter→disk mapping via MSFT_Partition (root\\Microsoft\\Windows\\Storage)."""
        try:
            import win32com.client
            locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
            service = locator.ConnectServer(".", r"root\Microsoft\Windows\Storage")
            query = f"SELECT DiskNumber FROM MSFT_Partition WHERE DriveLetter='{drive_letter}'"
            return [int(part.DiskNumber) for part in service.ExecQuery(query)]
        except Exception as e:
            logger.debug(f"WMI MSFT_Partition query failed for {drive_letter}: {e}")
            return []

    def _get_disk_numbers_for_letter(self, drive_letter: str) -> List[int]:
        """Return the physical disk number(s) backing a drive letter."""
        letter = drive_letter.rstrip(':').upper()
        if len(letter) != 1 or not ('A' <= letter <= 'Z'):
            return []
        disk_numbers = self._get_volume_disk_numbers(f"\\\\.\\{letter}:")
        if not disk_numbers:
            disk_numbers = self._get_disk_numbers_wmi(letter)
        return disk_numbers

    def _query_seek_penalty(self, disk_number: int) -> Optional[bool]:
        """True=HDD, False=SSD, None=unsupported, via StorageDeviceSeekPenaltyProperty."""
        handle = self._open_storage_handle(f"\\\\.\\PhysicalDrive{disk_number}")
        if handle is None:
            return None
        try:
            query = _STORAGE_PROPERTY_QUERY()
            query.PropertyId = STORAGE_DEVICE_SEEK_PENALTY_PROPERTY
            query.QueryType = PROPERTY_STANDARD_QUERY
            out = self._device_io_control(handle, IOCTL_STORAGE_QUERY_PROPERTY, query, 32)
            if out is None or len(out) < 9:
                return None
            # DEVICE_SEEK_PENALTY_DESCRIPTOR.IncursSeekPenalty (BOOLEAN) @ offset 8
            return bool(out[8])
        finally:
            _kernel32.CloseHandle(handle)

    def _query_bus_type(self, disk_number: int) -> Optional[int]:
        """Return the STORAGE_BUS_TYPE of a physical disk, or None."""
        handle = self._open_storage_handle(f"\\\\.\\PhysicalDrive{disk_number}")
        if handle is None:
            return None
        try:
            query = _STORAGE_PROPERTY_QUERY()
            query.PropertyId = STORAGE_DEVICE_PROPERTY
            query.QueryType = PROPERTY_STANDARD_QUERY
            out = self._device_io_control(handle, IOCTL_STORAGE_QUERY_PROPERTY, query, 512)
            if out is None or len(out) < 32:
                return None
            # STORAGE_DEVICE_DESCRIPTOR.BusType is a 4-byte enum @ offset 28
            return struct.unpack_from("<I", out, 28)[0]
        finally:
            _kernel32.CloseHandle(handle)

    def _get_media_type_wmi(self, disk_number: int) -> Optional[str]:
        """Return 'SSD'/'HDD'/'SCM' from MSFT_PhysicalDisk.MediaType, or None."""
        try:
            import win32com.client
            locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
            service = locator.ConnectServer(".", r"root\Microsoft\Windows\Storage")
            for disk in service.ExecQuery("SELECT DeviceId, MediaType FROM MSFT_PhysicalDisk"):
                try:
                    if int(disk.DeviceId) == int(disk_number):
                        return WMI_MEDIA_TYPE.get(int(disk.MediaType))
                except (ValueError, TypeError):
                    continue
        except Exception as e:
            logger.debug(f"WMI MSFT_PhysicalDisk query failed for disk {disk_number}: {e}")
        return None

    def _get_friendly_name_wmi(self, disk_number: int) -> Optional[str]:
        """Return the MSFT_PhysicalDisk.FriendlyName for a disk, or None."""
        try:
            import win32com.client
            locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
            service = locator.ConnectServer(".", r"root\Microsoft\Windows\Storage")
            for disk in service.ExecQuery("SELECT DeviceId, FriendlyName FROM MSFT_PhysicalDisk"):
                try:
                    if int(disk.DeviceId) == int(disk_number):
                        return disk.FriendlyName or None
                except (ValueError, TypeError):
                    continue
        except Exception as e:
            logger.debug(f"WMI MSFT_PhysicalDisk FriendlyName query failed for disk {disk_number}: {e}")
        return None

    @staticmethod
    def _classify_by_name(name: Optional[str]) -> Optional[str]:
        """Best-effort SSD/HDD classification from a disk model/friendly name.

        Last-resort heuristic used only when hardware signals (seek penalty,
        MediaType) are unavailable — typically USB/SCSI enclosures that hide the
        medium. Returns None when the name is ambiguous.
        """
        s = (name or "").upper().strip()
        if not s:
            return None
        ssd = ("NVME", "SSD", "SOLID STATE", "M.2", "FLASH", "SAMSUNG",
               "MICRON", "SABRENT", "CRUCIAL", "KINGSTON", "WDS", "WD_BLACK")
        hdd = ("HDD", "HARD DISK", "WDC", "TOSHIBA", "SEAGATE", "GAME DRIVE",
               "BARRACUDA", "IRONWOLF", "EXOS", "ULTRASTAR", "EXPANSION",
               "ROTATIONAL", "SPINNING")
        if any(m in s for m in ssd):
            return "SSD"
        if any(m in s for m in hdd) or s.startswith("ST"):
            return "HDD"
        return None

    def _detect_fixed_drive_type(self, drive_letter: str) -> str:
        """Distinguish SSD vs HDD for a DRIVE_FIXED letter via the fallback chain."""
        disk_numbers = self._get_disk_numbers_for_letter(drive_letter)

        for disk_number in disk_numbers:
            penalty = self._query_seek_penalty(disk_number)
            if penalty is True:
                return "HDD"
            if penalty is False:
                return "SSD"

        for disk_number in disk_numbers:
            media_type = self._get_media_type_wmi(disk_number)
            if media_type in ("SSD", "HDD"):
                return media_type

        for disk_number in disk_numbers:
            if self._query_bus_type(disk_number) == BUS_TYPE_NVME:
                return "SSD"

        # Hardware signals unavailable (USB/SCSI enclosures): fall back to the
        # model/friendly-name heuristic.
        for disk_number in disk_numbers:
            name_type = self._classify_by_name(self._get_friendly_name_wmi(disk_number))
            if name_type is not None:
                return name_type

        return "Unknown"

    def _detect_drive_type(self, drive_letter: str) -> str:
        """Classify a drive using GetDriveTypeW + the SSD/HDD chain."""
        letter = drive_letter.rstrip(':').upper()
        try:
            coarse = _kernel32.GetDriveTypeW(f"{letter}:\\")
        except Exception:
            coarse = 0

        if coarse == 2:   # DRIVE_REMOVABLE
            return "Removable"
        if coarse == 4:   # DRIVE_REMOTE
            return "Network"
        if coarse == 5:   # DRIVE_CDROM
            return "CD-ROM"
        if coarse == 6:   # DRIVE_RAMDISK
            return "RAM-disk"
        if coarse != 3:   # DRIVE_FIXED
            return "Unknown"

        return self._detect_fixed_drive_type(letter)

    def _get_detailed_drive_types(self) -> Optional[Dict[str, str]]:
        """Return {letter_with_colon: type} for all present logical drives."""
        try:
            bitmask = _kernel32.GetLogicalDrives()
            if not bitmask:
                return None
            drive_info = {}
            for i in range(26):
                if bitmask & (1 << i):
                    letter = chr(ord('A') + i)
                    drive_info[f"{letter}:"] = self._detect_drive_type(letter)
            logger.debug(f"Drive detection results: {drive_info}")
            return drive_info
        except Exception as e:
            logger.error(f"Error in drive type detection: {e}")
            return None
    
    def _get_volume_info(self, drive_path: Path) -> Dict[str, Any]:
        """Get volume information for a drive with caching."""
        drive_letter = str(drive_path).rstrip('\\')
        
        # Check cache first
        current_time = time.time()
        if (current_time - self._volume_cache_timestamp) < self._volume_cache_ttl:
            if drive_letter in self._volume_info_cache:
                return self._volume_info_cache[drive_letter]
        
        try:
            import ctypes
            from ctypes import wintypes
            
            volume_name = ctypes.create_unicode_buffer(256)
            file_system = ctypes.create_unicode_buffer(256)
            serial_number = wintypes.DWORD()
            max_component_length = wintypes.DWORD()
            file_system_flags = wintypes.DWORD()
            
            result = ctypes.windll.kernel32.GetVolumeInformationW(
                str(drive_path),
                volume_name,
                256,
                ctypes.byref(serial_number),
                ctypes.byref(max_component_length),
                ctypes.byref(file_system_flags),
                file_system,
                256
            )
            
            if result:
                volume_info = {
                    "volume_name": volume_name.value,
                    "file_system": file_system.value,
                    "serial_number": serial_number.value,
                    "max_component_length": max_component_length.value,
                    "file_system_flags": file_system_flags.value
                }
            else:
                volume_info = {}
            
            # Cache the result
            self._volume_info_cache[drive_letter] = volume_info
            self._volume_cache_timestamp = current_time
            
            return volume_info
                
        except Exception as e:
            logger.error(f"Failed to get volume info: {e}")
            return {}
