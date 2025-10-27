# Drive Revenant - System Version Log

> System version numbers below are **project‑level** milestones (not the per‑module file headers). Each version change covers (roughly) 10 minor changes or bugfixes done in a given session on a given day.

## v0.1.0 - v0.1.8 · Foundations · 2025-10-02
- First runnable baseline with basic config management and path layout for `%APPDATA%/DriveRevenant` and portable mode directories
- Initial scheduler loop with fixed cadence and early jitter spacing (~0.5s any‑any, ~1.0s write‑write)
- I/O groundwork: safe write with temporary file + atomic move; basic lock retry/backoff
- Device probing and volume information collection with early WMI/PowerShell helpers
- Error taxonomy scaffolded (OK / SKIP_LOCKED / ERROR) and human logs created
- Test scaffolding: basic unit tests and real‑drive smoke tests

## v0.2.0 - v0.2.4 · Data Integrity and Logging · 2025-10-02
- Basic functionality tests for core scheduling, I/O safety, and config load/save
- Real‑drive smoke tests with external media and import‑graph verification
- Minimal CI runner scripts for local Windows runs (e.g., `test.bat`, `run.bat`)
- NDJSON schema sanity checks and log rotation assertions
- Failure‑mode assertions for `SKIP_LOCKED`, timeouts, and partial flush
- Scaffold for pytest fixtures and environment bootstrap

## v0.3.0 - v0.3.7 · Pause and Policy · 2025-10-03
- Introduced `DriveStatus` (incl. `PAUSED`) and `PolicyState` to unify GUI/core semantics
- Expanded operation enums and status snapshot schema for stable GUI/log consumption
- Clarified policy precedence (global pause → battery → idle → per‑drive disable)
- Added docstrings and comments to types for maintainability
- Built PySide6 interface: drive table with in‑cell editing and color/status indicators
- Context menu actions for per‑drive pause/resume and details

## v0.4.0 - v0.4.4 · Scheduler and Timing · 2025-10-03
- System tray integration for background operation; notifications wired
- Settings dialog covering key configuration values with validation
- Real‑time “Next in” countdown column and basic keyboard navigation
- Hash‑based change detection so GUI updates only on state changes (reduced churn)
- Global & per‑drive pause/resume wired into policy engine (battery/idle/global)
- Quarantine & retry system for transient I/O failures with bounded backoff

## v0.5.0 - v0.5.7 · Scheduler and Timing · 2025-10-03
- Optimized status emission path; immediate feedback after control actions
- Better error recovery and clearer logging around device disappearance
- Introduced `JitterPlanner` with a 500 ms grid and deterministic BLAKE2s tie‑breaks
- Enforced spacing rules (0.5 s any‑any, 1.0 s write‑write) and HDD‑guard earlier‑only offsets
- Multi‑drive collision packing (writes first, reads next) with overflow handling
- Half‑second timing indicators and tie‑break metadata in human logs

## v0.6.0 - v0.6.6 · Scheduler and Timing · 2025-10-04
- Error budget tracking and quarantine thresholds wired into scheduler
- Diagnostics export flow added to the GUI; clearer status countdown behavior
- Policy precedence clarified, with interval clamping and status indication
- Config v3 migration with atomic save + backups, integrity verification, and repair
- Main: single‑instance mutex, `--debug` flag, clearer startup errors/help
- Logging: improved NDJSON schema, better rotation, and timing/metadata fields

## v0.7.0 - v0.7.4 · Scheduler and Timing · 2025-10-04
- Autostart plumbing set up (Task Scheduler preferred; Registry fallback for portable)
- Strengthened import graph and removed redundant init paths in entry flow
- Global Pause/Resume toolbar and per‑drive context controls
- Immediate, clearer status feedback on actions; better UX responsiveness
- Visual polish on status indicators and table sizing/formatting
- Minor fixes to keep rows stable during refresh

## v0.8.0 - v0.8.4 · Testing and Verification · 2025-10-04
- README usage instructions aligned with packaging outputs; installer track stubbed (signing TBD)
- Version metadata conventions documented for future builds
- GitHub Actions CI workflow established for build and tests
- Requirements normalized and reproducible installs documented

## v0.9.0 - v0.9.7 · Scheduler and Timing · 2025-10-04
- Single‑instance enforcement and clean shutdown verified under packaged runs
- Local runner scripts kept for parity with CI and release prep
- Expanded schema v3 keys documented and enforced: `defaultintervalsec`, `intervalminsec`, `jittersec`, `hddmaxgapsec`, `deadlinemarginsec`
- Clarified policy precedence (global pause, then battery, then idle, then per‑drive disable) and surfaced policy reasons in status
- Added `pauseonbattery` and `idlepausemin` controls with safe defaults
- Introduced durability controls: `fsync`, bounded flush (`maxflushms`), and `lockretryms`

## v1.0.0 - v1.0.6 · Data Integrity and Logging · 2025-10-05
- Error handling extensions: `errorquarantineafter`/`errorquarantinesec` for repeated failures
- Toggle to `treatunknownas_ssd` to avoid unnecessary writes on ambiguous media
- Per‑drive overrides (`enabled`, `interval`, `type`, `ping_dir`) formalized
- NDJSON event schema stabilized (timestamp, drive, operation, outcome, latency, notes) for external analysis
- Log rotation hardened via `logmaxkb` and `loghistorycount`; consistent timestamp formats
- Human‑readable logs improved for triage; mapped error classes to concise messages

## v1.1.0 - v1.1.6 · Scheduler and Timing · 2025-10-05
- Added diagnostics export bundle (config snapshot, logs, NDJSON sample) from the UI
- Sharpened log levels and retention guidance for support scenarios
- Default autostart via Task Scheduler; resilient repair flow; naming conventions standardized
- Registry‑based autostart fallback when running in portable mode
- Portable mode keeps `config.json` and logs beside the executable
- Command‑line flags: `--portable` and `--debug` documented and respected consistently

## v1.2.0 - v1.2.7 · GUI and UX · 2025-10-05
- Startup banner surfaces missing/broken autostart with a one‑click fix
- Stable row order during refresh; header sorting disabled by default to prevent jumpy tables
- In‑cell editing guard rails to avoid clobbering active edits
- System tray presence/behavior normalized across sessions
- Keyboard navigation and focus handling improved for faster edits
- Tooltips and microcopy added in Settings to clarify effects of key options

## v1.3.0 - v1.3.4 · Scheduler and Timing · 2025-10-06
- Table column sizing tweaked for common resolutions
- Locked in module layout (`appgui`, `appcore`, `appconfig`, `appio`, `applogging`, `apptypes`) and public interfaces; Plan 7 supersedes Plan 6
- Scheduling is fully specified: monotonic clock, resume smoothing (`now + min(2 s, 0.5×interval)`), canonical cadence `t_nom(k)` with no drift
- Deterministic daily tie‑break using per‑install `installid` + local date; same‑tick set packing (writes first, reads next) with NDJSON `tieepoch`, `tierank`, and `packsize` fields
- HDD guard: effective interval cap, earlier‑only offsets with tiny late slack, and a per‑install stable phase snapped to the 0.5 s grid at enable
- I/O semantics finalized: bounded flush via `maxflushms` (PARTIALFLUSH), `SKIPLOCKED` without shifting schedule, default target file `driverevenant` in `X:\.driverevenant\`

## v1.4.0 - v1.4.6 · Scheduler and Timing · 2025-10-06
- GUI behavior consolidated: global countdown in status bar; tooltips with last 3 results; SSD write warning persistence; autostart integrity banner; Exit to Tray/Quit All semantics; hotkey disable option; diagnostics export
- Config v3 fields and branding migration (`KeepAlivePy` → `DriveRevenant`) made authoritative
- New GUI performance settings: `guiupdateintervalms` (default 500) and `guiupdateintervalediting_ms` (default 1000) with UI ranges (100ms-5s normal, 200ms-10s editing)
- StatusUpdateThread auto‑restarts when intervals change; 2× faster default refresh (500ms vs 1000ms)
- Drive‑letter normalization across engine/GUI/tests (`"E"` vs `"E:"`) to fix sizing/lookup inconsistencies
- Type detection simplified: NVMe→SSD; SDXC+removable→Removable; `SCSI`/`HDD` tokens→HDD; else Unknown (optionally treat as SSD)

## v1.5.0 - v1.5.9 · GUI and UX · 2025-10-06
- Unit tests updated for normalized drive‑letter convention; current file headers bumped to reflect work
- Audited Plan/README/updates and flagged missing GUI performance settings in schema/docs
- Documented drive‑letter standards and updated detection rules for docs
- Captured a current file versions snapshot for cross‑checking code headers
- Recorded user‑visible impacts: faster GUI, accurate size/type, consistent behavior
- Outlined a Files‑to‑Update list and alignment tasks for next push

## v1.6.0 - v1.6.4 · GUI and UX · 2025-10-06
- Identified critical issues: duplicate init paths; missing PS script; version inconsistencies
- Established success metrics and production readiness checklist
- Cleaned emoji/special characters; standardized headings, lists, and code blocks for accessibility
- Rewrote Quick Start with explicit Standard vs Portable flows and exact commands
- Added guidance for comparison tables and concise feature bullets
- Proposed stable updates.md structure: Version Overview + Detailed Changelog (+ optional Architecture & Dependencies)

## v1.7.0 - v1.7.7 · Pause and Policy · 2025-10-07
- Clarified tone and versioning conventions to separate system versions from module file headers
- Restated Phase 1-3 completion and Phase 4-5 status with actionable checklists
- Captured performance metrics: status updates ~<50ms; memory ~<50MB; cached scans ~<2s for 5 drives; adaptive GUI refresh (500ms normal / 1000ms editing)
- Documented cache TTLs: drive info 30s; volume info 60s; policy state 5s; incremental status with change detection
- Detailed error taxonomy and quarantine triggers (e.g., 3 consecutive failures → quarantine) with recovery steps
- Security/ops: minimal privileges; registry only for autostart; no network; no data exfiltration

## v1.8.0 - v1.8.7 · Scheduler and Timing · 2025-10-07
- Reiterated remaining work: GUI automation (pytest‑qt), integration/perf validation, packaging & release notes, docs pass
- Scheduler: execute‑then‑plan loop; enforce `next_due ≥ now + 0.5s` to end 0-2s flicker; 1s status cadence; 30s CLI "Next due" summary
- GUI: incremental, non‑destructive table refresh; strict edit‑protection; disabled header sorting; guarded `itemChanged` connection; no redundant startup rescan
- Config: eliminate save‑storms (single write per logical change using live in‑memory config during edits)
- Drive scans: batch PowerShell probing per scan; short prefetch cache; remove GUI‑triggered duplicate startup scan
- Runtime: new `hideconsolewindow` (default true) with migration; quieter startup

## v1.9.0 - v1.9.8 · Pause and Policy · 2025-10-07
- Component snapshot (for reference): Core 0.2.1, GUI 0.2.6, I/O 0.2.1, Config 0.1.9, Main 0.1.8
- Deprecated code cleanup: Fixed remaining references to deprecated `getstatus_snapshot()` method in CoreEngine
- Parameter order fixes: Corrected DriveSnapshot constructor calls in test files with missing `effectiveintervalsec` parameter
- Type hint improvements: Enhanced `appconfig.py` with proper `List[str]` type hint for `policyprecedence` field
- Naming consistency audit: Verified all variable and method names follow Python conventions across all modules
- Cross-module integration: Confirmed all method calls use correct parameter order and named parameters where appropriate

## v2.0.0 - v2.0.6 · Scheduler and Timing · 2025-10-08
- Test suite fixes: Updated `TESTguisnapshot_mapping.py` to use correct DriveSnapshot constructor signature
- Version updates: Bumped `appcore.py` to v1.1.1 and `appconfig.py` to v1.1.1
- Critical bug fix: Resolved repeated AttributeError crashes in scheduler loop that were flooding logs
- Comprehensive integration testing: Created 4 comprehensive test suites (TESTdeepintegrationarchitecture.py, TESTapplicationlifecycle.py, TESTguiintegrationcomprehensive.py, TESTsystemintegration_complete.py) with 40+ deep integration tests
- Architectural verification: Verified all major architectural changes work correctly across the entire codebase (centralized timing, immutable snapshots, scheduler loop, GUI consumption, HDD logic, ConfigManager purity)
- Performance validation: Confirmed new architecture maintains good performance characteristics (snapshots < 10KB, updates < 1s for 100 drives)

## v2.1.0 - v2.1.9 · GUI and UX · 2025-10-08
- Thread safety verification: Validated concurrent access safety across all architectural boundaries
- Error handling robustness: Confirmed system handles errors gracefully while maintaining stability
- Memory management: Verified reasonable memory usage and proper cleanup (snapshots < 100KB, GUI < 50KB)
- Zero breaking changes: Confirmed all existing functionality preserved (49/49 tests passing across all test suites)
- CLI monitoring improvement: Reduced CLI time remaining output interval from 30 seconds to 15 seconds for better monitoring
- System versions group coherent user‑visible behavior and architectural steps; individual file headers (for example, `app_gui.py 0.2.x`) may advance between system releases

## v2.2.0 - v2.2.6 · Scheduler and Timing · 2025-10-08
- If additional timestamped sources are provided, they will be integrated at the appropriate point in the sequence (and may introduce intermediary system versions if warranted)
- Fixed scheduler loop crashes: Resolved repeated `AttributeError: 'CoreEngine' object has no attribute 'getstatus_snapshot'` errors that were flooding logs
- Fixed parameter order issues: Corrected DriveSnapshot constructor calls in test files with missing `effectiveintervalsec` parameter
- Fixed deprecated method calls: Replaced all remaining references to deprecated `getstatussnapshot()` with `getstatus_snapshot()`
- Enhanced type hints: Added proper `List[str]` type hint for `policyprecedence` field in `appconfig.py`
- Naming consistency audit: Verified all variable and method names follow Python conventions across all modules

## v2.3.0 - v2.3.5 · Scheduler and Timing · 2025-10-09
- Cross-module integration: Confirmed all method calls use correct parameter order and named parameters
- Test suite fixes: Updated `TESTguisnapshot_mapping.py` to use correct DriveSnapshot constructor signature
- Deep integration testing: Created 4 comprehensive test suites with 40+ integration tests covering all architectural components
- Architectural verification: Confirmed all major changes work correctly (centralized timing, immutable snapshots, scheduler loop, GUI consumption)
- Performance validation: Verified new architecture maintains good performance (snapshots < 10KB, updates < 1s for 100 drives)
- Thread safety: Validated concurrent access safety across all architectural boundaries

## v2.4.0 - v2.4.8 · Data Integrity and Logging · 2025-10-09
- Error handling: Confirmed system handles errors gracefully while maintaining stability
- Memory management: Verified reasonable memory usage (snapshots < 100KB, GUI < 50KB)
- Zero breaking changes: All existing functionality preserved (49/49 tests passing across all test suites)
- CLI monitoring improvement: Made CLI time remaining output interval configurable (default 15 seconds, not accessible via GUI) for better monitoring flexibility
- Fixed GUI table rendering: Corrected method name from `updatetable()` to `updatedrive_data()`
- Fixed test suite imports: Updated AutostartManager and IOResult imports after module reorganization

## v2.5.0 - v2.5.4 · Foundations · 2025-10-09
- Fixed DriveSnapshot constructor: Updated test compatibility for GUI integration
- Fixed ConfigManager purity: Corrected test expectations for initialization behavior
- Improved HDD protection: Increased `hddmaxgap_sec` from 5 to 45 seconds for better HDD safety
- Enhanced drive size display: All real drives now show correct sizes in GUI
- Verified countdown accuracy: GUI countdown calculations working correctly for all drive states

## v2.6.0 - v2.6.7 · Testing and Verification · 2025-10-10
- Deep integration testing completed
- Architectural verification passed
- Performance validation complete
- Thread safety verified
- Drive detection working (6 real drives detected)

## v2.7.0 - v2.7.7 · Scheduler and Timing · 2025-10-10
- ConfigManager purity verified
- Critical scheduler bug fixed
- DriveSnapshot constructors updated

## v2.8.0 - v2.8.9 · Pause and Policy · 2025-10-10
- Parameter order consistency verified across all modules
- Deprecated code cleanup completed
- Memory management verified (reasonable usage across all components)
- Error and Exit handling robustness confirmed (system handles errors and exit gracefully)

## v3.0.0 - v3.0.9 · Pause and Policy · 2025-10-11
- Reversion to v2.8 and fixes due to major errors made in v2.9
- Standardized pause reasons: user, global, battery, idle, none
- User intent preserved: global pause no longer overrides user-paused drives
- Pause State Reset fixed
- Pause All Button Toggle fixed
- Disabled Drive Display fixed
- CLI Random Pausing fixed
- User-Paused Drives Reverting to Active fixed
- Windows console QuickEdit disabled to prevent accidental runtime pause

## v3.1.0 · Critical Bug Fixes & Stability (2025-10-11)
- **Scheduler loop crash fixes**: Fixed undefined variable 'letter' in `_plan_operations_cached` causing repeated scheduler failures (app_core.py v1.1.7 → v1.1.8)
- **Parameter name mismatch**: Corrected `drive_letter` vs `letter` inconsistency in `CoreEngine.set_drive_config` that caused NameError on GUI operations (app_core.py v1.1.10 → v1.1.11)
- **Interval change detection bug**: Fixed `old_interval` capture timing to properly detect configuration changes in `set_drive_config` (prevented timing state resets)
- **Lambda variable capture**: Resolved NameError in GUI drive table by replacing closures with `functools.partial` for 7 signal connections (app_gui_drive_table.py v1.1.9 → v1.1.10)
- **Config save parameter**: Fixed missing `config` parameter in `ConfigManager.save_config()` calls throughout GUI modules (app_gui_drive_table.py v1.1.6 → v1.1.7, app_gui.py v1.1.8 → v1.1.9)
- **Robust exit mechanism**: Implemented 10-second force exit timer with `os._exit(1)` fallback for unresponsive shutdowns; increased core engine stop timeout to 2000ms; added shutdown state tracking (main.py v1.0.3 → v1.0.4)
- **Log rotation overhaul**: Replaced Log_current.txt scheme with numbered-only rotation (Log_current1.txt through Log_current5.txt); fixed AttributeError in doRollover by using standard `_open()` method; ensured logs directory creation (app_logging.py v1.0.1 → v1.0.3)
- **CLI countdown configuration**: Made CLI time remaining output interval configurable via `cli_countdown_interval_sec` field (default 15s); updated config schema v3 → v4 with migration (app_config.py version 3 → 4, app_core.py v1.1.6 → v1.1.7)
- **Component versions**: app_core.py v1.1.11, app_gui.py v1.1.9, app_gui_drive_table.py v1.1.10, app_logging.py v1.0.3, app_config.py v4, main.py v1.0.4

## v3.3.2 · Critical Bug Fixes & Stability (2025-10-25)