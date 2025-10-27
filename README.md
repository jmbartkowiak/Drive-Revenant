# Drive Revenant

A Windows-only GUI utility that keeps selected drives awake at safe, user-defined intervals using tiny read/write operations and strict jitter to avoid contention. Built for safety, clarity, and low overhead.

Please note that, ironically, the most out of date aspects of this system are the readme and version history. This will be rectified in the next few days, but running main.py or one of the .bat files (the debug version is for developers) after installing the necessary packages from requirements.txt to your python installation should get you started and much of the system is self-explanatory or includes extensive tooltips and other assistance.  You may need to manually enable your drives and adjust its interval time to between 6-15 seconds (for HDDs) or 30-40 seconds (for SSDs), but these settings will persist within your config file indefinitely.  New drives connected to the system should be automatically detected while disconnected drives are disabled (though not fully removed until they not been connected for 15d (another user-adjustable setting.)


This is my first fully functional application out of the gate, despite being at least twice as long as any other to this point, thanks to a Test-Driven Development approach and strict 'waterfall' development philosophy. 


## Key Features

### Safety First
- **Spacing rules**: minimum 0.5 s between any operations, 1.0 s between writes
- **HDD guard**: protective timing for mechanical drives (earlier-only offsets with small late slack)
- **Error budget**: automatic quarantine after consecutive failures
- **Lock retry**: graceful handling of file locks and antivirus interference
- **Durability bounds**: bounded flush times prevent UI stalls

### Intelligent Scheduling
- **500 ms grid-based timing** with monotonic clock and no drift
- **Deterministic tie-breaking** per install and day; collision packing (writes first, reads next)
- **Resume smoothing** when a drive or the app resumes from pause or sleep
- **Multi-drive collision handling** with stable ordering

### Advanced Controls
- **Global Pause/Resume** for all drives
- **Per-drive control** via context menu
- **Smart status updates** (GUI only updates on actual state changes)
- **Real-time monitoring** with clear countdowns and last-result tooltips

### User Experience
- **PySide6 GUI**: responsive table editing and system tray presence
- **Edit safety**: table refresh is incremental and will not clobber active edits
- **Status reasons**: clear policy explanations (battery, idle, global pause)
- **Diagnostics export** bundle for support

### Logging
- **Human-readable logs**: rotated text files with half-second indicators
- **NDJSON telemetry**: structured events for analysis tools
- **Performance metrics**: duration, outcome codes, and operation notes

### Modes
- **Standard mode** (default): uses user profile paths
- **Portable mode**: keeps config and logs next to the executable (ideal for removable drives)

## Quick Start

### Requirements
- Windows 10 or 11
- Python 3.8+ (tested on 3.10+)
- Dependencies: `PySide6`, `psutil`, `pywin32`

### Install
```bash
pip install -r requirements.txt
```

### Run

#### Standard mode (default)
```bash
python main.py
```
- Configuration: `%APPDATA%\DriveRevenant\config.json`
- Logs: `%APPDATA%\DriveRevenant\logs\`
- Autostart: Windows Task Scheduler

#### Portable mode
```bash
python main.py --portable
```
- Configuration and logs live beside the executable (self-contained)
- Autostart uses registry entries tied to the executable path (repair if moved)

## Usage

### Command line options
| Option | Description |
|---|---|
| `--portable` | Run in portable mode (config/logs beside executable) |
| `--no-autostart` | Disable autostart setup |
| `--fix-autostart` | Repair autostart entry and exit |
| `--debug` | Increase log verbosity |
| `--version` | Show version info |

### GUI overview
- **Drive table** with in-cell editing for interval and type
- **Status bar** with global countdown and policy status
- **Toolbar** for Pause/Resume all drives
- **System tray** for background operation

### Status indicators (text-only, accessible)
- Active (green in UI)
- Paused or Quarantine (yellow in UI)
- Disabled or Offline (red in UI)

### Per-drive context menu (right-click)
- Ping now
- Enable or Disable
- Pause or Resume
- Release from Quarantine
- Drive details

## Configuration

Configuration should automatically attempt to migrate from older versions or create a new .config if it is missing entirely. Defaults are safe. 

Key settings:

```json
{
  "version": 3,
  "install_id": "<uuid>",
  "portable": false,
  "autostart": true,
  "autostart_method": "scheduler",   // or "registry"
  "treat_unknown_as_ssd": true,

  "default_interval_sec": 20,
  "interval_min_sec": 3,
  "jitter_sec": 2,
  "hdd_max_gap_sec": 45,
  "deadline_margin_sec": 0.3,

  "pause_on_battery": true,
  "idle_pause_min": 0,
  "policy_precedence": ["global_pause", "battery", "idle", "per_drive_disable"],

  "fsync": true,
  "max_flush_ms": 150,
  "lock_retry_ms": 750,
  "error_quarantine_after": 5,
  "error_quarantine_sec": 60,

  "log_max_kb": 150,
  "log_history_count": 5,
  "log_ndjson": true,

  "gui_update_interval_ms": 500,
  "gui_update_interval_editing_ms": 1000,
  "hide_console_window": true,

  "disable_hotkeys": false,
  "suppress_quit_confirm": false,
  "suppress_ssd_warnings": {},

  "per_drive": {
    "E:": {"enabled": true, "interval": 120, "type": "HDD", "ping_dir": null}
  }
}
```

### Notes on performance settings
- **GUI update interval (normal)** controls background refresh cadence
- **GUI update interval (editing)** slows the cadence while a cell editor is open
- Changes apply immediately (no thread recreation)

### Console window
- When `hide_console_window` is true, the console will be hidden on startup

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Drive Revenant                       │
├─────────────────────────────────────────────────────────┤
│  main.py              - Application entry point         │
├─────────────────────────────────────────────────────────┤
│  app_config.py        - Configuration & autostart       │
│  app_core.py          - Core scheduling engine          │
│  app_io.py            - I/O operations & probing        │
│  app_logging.py       - Logging & telemetry             │
│  app_gui.py           - PySide6 user interface          │
│  app_types.py         - Types shared across modules     │
└─────────────────────────────────────────────────────────┘
```

**Core components**
- `CoreEngine`: monotonic timing, jitter placement, collision spacing
- `IOManager`: safe reads/writes to `X:\.drive_revenant\drive_revenant` with bounded flush
- `ConfigManager`: configuration management, portable mode, autostart helpers
- `LoggingManager`: human logs + NDJSON (`events.ndjson`), rotation
- `JitterPlanner`: deterministic grid scheduling and HDD protection
- GUI subsystems: table widget, status thread, settings, log viewer, diagnostics export

## Troubleshooting
- **Autostart issues**: use the in-app “Fix Autostart” repair flow
- **Drive locked**: operations skip as `SKIP_LOCKED` and the schedule continues
- **Sluggish UI**: increase `gui_update_interval_ms` or hide heavy columns
- **Unknown drive type**: enable `treat_unknown_as_ssd` to avoid unnecessary writes
- **Portable path moved**: run `--fix-autostart` after relocating the folder

## Security and Privacy
- No network access and no data exfiltration
- Minimal registry writes (autostart only, optional)
- Logs and NDJSON are local; disable or rotate per your policy

## Development

### Tests
```bash
pytest
pytest --cov=app_core --cov=app_config --cov=app_io
python test_basic.py
```

### Quality
```bash
black .
ruff check .
mypy .
```

## Updates (2025-10-17)
I would be remiss in failing to mention the ages-old application that inspired the basis for this system - even if it did once manage to corrupt one of my drives! I believe the name was something like Drive Killer or something similar, if even still extant somewhere.  I am certain the full name will return to me at some point so I can properly credit the fundamental concept of maintaining HDDs in a responsive state by preventing their auto-sleep routines.

### Critical Bug Fixes (PLAN 4)
- **Fixed scheduler loop crashes**: Resolved multiple critical crashes including undefined variable 'letter' in `_plan_operations_cached` that caused scheduler failures
- **Fixed parameter name mismatch**: Corrected `drive_letter` vs `letter` parameter inconsistency in `CoreEngine.set_drive_config` that caused GUI operations to fail
- **Fixed interval change detection**: Moved `old_interval` capture before config modification to properly detect interval changes
- **Fixed lambda variable capture**: Resolved NameError in GUI drive table by using `functools.partial` for proper variable binding in 7 signal connections
- **Fixed missing config parameter**: Updated all `ConfigManager.save_config()` calls to pass required config object
- **Fixed log rotation naming**: Implemented numbered-only log scheme (Log_current1.txt through Log_current5.txt) without bare current file

### Exit & Shutdown Improvements
- **Robust exit mechanism**: Added 10-second force exit timer with `os._exit(1)` fallback for unresponsive shutdown scenarios
- **Improved graceful shutdown**: Increased core engine stop timeout from 500ms to 2000ms for better cleanup
- **Shutdown state tracking**: Prevented multiple shutdown attempts with `_shutdown_in_progress` flag

### Configuration & Monitoring
- **CLI countdown interval**: Made CLI time remaining output interval configurable via config (default 15 seconds, config version 3 → 4)
- **Config schema migration**: Updated migration logic to handle new `cli_countdown_interval_sec` field

### Logging System Overhaul
- **Numbered log rotation**: Changed from Log_current.txt + backups to Log_current1.txt through Log_current5.txt scheme
- **Fixed rollover bugs**: Used standard `_open()` method to prevent AttributeError during log rotation
- **Directory creation**: Ensured logs directory is always created on initialization
- **Formatter access**: Made formatter an instance attribute for proper access across HumanLogger methods

### Comprehensive Integration Testing & Architectural Verification
- **Deep integration testing**: Created 4 comprehensive test suites with 40+ integration tests covering all architectural components
- **Architectural verification**: Confirmed all major changes work correctly (centralized timing, immutable snapshots, scheduler loop, GUI consumption)
- **Performance validation**: Verified new architecture maintains good performance (snapshots < 10KB, updates < 1s for 100 drives)
- **Thread safety**: Validated concurrent access safety across all architectural boundaries
- **Zero breaking changes**: All existing functionality preserved (49/49 tests passing across all test suites)

### Previous Bug Fixes and Improvements
- **Fixed GUI table rendering**: Corrected method name from `update_table()` to `update_drive_data()`
- **Fixed test suite imports**: Updated AutostartManager and IOResult imports after module reorganization
- **Fixed DriveSnapshot constructor**: Updated test compatibility for GUI integration
- **Fixed ConfigManager purity**: Corrected test expectations for initialization behavior
- **Improved HDD protection**: Increased `hdd_max_gap_sec` from 5 to 45 seconds for better HDD safety
- **Enhanced drive size display**: All real drives now show correct sizes in GUI
- **Verified countdown accuracy**: GUI countdown calculations working correctly for all drive states

## Version History
See [VERSION_HISTORY.md](VERSION_HISTORY.md) for the full system version log and chronological change history.
