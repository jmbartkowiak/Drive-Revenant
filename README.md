# Drive Revenant

**Keep your drives hot and ready for instant access.**

Drive Revenant prevents hard drives and SSDs from entering sleep mode by performing tiny read/write operations at safe intervals. This eliminates the frustrating delay when accessing files on drives that have "spun down" or entered low-power states. Drive Revenant was partially inspired by 'Keep Alive' -  a similar, if much more basic (seeing as it managed to corrupt a drive after just a few days) implementation for keeping drives active.

## Why Use Drive Revenant?

When drives go to sleep, accessing files takes several seconds while the drive wakes up. Drive Revenant keeps them active and ready, ensuring:

- **Instant file access** - No waiting for drives to spin up or wake from sleep
- **Reduced data access latency** - Eliminates the 3-10 second delay when accessing sleeping drives
- **Automatic operation** - Runs in the background, requires no interaction after setup
- **Fast startup** - Application launches in seconds and begins monitoring immediately
- **Low overhead** - Minimal system resources and safe, carefully-timed operations

## Quick Start

### Installation (One-Time Setup)

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the application:**
   ```bash
   python main.py
   ```

That's it! The application will:
- Start in under 2 seconds
- Automatically detect available drives
- Begin keeping drives active using safe, configurable intervals
- Minimize to system tray for background operation

### First Run

1. **Launch the application** - The GUI appears showing all detected drives
2. **Review detected drives** - Each drive shows its current status, type, and next operation time
3. **Configure intervals** - Double-click any drive's "Interval" cell to set how often it should be accessed (default: 20 seconds - though I would suggest ~8s for HDDs)
4. **Enable/disable drives** - Right-click any drive to enable or disable monitoring
5. **Minimize to tray** - Click the minimize button to run in the background

No complex configuration needed - most defaults work immediately.

## Core Purpose: Preventing Drive Sleep

Drive Revenant performs small read/write operations to drive files at regular intervals. This prevents Windows from putting drives into:
- **Sleep mode** (spinning drives)
- **Low-power states** (SSDs)
- **Complete shutdown** (removable drives)

The result: **your drives stay active and ready for instant access**, eliminating the frustrating delay when opening files on drives that have gone to sleep.

### How It Works

- **Tiny operations**: Each drive gets a small read or write operation (typically <1KB)
- **Safe intervals**: User-configurable intervals (default: 20 seconds, minimum: 3 seconds)
- **Intelligent scheduling**: Prevents collisions between drives using deterministic timing
- **HDD protection**: Mechanical drives get extra protection with longer minimum intervals
- **Automatic recovery**: Failed operations trigger quarantine with exponential backoff 

## Key Features

### Safety First
- **Spacing rules**: Minimum 0.5s between any operations, 1.0s between writes
- **HDD guard**: Protective timing for mechanical drives (5-minute minimum gap for safety)
- **Error quarantine**: Automatic temporary disable after consecutive failures with exponential backoff
- **Lock retry**: Graceful handling of file locks and antivirus interference
- **Bounded operations**: Flush times capped to prevent UI stalls

### Intelligent Scheduling
- **500ms grid-based timing** with monotonic clock (no drift)
- **Deterministic tie-breaking** per install and day; collision packing (writes first, reads next)
- **Resume smoothing** when app resumes from pause or sleep
- **Multi-drive collision handling** with stable ordering

### User-Friendly Controls
- **Global Pause/Resume** for all drives
- **Per-drive control** via context menu (right-click)
- **In-cell editing** for intervals and drive types
- **Real-time countdowns** showing "Next in" time or "Due now"
- **System tray integration** for background operation
- **Full Rescan** option to reset and re-detect all drives

### Rapid Startup & Performance
- **Fast launch**: Application starts in under 2 seconds
- **Immediate operation**: Begins monitoring drives immediately on startup
- **Low overhead**: <50MB memory, <1% CPU usage
- **Incremental updates**: GUI refreshes only when state changes (500ms normal, 1000ms while editing)

## Usage

### Command Line Options

| Option | Descrption |
|--------|-------------|
| `--portable` | Run in portable mode (config/logs beside executable). See [Modes](#modes) section for details on when and why to use portable mode. |
| `--no-autostart` | Disable autostart setup |
| `--fix-autostart` | Repair autostart entry and exit (especially useful after moving a portable installation) |
| `--debug` | Increase log verbosity |
| `--version` | Show version info |

### GUI Overview

- **Drive table**: Shows all detected drives with status, type, interval, and countdown
- **Status bar**: Global countdown and policy status
- **Toolbar**: Pause/Resume all drives button
- **System tray**: Minimize to tray for background operation
- **Menu bar**: File menu includes "Full Rescan (Clear All)" for complete reset

### Status Indicators

- **Active** (green): Drive is being monitored and kept active
- **Paused** (yellow): Temporarily paused (user, global, battery, or idle policy)
- **Quarantine** (yellow): Temporarily disabled due to errors (exponential backoff)
- **Disabled** (red): Manually disabled by user
- **Offline** (red): Drive not detected or removed

### Per-Drive Context Menu (Right-Click)

- **Ping now**: Immediately perform an operation on this drive
- **Enable/Disable**: Toggle monitoring for this drive
- **Pause/Resume**: Temporarily pause this drive (preserves interval settings)
- **Release from Quarantine**: Manually clear quarantine status
- **Drive details**: View detailed information about the drive

### Display Format

- **"Next in" column**: Shows time until next operation (e.g., "15s", "2m", "Due now")
- **"Due now"**: Displayed when next operation is less than 1 second away
- **"---"**: Displayed when no operation is scheduled (disabled, paused, or quarantined)

## Configuration

Configuration is automatically migrated from older versions or created with safe defaults on first run. No manual configuration required.

### Key Settings (config.json)

```json
{
  "version": 4,
  "default_interval_sec": 20,
  "interval_min_sec": 3,
  "hdd_max_gap_sec": 300.0,
  "error_quarantine_after": 5,
  "pause_on_battery": true,
  "autostart": true,
  "per_drive": {
    "E:": {"enabled": true, "interval": 120, "type": "HDD"}
  }
}
```

**Important settings:**
- `default_interval_sec`: Default interval for new drives (20 seconds)
- `interval_min_sec`: Minimum allowed interval (3 seconds)
- `hdd_max_gap_sec`: Maximum gap for HDD protection (300 seconds = 5 minutes)
- `error_quarantine_after`: Consecutive failures before quarantine (5)
- `pause_on_battery`: Automatically pause when on battery power
- `autostart`: Start with Windows automatically

### Modes

Drive Revenant supports two operating modes: **Standard mode** (default) and **Portable mode**. Choose based on your needs:

#### Standard Mode (Default)

**When it's enabled:**
- Default mode when no `--portable` flag is used
- Auto-detection prefers standard mode when both config locations exist
- Used automatically when config exists in `%APPDATA%\DriveRevenant\`

**Storage locations:**
- Configuration: `%APPDATA%\DriveRevenant\config.json`
- Logs: `%APPDATA%\DriveRevenant\logs\`
- Autostart: Windows Task Scheduler (preferred method)

**Why use standard mode:**
- **System-wide installation**: Settings persist across user sessions
- **Clean separation**: Application files separate from user data
- **Task Scheduler autostart**: More reliable, system-managed autostart
- **Multi-user friendly**: Each Windows user has their own configuration
- **Standard Windows practice**: Follows typical application installation patterns

**Best for:**
- Permanent installation on your primary computer
- When you want settings to persist across application updates
- Multi-user systems where each user needs independent configuration
- When you want the most reliable autostart mechanism

#### Portable Mode

**When it's enabled:**
- Explicitly: Use `--portable` command-line flag
- Auto-detection: When only `config.json` exists beside the executable AND it contains `"portable": true`
- Auto-detection priority: If both portable and AppData configs exist, standard mode is preferred

**Storage locations:**
- Configuration: `config.json` beside the executable
- Logs: `logs\` folder beside the executable
- Autostart: Windows Registry entries (tied to executable path)

**Why use portable mode:**
- **Self-contained**: All files (config, logs, application) in one folder
- **USB drive friendly**: Perfect for running from removable drives
- **No system impact**: No files written to `%APPDATA%` or system directories
- **Easy backup**: Copy the entire folder to backup or move between computers
- **Clean uninstall**: Simply delete the folder - nothing left behind
- **Multiple instances**: Run multiple independent copies with different settings

**Best for:**
- USB drives or external hard drives
- Running from a specific folder without system-wide installation
- When you want to keep everything together (config, logs, application)
- Temporary installations or testing
- Moving the application between computers
- Situations where you can't or don't want to write to `%APPDATA%`

**Important considerations:**
- **Path dependency**: Autostart breaks if you move the executable folder (use `--fix-autostart` to repair)
- **No global settings**: Each portable copy has completely independent configuration
- **Registry autostart**: Less robust than Task Scheduler; requires registry write permissions
- **USB eject safety**: Always properly eject USB drives to avoid data corruption

#### Auto-Detection Behavior

When `--portable` is not specified, the application automatically detects the mode:

1. **Both configs exist**: Prefers standard mode (AppData location)
2. **Only AppData config exists**: Uses standard mode
3. **Only portable config exists**: Checks if `config.json` contains `"portable": true`
   - If `true`: Uses portable mode
   - If `false` or missing: Uses standard mode
4. **Neither exists**: Defaults to standard mode (creates config in AppData)

#### Switching Between Modes

You can run multiple instances simultaneously:
- **One standard mode instance**: Global autostart, system-wide settings
- **Multiple portable instances**: Each with independent settings and autostart

To switch modes:
- **Enable portable**: Run with `--portable` flag (creates local `config.json`)
- **Switch to standard**: Delete local `config.json` and run without `--portable` flag
- **Fix autostart after move**: Use `--fix-autostart` if you moved a portable installation

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

**Core components:**
- `CoreEngine`: Centralized scheduling with monotonic timing, jitter placement, collision spacing
- `Scheduler`: Single source of truth for all drive timing and state
- `IOManager`: Safe reads/writes to `X:\.drive_revenant\drive_revenant` with bounded flush
- `JitterPlanner`: Deterministic grid scheduling and HDD protection
- GUI subsystems: Table widget, status thread, settings, log viewer, diagnostics export

## Troubleshooting

### Common Issues

**Autostart not working:**
- Use the in-app "Fix Autostart" option from the File menu
- Or run: `python main.py --fix-autostart`

**Drive shows as quarantined:**
- Right-click the drive → "Release from Quarantine"
- Quarantine is automatic after 5 consecutive failures
- Quarantine uses exponential backoff: 30s, 1m, 2m, 4m, 8m, 16m, 32m, 1h, 2h, 4h, 8h, ~21 days

**Countdown stuck at "Due now":**
- This should resolve within 1-2 seconds as operations execute
- If persistent, use "Full Rescan (Clear All)" from File menu to reset

**Drive locked (antivirus interference):**
- Operations automatically skip locked drives as `SKIP_LOCKED`
- Schedule continues normally; no action needed

**Sluggish UI:**
- Increase `gui_update_interval_ms` in config (default: 500ms)
- Or hide heavy columns in the table

**Portable path moved:**
- Run `python main.py --fix-autostart` after relocating the folder

## Security and Privacy

- **No network access**: Application never connects to the internet
- **No data exfiltration**: All operations are local file I/O
- **Minimal registry writes**: Only autostart entries (optional)
- **Local logs only**: All logs stay on your machine
- **No telemetry**: No usage tracking or reporting

## Recent Updates

### v3.3.2 (2025-10-25) - Countdown & Interval Fixes
- **Exponential quarantine**: Smart backoff system (30s → ~21 days) for failed drives
- **Countdown display fix**: Shows "Due now" instead of "0s" or "-" for better clarity
- **Interval override fix**: Increased HDD protection from 5s to 300s (5 minutes) to respect configured intervals
- **Full rescan feature**: Added "Full Rescan (Clear All)" menu option to reset all drives
- **Tray exit fix**: Fixed exit from system tray menu
- **Scheduler migration**: Complete migration to centralized scheduler-based architecture

### v3.1.0 (2025-10-11) - Critical Bug Fixes
- Fixed scheduler loop crashes and parameter mismatches
- Improved exit mechanism with force exit timer
- Log rotation overhaul (numbered scheme)
- CLI countdown configuration

See [VERSION_HISTORY.md](VERSION_HISTORY.md) for complete version history.

## Development

### Running Tests
```bash
pytest
pytest --cov=app_core --cov=app_config --cov=app_io
```

### Code Quality
```bash
black .
ruff check .
mypy .
```
