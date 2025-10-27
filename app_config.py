# app_config.py
# Version: 1.1.5
# Pure persistence layer for Drive Revenant configuration with crash-safe saves, explicit mode resolution,
# APPDATA fallback, no side effects in getters, and read-only path properties.

import json
import os
import uuid
import shutil
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass, asdict
import logging

from app_types import DriveConfig
from app_utils import sha256_head

logger = logging.getLogger(__name__)

@dataclass
class AppConfig:
    """Main application configuration."""
    version: int = 5
    install_id: str = ""  # Generated UUID v4 on first run
    portable: bool = False
    autostart: bool = True
    autostart_method: str = "scheduler"  # "scheduler" or "registry"
    treat_unknown_as_ssd: bool = True
    default_interval_sec: int = 180
    interval_min_sec: int = 5
    jitter_sec: int = 2
    hdd_max_gap_sec: float = 300.0  # 5 minutes - reasonable for HDD protection
    deadline_margin_sec: float = 0.3
    pause_on_battery: bool = False
    idle_pause_min: int = 0
    policy_precedence: List[str] = None
    fsync: bool = True
    max_flush_ms: int = 150
    lock_retry_ms: int = 750
    error_quarantine_after: int = 5
    error_quarantine_sec: int = 60
    log_max_kb: int = 150
    log_history_count: int = 5
    log_ndjson: bool = True
    disable_hotkeys: bool = False
    suppress_quit_confirm: bool = False
    suppress_ssd_warnings: Dict[str, bool] = None  # Drive letter -> suppress warning
    gui_update_interval_ms: int = 250  # GUI update interval in milliseconds
    gui_update_interval_editing_ms: int = 1000  # GUI update interval when editing
    cli_countdown_interval_sec: int = 15  # CLI countdown logging interval in seconds
    hide_console_window: bool = False  # Hide the command terminal/console window
    scheduler_grid_ms: int = 250  # Scheduler timing grid in milliseconds
    scheduler_min_read_spacing_ms: int = 500  # Minimum spacing between read operations
    scheduler_min_write_spacing_ms: int = 1000  # Minimum spacing between write operations
    drive_stale_removal_days: int = 15  # Remove drives not seen for this many days (0=disabled)
    drive_scan_mode: str = "quick"  # "quick" (config drives only) or "full" (E-Z scan)
    forced_drive_letters: str = ""  # Comma-separated drive letters to always check (e.g., "F,J,K")
    per_drive: Dict[str, DriveConfig] = None

    def __post_init__(self):
        if self.policy_precedence is None:
            self.policy_precedence = ["global_pause", "battery", "idle", "per_drive_disable"]
        if self.per_drive is None:
            self.per_drive = {}
        if self.suppress_ssd_warnings is None:
            self.suppress_ssd_warnings = {}

        # Validate scheduler settings
        if self.scheduler_grid_ms <= 0:
            logger.warning(f"Invalid scheduler_grid_ms: {self.scheduler_grid_ms}, using 250ms")
            self.scheduler_grid_ms = 250
        if self.scheduler_min_read_spacing_ms <= 0:
            logger.warning(f"Invalid scheduler_min_read_spacing_ms: {self.scheduler_min_read_spacing_ms}, using 500ms")
            self.scheduler_min_read_spacing_ms = 500
        if self.scheduler_min_write_spacing_ms <= 0:
            logger.warning(f"Invalid scheduler_min_write_spacing_ms: {self.scheduler_min_write_spacing_ms}, using 1000ms")
            self.scheduler_min_write_spacing_ms = 1000

        if not self.install_id:
            self.install_id = str(uuid.uuid4())

class ConfigManager:
    """Manages configuration loading, saving, and migration."""

    # Class-level flag to track if dual-file warning has been shown
    _dual_file_warning_shown = False

    def __init__(self, portable_mode: Optional[bool] = None):
        # Explicit mode selection with smart probing when None
        if portable_mode is None:
            portable_mode = self._resolve_portable_mode()

        # Coerce to bool to avoid None values in config.portable
        self.portable_mode = bool(portable_mode)

        # Cache the resolved config path to ensure consistency
        self._resolved_config_path = self._get_config_path()
        self._config_path = self._resolved_config_path
        self._config_dir = self._config_path.parent
        self._log_dir = self._get_log_dir()

    def _resolve_portable_mode(self) -> bool:
        """Resolve portable mode by probing both locations when not explicitly specified."""
        portable_path = Path(__file__).parent / "config.json"
        appdata_path = self._win_appdata_roaming() / "DriveRevenant" / "config.json"

        portable_exists = portable_path.exists()
        appdata_exists = appdata_path.exists()

        if portable_exists and appdata_exists:
            # Both exist - prefer AppData (more standard location)
            logger.debug("Both portable and AppData configs exist - using AppData")
            return False
        elif appdata_exists:
            # Only AppData exists - use standard mode
            logger.debug("Only AppData config exists - using standard mode")
            return False
        elif portable_exists:
            # Only portable exists - check if it explicitly wants portable mode
            try:
                with open(portable_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if data.get('portable', False):
                    logger.debug("Only portable config exists and specifies portable=True")
                    return True
                else:
                    logger.debug("Only portable config exists but doesn't specify portable=True - using standard mode")
                    return False
            except (json.JSONDecodeError, KeyError):
                logger.debug("Portable config exists but is invalid - using standard mode")
                return False
        else:
            # Neither exists - default to standard mode (AppData)
            logger.debug("No config files exist - defaulting to standard mode")
            return False

    @property
    def config_path(self) -> Path:
        """Read-only access to config path."""
        return self._config_path

    @property
    def config_dir(self) -> Path:
        """Read-only access to config directory."""
        return self._config_dir

    @property
    def log_dir(self) -> Path:
        """Read-only access to log directory."""
        return self._log_dir

    def _win_appdata_roaming(self) -> Path:
        """Get Windows AppData/Roaming path with fallback."""
        # Try APPDATA first
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata)

        # Fall back to USERPROFILE/AppData/Roaming
        userprofile = os.environ.get("USERPROFILE")
        if userprofile:
            return Path(userprofile) / "AppData" / "Roaming"

        # Last resort: use home directory
        return Path.home() / "AppData" / "Roaming"

    def _get_config_path(self) -> Path:
        """Get the configuration file path based on resolved portable mode."""
        if self.portable_mode:
            # Portable mode: config next to executable
            exe_dir = Path(__file__).parent
            return exe_dir / "config.json"
        else:
            # Standard mode: AppData/DriveRevenant/config.json
            appdata = self._win_appdata_roaming()
            config_dir = appdata / "DriveRevenant"
            return config_dir / "config.json"

    def get_resolved_config_path(self) -> Path:
        """Get the resolved config path (for debugging)."""
        return self._resolved_config_path
    
    def _get_log_dir(self) -> Path:
        """Get the log directory path based on portable mode."""
        if self.portable_mode:
            exe_dir = Path(__file__).parent
            return exe_dir / "logs"
        else:
            appdata = self._win_appdata_roaming()
            return appdata / "DriveRevenant" / "logs"
    
    def load_config(self) -> AppConfig:
        """Load configuration with migration from older versions."""
        if not self.config_path.exists():
            logger.info("No existing config found, creating default config")
            config = self._create_default_config()
            # Log boot banner for new config
            self._log_boot_banner(config)
            return config

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            version = data.get('version', 1)
            logger.info(f"Loading config version {version}")

            if version < 5:
                data = self._migrate_config(data, version)

            config = self._dict_to_config(data)

            # Log boot banner with sha256 head
            self._log_boot_banner(config)
            self._check_dual_file_guard()

            return config

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to load config: {e}")
            logger.info("Creating backup and default config")
            self._backup_corrupted_config()
            config = self._create_default_config()
            self._log_boot_banner(config)
            return config

    def _log_boot_banner(self, config: AppConfig):
        """Log boot banner with config path and sha256 head."""
        sha256_head_str = sha256_head(self.config_path, 16)
        logger.info(f"Using config at {self.config_path} (portable={config.portable}, sha256:{sha256_head_str})")

    def _check_dual_file_guard(self):
        """Check for and warn about dual config files (shown only once per session)."""
        # Only show warning once per application session
        if ConfigManager._dual_file_warning_shown:
            return

        try:
            portable_config = Path(__file__).parent / "config.json"
            appdata_config = self._win_appdata_roaming() / "DriveRevenant" / "config.json"

            portable_exists = portable_config.exists()
            appdata_exists = appdata_config.exists()

            if portable_exists and appdata_exists:
                ConfigManager._dual_file_warning_shown = True  # Mark as shown
                if self.portable_mode:
                    logger.warning(f"Both portable config ({portable_config}) and AppData config ({appdata_config}) exist. Using portable config, ignoring AppData config.")
                else:
                    logger.warning(f"Both AppData config ({appdata_config}) and portable config ({portable_config}) exist. Using AppData config, ignoring portable config.")
        except Exception as e:
            logger.warning(f"Could not check for dual config files: {e}")

    @classmethod
    def reset_dual_file_warning(cls):
        """Reset the dual-file warning flag (for debugging/testing)."""
        cls._dual_file_warning_shown = False
    
    def _migrate_config(self, data: Dict[str, Any], from_version: int) -> Dict[str, Any]:
        """Migrate configuration from older versions."""
        logger.info(f"Migrating config from v{from_version} to current version")
        
        # Ensure version is set to latest
        data['version'] = 5
        
        # Add new fields with defaults
        # install_id will be generated in AppConfig.__post_init__ if empty
        
        if 'portable' not in data:
            data['portable'] = self.portable_mode
        
        if 'interval_min_sec' not in data:
            data['interval_min_sec'] = 5
        
        if 'hdd_max_gap_sec' not in data:
            data['hdd_max_gap_sec'] = 300.0  # 5 minutes - reasonable for HDD protection

        if 'deadline_margin_sec' not in data:
            data['deadline_margin_sec'] = 0.3

        if 'cli_countdown_interval_sec' not in data:
            data['cli_countdown_interval_sec'] = 15
        
        if 'policy_precedence' not in data:
            data['policy_precedence'] = ["global_pause", "battery", "idle", "per_drive_disable"]
        
        if 'max_flush_ms' not in data:
            data['max_flush_ms'] = 150
        
        if 'lock_retry_ms' not in data:
            data['lock_retry_ms'] = 750
        
        if 'error_quarantine_after' not in data:
            data['error_quarantine_after'] = 5
        
        if 'error_quarantine_sec' not in data:
            data['error_quarantine_sec'] = 60
        
        if 'log_ndjson' not in data:
            data['log_ndjson'] = True
        
        if 'disable_hotkeys' not in data:
            data['disable_hotkeys'] = False
        
        if 'suppress_quit_confirm' not in data:
            data['suppress_quit_confirm'] = False
        
        if 'suppress_ssd_warnings' not in data:
            data['suppress_ssd_warnings'] = {}
        
        if 'hide_console_window' not in data:
            data['hide_console_window'] = False
        
        # V4->V5: Add drive scanning configuration
        if 'drive_stale_removal_days' not in data:
            data['drive_stale_removal_days'] = 15
        
        if 'drive_scan_mode' not in data:
            data['drive_scan_mode'] = "quick"
        
        if 'forced_drive_letters' not in data:
            data['forced_drive_letters'] = ""
        
        # Migrate per_drive structure if needed
        if 'per_drive' in data:
            import time
            current_timestamp = time.time()
            
            for drive_letter, drive_data in data['per_drive'].items():
                if isinstance(drive_data, dict):
                    # Ensure all required fields exist
                    if 'ping_dir' not in drive_data:
                        drive_data['ping_dir'] = None
                    
                    # V4->V5: Add new tracking fields for existing drives
                    if 'volume_guid' not in drive_data:
                        drive_data['volume_guid'] = None
                    if 'last_seen_timestamp' not in drive_data:
                        # Set to current time for existing drives (assume recently seen)
                        drive_data['last_seen_timestamp'] = current_timestamp
                    if 'total_size_bytes' not in drive_data:
                        drive_data['total_size_bytes'] = None
        
        logger.info("Config migration completed")
        return data
    
    def _create_default_config(self) -> AppConfig:
        """Create a default configuration."""
        config = AppConfig()
        # portable mode is already resolved in __init__ - don't override
        config.portable = self.portable_mode

        # install_id is generated in AppConfig.__post_init__ - don't duplicate here

        # Start with empty drive configuration - drives will be detected dynamically
        # Only include drives that are actually available and external
        config.per_drive = {}

        return config
    
    def _dict_to_config(self, data: Dict[str, Any]) -> AppConfig:
        """Convert dictionary to AppConfig object."""
        # Convert per_drive dict to DriveConfig objects
        per_drive = {}
        if 'per_drive' in data:
            for drive_letter, drive_data in data['per_drive'].items():
                if isinstance(drive_data, dict):
                    per_drive[drive_letter] = DriveConfig(**drive_data)
                else:
                    per_drive[drive_letter] = drive_data
        
        data['per_drive'] = per_drive
        return AppConfig(**data)
    
    def _backup_corrupted_config(self):
        """Backup corrupted config file with timestamp."""
        if self.config_path.exists():
            # Create timestamped backup: config.json.YYYY-MM-DDTHH-MM-SS.backup
            timestamp = time.strftime("%Y-%m-%dT%H-%M-%S")
            backup_path = self.config_path.with_suffix(f'.{timestamp}.backup')
            try:
                shutil.copy2(self.config_path, backup_path)
                logger.info(f"Backed up corrupted config to {backup_path}")
            except Exception as e:
                logger.error(f"Failed to backup corrupted config: {e}")
    
    def save_config(self, config: AppConfig) -> bool:
        """Save configuration with crash-safe atomic write and directory fsync."""
        try:
            # Convert to dict for JSON serialization
            data = asdict(config)

            # Write to same-directory temp file first
            temp_path = self.config_path.with_suffix('.tmp')
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    try:
                        os.fsync(f.fileno())  # Ensure data is written to disk
                    except OSError as e:
                        # File fsync failed - log but continue (data may still be written)
                        logger.warning(f"File fsync failed: {e} (continuing with atomic replace)")

                # Atomic replace
                temp_path.replace(self.config_path)

                # fsync the parent directory to ensure the replace is durable
                # Note: O_DIRECTORY not available on Windows, so use platform-safe approach
                try:
                    if hasattr(os, 'O_DIRECTORY'):
                        # Unix-like systems
                        dir_fd = os.open(str(self.config_dir), os.O_DIRECTORY)
                        try:
                            os.fsync(dir_fd)
                        finally:
                            os.close(dir_fd)
                    else:
                        # Windows: skip directory fsync (file fsync is still performed)
                        # This is acceptable as Windows NTFS provides reasonable durability guarantees
                        logger.debug("Skipping directory fsync on Windows (O_DIRECTORY not available)")
                except (OSError, AttributeError) as e:
                    # Directory fsync failed - log but don't fail the save
                    logger.debug(f"Directory fsync failed: {e} (continuing with file fsync only)")

                logger.info(f"Config saved to {self.config_path}")
                return True

            except Exception as e:
                # Clean up temp file on error
                try:
                    temp_path.unlink(missing_ok=True)
                except:
                    pass
                raise e

        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False
    
    def get_log_dir(self) -> Path:
        """Get the log directory, creating it if needed."""
        log_dir = self._get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

