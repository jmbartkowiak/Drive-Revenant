# Drive Revenant - System Version Log

> System version numbers are **project-level** milestones (not per-module file headers). Each version represents a coherent set of changes focused on keeping drives active and preventing sleep mode.

## Core Purpose

Drive Revenant prevents drives from entering sleep mode by performing tiny read/write operations at safe intervals. This eliminates data access latency that occurs when drives must wake from sleep states, ensuring instant file access.

## v3.4.0 · Scheduler Rewrite, Cleanup & Packaging (2026-08-12)

### Architecture
- **Single source of truth**: `Scheduler` owns all drive timing/state in `_drive_timing` and publishes immutable `StatusSnapshot`s under a lock.
- **JitterPlanner**: The effective interval (min-clamped, HDD-capped) is derived without mutating the user's configured interval; operations are placed with deterministic jitter and spacing.
- **Legacy API removal**: Dropped the old `drive_states` dictionary, `_get_status_snapshot`, and `write_keep_alive_file` paths; all consumers now read `get_all_drive_states()` / `get_snapshot()`.
- **Dead code removal**: Removed unused scheduler helpers and stale GUI paths (`app_core.py`, `app_gui.py`).

### Packaging
- **Single version source**: Version now lives in `app_version.py` (`__version__ = "3.4.0"`).
- **PyInstaller spec**: Added `assets/icon.ico` and `assets/version_info.txt`; the tray PNGs are bundled and resolved via `_MEIPASS` when frozen (`_icon_path`). Fixed the spec to resolve paths via `SPECPATH` (spec files are exec'd, so `__file__` is undefined); a onefile build was verified end-to-end.

### Logging
- **Debug handler shutdown**: `LoggingManager.shutdown()` now closes the debug logger's file handler, releasing the `debug.log` lock on Windows.

### Drive type detection (no PowerShell)
- Replaced the `get_drive_types.ps1` string-matching script with an in-process,
  no-admin detection chain in `app_io.py`: `GetDriveTypeW` for the coarse type,
  then `DeviceIoControl` `IOCTL_STORAGE_QUERY_PROPERTY` seek-penalty/bus-type
  queries on `\\.\PhysicalDriveN`, a WMI `MSFT_PhysicalDisk.MediaType` fallback,
  and a model/friendly-name heuristic for USB/SCSI enclosures.
- Removes the PowerShell dependency (AppLocker / constrained-language-mode safe).

### SAFE mode (write gate)
- New `simulate_writes` config flag (default `true`) plus a **SAFE** checkbox in the
  bottom-left of the window. When checked, `perform_operation` simulates every operation
  and writes nothing to drives; uncheck it to enable real drive pings.
- The SAFE toggle is large and red while safe (green when live), and is forced visible
  so status-bar messages can't hide it.

### Test suite cleanup
- **Archived legacy tests**: Moved stale tests referencing the pre-`drive_states`/`_get_status_snapshot` APIs, script-style verification files, and removed-API GUI tests to `archive/legacy_tests/`.
- **Current suite**: `tests/` now holds only the current, passing suite (254 tests: 240 fast + 14 slow, all green). The slow suite dropped from ~110 s to ~11 s once the PowerShell drive-detection shell-out was removed.
- **Multi-drive quarantine test**: Implemented the previously-skipped `test_full_cycle_with_multiple_drives` to verify per-drive countdown independence.

### Review & hardening pass
- Fixed autostart to point at the real exe (`get_exe_path()`) instead of a
  `ConfigManager` repr; XML-escaped the Task Scheduler path.
- Made full-rescan and stale-drive removal clear scheduler state under the lock
  (`Scheduler.clear_all()` / `remove_drive()`).
- Hardened the GUI status thread (snapshot errors no longer kill it; bounded stop wait).
- Portable mode now anchors config/logs to `sys.executable`'s dir when frozen.
- Config load tolerates unknown `per_drive` keys; failure classification prefers
  `exception.winerror`; idle detection uses unsigned tick math; WD SSD name markers added.
- Manual verification items captured in `USER-TODO.md`.

## v3.3.2 · Countdown & Interval Fixes (2025-10-25)

### Exponential Quarantine System
- **Smart backoff**: Implements exponential quarantine backoff (30s × 2^n, up to 2^11 ≈ 21 days) for drives with repeated failures
- **Quarantine counter**: Tracks quarantine attempts (0-11) per drive, resets on successful operation
- **Permanent removal**: Drives at max quarantine (11) that remain stale for extended periods are permanently removed
- **Status clarity**: Quarantine status clearly indicates "not currently accessible" rather than "permanently gone"

### Countdown Display Improvements
- **"Due now" display**: Shows "Due now" instead of "0s" or "-" when next operation is <1 second away
- **Countdown restart fix**: Fixed issue where countdowns would stop at default interval values
- **Planning cycle fixes**: Corrected `_plan_operations` to handle past-due operations and re-plan correctly
- **Execution timing**: Fixed `_execute_due_operations` to properly clear `next_due_at` after execution

### Interval Override Fix
- **HDD protection**: Increased `hdd_max_gap_sec` from 5.0s to 300.0s (5 minutes) to respect configured intervals
- **Interval respect**: Configured intervals are no longer overridden by aggressive HDD guard logic
- **Effective interval**: Fixed calculation to properly use configured intervals for both HDD and SSD drives

### Full Rescan Feature
- **Complete reset**: Added "Full Rescan (Clear All)" menu option to completely reset drive configurations
- **Fresh scan**: Clears all existing drives and performs a complete fresh scan of available drives
- **State reset**: Resets scheduler state, timing states, and scheduled operations for clean slate

### System Tray Fix
- **Exit functionality**: Fixed exit from system tray menu to properly quit the application
- **Menu action**: Changed from `self.close()` to `self.do_quit()` for proper shutdown

### Architecture Migration
- **Scheduler-based**: Complete migration to centralized scheduler as single source of truth
- **Drive state**: All drive state now managed by `Scheduler` with `DriveTimingState` dataclass
- **Removed deprecated**: Eliminated all references to old `drive_states` dictionary
- **Method updates**: Updated `main.py` and all modules to use scheduler-based approach

### Component Versions
- app_core.py: v2.0.7
- app_types.py: v2.0.3
- app_gui_drive_table.py: v2.0.2
- app_config.py: v1.1.5

## v3.1.0 · Critical Bug Fixes & Stability (2025-10-11)

### Scheduler Loop Crash Fixes
- **Fixed undefined variable**: Resolved `'letter'` undefined in `_plan_operations_cached` causing repeated scheduler failures
- **Parameter name fix**: Corrected `drive_letter` vs `letter` inconsistency in `CoreEngine.set_drive_config`
- **Interval change detection**: Fixed `old_interval` capture timing to properly detect configuration changes
- **Lambda variable capture**: Resolved NameError in GUI drive table using `functools.partial` for signal connections

### Exit & Shutdown Improvements
- **Robust exit mechanism**: Added 10-second force exit timer with `os._exit(1)` fallback for unresponsive shutdowns
- **Improved graceful shutdown**: Increased core engine stop timeout from 500ms to 2000ms
- **Shutdown state tracking**: Prevented multiple shutdown attempts with `_shutdown_in_progress` flag

### Logging System Overhaul
- **Numbered log rotation**: Changed from `Log_current.txt` to numbered scheme (`Log_current1.txt` through `Log_current5.txt`)
- **Fixed rollover bugs**: Used standard `_open()` method to prevent AttributeError during rotation
- **Directory creation**: Ensured logs directory is always created on initialization

### Configuration & Monitoring
- **CLI countdown configuration**: Made CLI time remaining output interval configurable via `cli_countdown_interval_sec` (default 15s)
- **Config schema migration**: Updated config version 3 → 4 with migration logic

### Component Versions
- app_core.py: v1.1.11
- app_gui.py: v1.1.9
- app_gui_drive_table.py: v1.1.10
- app_logging.py: v1.0.3
- app_config.py: v4
- main.py: v1.0.4

## v3.0.0 · Pause and Policy (2025-10-11)

### Pause System Improvements
- **Standardized pause reasons**: user, global, battery, idle, none
- **User intent preserved**: Global pause no longer overrides user-paused drives
- **Pause state reset**: Fixed pause state reset on drive enable/disable
- **Pause all button toggle**: Fixed button state to reflect actual pause status
- **Disabled drive display**: Fixed display of disabled drives in GUI

### CLI and Console Fixes
- **CLI random pausing**: Fixed CLI randomly pausing drives
- **User-paused drives reverting**: Fixed user-paused drives reverting to active
- **Windows console QuickEdit**: Disabled to prevent accidental runtime pause

## v2.8.0 - v2.8.9 · Pause and Policy (2025-10-10)

### Consistency & Stability
- **Parameter order consistency**: Verified across all modules
- **Deprecated code cleanup**: Completed removal of deprecated methods
- **Memory management**: Verified reasonable usage across all components
- **Error and exit handling**: Confirmed robust error handling and graceful exit

## v2.7.0 - v2.7.7 · Scheduler and Timing (2025-10-10)

### Critical Fixes
- **ConfigManager purity**: Verified no side effects
- **Critical scheduler bug**: Fixed major scheduling issues
- **DriveSnapshot constructors**: Updated for compatibility

## v2.6.0 - v2.6.7 · Testing and Verification (2025-10-10)

### Comprehensive Testing
- **Deep integration testing**: Completed comprehensive test coverage
- **Architectural verification**: Confirmed all major components work correctly
- **Performance validation**: Verified performance characteristics
- **Thread safety**: Verified concurrent access safety
- **Drive detection**: Working correctly (6 real drives detected)

## v2.5.0 - v2.5.4 · Foundations (2025-10-09)

### Improvements
- **HDD protection**: Increased `hdd_max_gap_sec` from 5 to 45 seconds
- **Drive size display**: All real drives now show correct sizes in GUI
- **Countdown accuracy**: Verified GUI countdown calculations working correctly

## v2.4.0 - v2.4.8 · Data Integrity and Logging (2025-10-09)

### Monitoring & Configuration
- **CLI monitoring**: Made CLI time remaining output interval configurable (default 15 seconds)
- **GUI table rendering**: Fixed method name from `update_table()` to `update_drive_data()`
- **Test suite imports**: Updated after module reorganization

## v2.3.0 - v2.3.5 · Scheduler and Timing (2025-10-09)

### Architecture Verification
- **Deep integration testing**: Created 4 comprehensive test suites with 40+ integration tests
- **Architectural verification**: Confirmed centralized timing, immutable snapshots, scheduler loop
- **Performance validation**: Verified architecture maintains good performance
- **Thread safety**: Validated concurrent access safety

## v2.2.0 - v2.2.6 · Scheduler and Timing (2025-10-08)

### Critical Fixes
- **Scheduler loop crashes**: Fixed `AttributeError: 'CoreEngine' object has no attribute 'getstatus_snapshot'`
- **Parameter order issues**: Corrected DriveSnapshot constructor calls
- **Deprecated method calls**: Replaced all references to deprecated methods
- **Enhanced type hints**: Added proper type hints for configuration fields

## v2.1.0 - v2.1.9 · GUI and UX (2025-10-08)

### User Experience
- **Thread safety**: Validated concurrent access safety
- **Error handling**: Confirmed robust error handling
- **Memory management**: Verified reasonable memory usage
- **Zero breaking changes**: All existing functionality preserved (49/49 tests passing)

## v2.0.0 - v2.0.6 · Scheduler and Timing (2025-10-08)

### Major Architectural Changes
- **Test suite fixes**: Updated tests for new architecture
- **Version updates**: Bumped core modules to new versions
- **Critical bug fix**: Resolved repeated AttributeError crashes in scheduler loop
- **Comprehensive integration testing**: Created 4 comprehensive test suites with 40+ tests
- **Architectural verification**: Verified all major changes work correctly
- **Performance validation**: Confirmed good performance characteristics

## v1.9.0 - v1.9.8 · Pause and Policy (2025-10-07)

### Code Quality
- **Deprecated code cleanup**: Fixed remaining references to deprecated methods
- **Parameter order fixes**: Corrected DriveSnapshot constructor calls
- **Type hint improvements**: Enhanced type hints across modules
- **Naming consistency**: Verified all variable and method names follow conventions

## v1.8.0 - v1.8.4 · Scheduler and Timing (2025-10-07)

### Scheduling Improvements
- **Execute-then-plan loop**: Fixed scheduler execution order
- **Next due enforcement**: Enforce `next_due ≥ now + 0.5s` to end 0-2s flicker
- **Status cadence**: 1s status update cadence
- **CLI summary**: 30s CLI "Next due" summary

### GUI & Config
- **Incremental table refresh**: Non-destructive table refresh
- **Edit protection**: Strict edit-protection during refresh
- **Config save optimization**: Eliminated save-storms (single write per logical change)
- **Drive scans**: Batch PowerShell probing per scan

### Runtime
- **Console window**: New `hide_console_window` (default true) with migration
- **Quieter startup**: Reduced startup noise

## v1.7.0 - v1.7.7 · Pause and Policy (2025-10-07)

### Documentation & Performance
- **Tone and versioning**: Clarified conventions separating system versions from module headers
- **Performance metrics**: Status updates ~<50ms; memory ~<50MB; cached scans ~<2s for 5 drives
- **Cache TTLs**: Drive info 30s; volume info 60s; policy state 5s
- **Error taxonomy**: Detailed quarantine triggers and recovery steps
- **Security/ops**: Minimal privileges; registry only for autostart; no network; no data exfiltration

## v1.6.0 - v1.6.4 · GUI and UX (2025-10-06)

### Documentation
- **Critical issues**: Identified duplicate init paths; missing PS script; version inconsistencies
- **Success metrics**: Established production readiness checklist
- **Clean formatting**: Standardized headings, lists, and code blocks for accessibility
- **Quick Start**: Rewrote with explicit Standard vs Portable flows

## v1.5.0 - v1.5.9 · GUI and UX (2025-10-06)

### Drive Detection
- **Unit tests**: Updated for normalized drive-letter convention
- **Drive-letter standards**: Documented and updated detection rules
- **Version snapshot**: Captured current file versions for cross-checking
- **User-visible impacts**: Faster GUI, accurate size/type, consistent behavior

## v1.4.0 - v1.4.6 · Scheduler and Timing (2025-10-06)

### GUI & Config
- **GUI behavior**: Global countdown in status bar; tooltips with last 3 results
- **Config migration**: Config v3 fields and branding migration (`KeepAlivePy` → `DriveRevenant`)
- **GUI performance**: New settings `gui_update_interval_ms` (default 500) and `gui_update_interval_editing_ms` (default 1000)
- **Status thread**: Auto-restarts when intervals change; 2× faster default refresh
- **Drive-letter normalization**: Fixed sizing/lookup inconsistencies

## v1.3.0 - v1.3.4 · Scheduler and Timing (2025-10-06)

### Scheduling Specification
- **Module layout**: Locked in module layout and public interfaces
- **Scheduling**: Fully specified monotonic clock, resume smoothing, canonical cadence with no drift
- **Deterministic tie-break**: Daily tie-break using per-install `install_id` + local date
- **HDD guard**: Effective interval cap, earlier-only offsets with tiny late slack
- **I/O semantics**: Bounded flush via `max_flush_ms`, `SKIP_LOCKED` without shifting schedule

## v1.2.0 - v1.2.7 · GUI and UX (2025-10-05)

### User Experience
- **Startup banner**: Surfaces missing/broken autostart with one-click fix
- **Stable row order**: Header sorting disabled by default to prevent jumpy tables
- **In-cell editing**: Guard rails to avoid clobbering active edits
- **System tray**: Normalized presence/behavior across sessions
- **Keyboard navigation**: Improved focus handling for faster edits
- **Tooltips**: Added microcopy in Settings to clarify options

## v1.1.0 - v1.1.6 · Scheduler and Timing (2025-10-05)

### Features
- **Diagnostics export**: Bundle (config snapshot, logs, NDJSON sample) from UI
- **Log levels**: Sharpened retention guidance for support scenarios
- **Autostart**: Default via Task Scheduler; resilient repair flow
- **Portable mode**: Registry-based autostart fallback; config and logs beside executable
- **Command-line flags**: `--portable` and `--debug` documented and respected

## v1.0.0 - v1.0.6 · Data Integrity and Logging (2025-10-05)

### Error Handling & Configuration
- **Error handling**: `error_quarantine_after`/`error_quarantine_sec` for repeated failures
- **Toggle**: `treat_unknown_as_ssd` to avoid unnecessary writes on ambiguous media
- **Per-drive overrides**: `enabled`, `interval`, `type`, `ping_dir` formalized
- **NDJSON schema**: Stabilized event schema for external analysis
- **Log rotation**: Hardened via `log_max_kb` and `log_history_count`

## v0.9.0 - v0.9.7 · Scheduler and Timing (2025-10-04)

### Configuration & Policy
- **Single-instance**: Enforcement and clean shutdown verified
- **Schema v3**: Expanded keys documented and enforced
- **Policy precedence**: Clarified (global pause, then battery, then idle, then per-drive disable)
- **Pause controls**: `pause_on_battery` and `idle_pause_min` with safe defaults
- **Durability controls**: `fsync`, bounded flush (`max_flush_ms`), and `lock_retry_ms`

## v0.8.0 - v0.8.4 · Testing and Verification (2025-10-04)

### Documentation & Build
- **README**: Usage instructions aligned with packaging outputs
- **Version metadata**: Conventions documented for future builds
- **CI workflow**: GitHub Actions established for build and tests
- **Requirements**: Normalized and reproducible installs documented

## v0.7.0 - v0.7.4 · Scheduler and Timing (2025-10-04)

### Autostart & UI
- **Autostart plumbing**: Task Scheduler preferred; Registry fallback for portable
- **Import graph**: Strengthened and removed redundant init paths
- **Global Pause/Resume**: Toolbar and per-drive context controls
- **Status feedback**: Immediate, clearer feedback on actions
- **Visual polish**: Status indicators and table sizing/formatting

## v0.6.0 - v0.6.6 · Scheduler and Timing (2025-10-04)

### Features
- **Error budget**: Tracking and quarantine thresholds wired into scheduler
- **Diagnostics export**: Flow added to GUI
- **Policy precedence**: Clarified with interval clamping and status indication
- **Config v3 migration**: Atomic save + backups, integrity verification, and repair
- **Main entry**: Single-instance mutex, `--debug` flag, clearer startup errors/help
- **Logging**: Improved NDJSON schema, better rotation, timing/metadata fields

## v0.5.0 - v0.5.7 · Scheduler and Timing (2025-10-03)

### Scheduling
- **JitterPlanner**: Introduced with 500ms grid and deterministic BLAKE2s tie-breaks
- **Spacing rules**: Enforced (0.5s any-any, 1.0s write-write) and HDD-guard earlier-only offsets
- **Collision packing**: Multi-drive collision packing (writes first, reads next) with overflow handling
- **Logging**: Half-second timing indicators and tie-break metadata in human logs

## v0.4.0 - v0.4.4 · Scheduler and Timing (2025-10-03)

### GUI & Features
- **System tray**: Integration for background operation; notifications wired
- **Settings dialog**: Covering key configuration values with validation
- **Real-time countdown**: "Next in" countdown column and basic keyboard navigation
- **Change detection**: Hash-based so GUI updates only on state changes
- **Pause/Resume**: Global & per-drive wired into policy engine
- **Quarantine**: Retry system for transient I/O failures with bounded backoff

## v0.3.0 - v0.3.7 · Pause and Policy (2025-10-03)

### Status & Policy
- **DriveStatus**: Introduced (incl. `PAUSED`) and `PolicyState` to unify GUI/core semantics
- **Operation enums**: Expanded and status snapshot schema for stable GUI/log consumption
- **Policy precedence**: Clarified (global pause → battery → idle → per-drive disable)
- **PySide6 interface**: Drive table with in-cell editing and color/status indicators
- **Context menu**: Actions for per-drive pause/resume and details

## v0.2.0 - v0.2.4 · Data Integrity and Logging (2025-10-02)

### Testing
- **Basic functionality tests**: Core scheduling, I/O safety, config load/save
- **Real-drive smoke tests**: External media and import-graph verification
- **CI runner scripts**: Minimal scripts for local Windows runs
- **NDJSON schema**: Sanity checks and log rotation assertions
- **Failure-mode assertions**: `SKIP_LOCKED`, timeouts, and partial flush

## v0.1.0 - v0.1.8 · Foundations (2025-10-02)

### Initial Implementation
- **First runnable baseline**: Basic config management and path layout
- **Initial scheduler loop**: Fixed cadence and early jitter spacing
- **I/O groundwork**: Safe write with temporary file + atomic move; basic lock retry/backoff
- **Device probing**: Volume information collection with WMI/PowerShell helpers
- **Error taxonomy**: Scaffolded (OK / SKIP_LOCKED / ERROR) and human logs created
- **Test scaffolding**: Basic unit tests and real-drive smoke tests
