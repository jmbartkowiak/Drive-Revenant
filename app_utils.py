# app_utils.py
# Version: 0.1.0
# Shared utility functions for Drive Revenant to eliminate code duplication and provide common functionality.

import hashlib
import os
import time
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def sha256_head(path: Path, n: int = 16) -> str:
    """Get first n characters of SHA256 hash of file at path."""
    try:
        sha256_hash = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()[:n]
    except Exception as e:
        logger.warning(f"Could not compute SHA256 for {path}: {e}")
        return "unknown"

def safe_makedirs(path: Path) -> bool:
    """Safely create directories, handling permissions and existing dirs."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.warning(f"Could not create directory {path}: {e}")
        return False

def normalize_drive_letter(drive_letter) -> str:
    """Normalize drive letter to uppercase with colon.

    Args:
        drive_letter: String or None to normalize

    Returns:
        Normalized drive letter (e.g., "C:") or empty string if invalid
    """
    if drive_letter is None or not isinstance(drive_letter, str):
        return ""

    if not drive_letter.strip():
        return ""

    letter = drive_letter.strip().upper()
    if len(letter) == 1 and letter.isalpha():
        return f"{letter}:"
    return letter

def format_timespan(seconds: float) -> str:
    """Format seconds as human-readable timespan."""
    if seconds < 0:
        return "0s"

    if seconds < 60:
        return f"{int(seconds + 0.5)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = int(seconds % 60 + 0.5)
        return f"{minutes}m{remaining_seconds}s"
    else:
        hours = int(seconds // 3600)
        remaining_minutes = int((seconds % 3600) // 60)
        return f"{hours}h{remaining_minutes}m"

def format_bytes(bytes_value) -> str:
    """Format bytes as human-readable size using binary units (1024-based).

    Args:
        bytes_value: Integer or float number of bytes

    Returns:
        Formatted string with appropriate unit (B, KB, MB, GB, TB, PB)

    Note:
        Uses binary units (1 KB = 1024 bytes, not 1000).
        Float inputs are truncated to integers for display.
    """
    if bytes_value is None:
        return "0B"

    # Convert to int, truncating floats
    value = int(bytes_value) if isinstance(bytes_value, (int, float)) else 0

    if value < 0:
        return "0B"

    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if value < 1024:
            return f"{value}{unit}"
        value //= 1024
    return f"{value}PB"

def monotonic_now() -> float:
    """Get current monotonic time (alias for time.monotonic)."""
    return time.monotonic()

def wall_now() -> float:
    """Get current wall clock time (alias for time.time)."""
    return time.time()

def timestamp_filename(prefix: str = "", suffix: str = "", ext: str = "txt") -> str:
    """Generate timestamped filename."""
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    parts = [part for part in [prefix, timestamp, suffix] if part]
    return "_".join(parts) + f".{ext}"
