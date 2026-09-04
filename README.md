# Drive Revenant

**Keep your drives hot and ready for instant access.**

Drive Revenant prevents hard drives and SSDs from entering sleep mode by performing
tiny read/write operations at safe, user-configurable intervals. This eliminates the
multi-second wake-up delay when a drive has "spun down" or entered a low-power state.

It was partly inspired by *Keep Alive* — a similar but far more basic tool that
managed to corrupt a drive after a few days. Drive Revenant is built around safety:
bounded flushes, atomic writes, spacing rules, and exponential error quarantine.

---

## Features

### Safety first
- **SAFE mode (default)** — on first start the app simulates every operation and
  writes nothing to your drives until you uncheck the big **red SAFE** toggle in the
  bottom-left of the window (it turns green when live). Only then are real drive pings
  written.
- **Tiny operations** — each ping is a single read or write of a <1 KB file
  (`X:\.drive_revenant\drive_revenant`).
- **Atomic writes** — writes go to a temp file and are atomically replaced, with an
  optional `fsync` and a bounded flush (`max_flush_ms`).
- **Spacing rules** — minimum spacing between operations (500 ms read, 1000 ms write)
  prevents I/O storms across many drives.
- **HDD guard** — mechanical drives are capped to a maximum gap (`hdd_max_gap_sec`)
  so they never sleep for too long, while still respecting the configured interval.
- **Exponential quarantine** — a drive that fails repeatedly is temporarily disabled
  with exponential backoff (30 s -> ~21 days) and recovers automatically.
- **Lock retry** — graceful handling of file locks and antivirus interference
  (`SKIP_LOCKED`).

### Intelligent scheduling
- **Monotonic clock** — all timing uses `time.monotonic()`, so there is no drift and
  no confusion with wall-clock changes.
- **Deterministic jitter** — daily tie-breaking seeded by `install_id` + date keeps
  multi-drive scheduling stable and collision-free.
- **Effective interval** — the user-configured interval is kept intact; the effective
  interval (after minimum clamping and HDD capping) is derived separately and shown in
  the UI. A clamped or HDD-capped drive is labeled accordingly.
- **Resume smoothing** — pausing/resuming clears and re-plans the schedule cleanly;
  paused drives are never re-planned behind your back.

### User controls
- **Global Pause / Resume** for all drives.
- **Per-drive** enable/disable, pause/resume, ping-now, and release-from-quarantine
  via a right-click context menu.
- **In-cell editing** for interval and drive type.
- **Real-time countdown** ("Next in" column) computed from the effective interval.
- **System tray** integration for background operation.
- **Full Rescan (Clear All)** to reset and re-detect all drives.

### Low overhead
- Starts in seconds and begins monitoring immediately.
- GUI emits snapshots only when state changes (or once per second for the countdown
  tick) instead of repainting on every poll.
- Cheap O(n log n) "next drives" preview derived from the live schedule.

---

## Quick start

### Install

```bash
pip install -r requirements.txt
```

Requirements: Python 3.10+, Windows, and `PySide6`, `psutil`, `pywin32`.

### Run

```bash
python main.py
```

The app detects drives, begins keeping them active, and minimizes to the system tray.

### First run

1. Launch the app — the GUI shows all detected drives.
2. Note the **SAFE** checkbox in the bottom-left: it starts checked, so all
   operations are simulated and nothing is written to your drives.
3. Review each drive's status, type, and next-operation countdown.
4. When you are ready for the app to write real pings, **uncheck SAFE**.
5. Double-click the **Interval (s)** cell to change how often a drive is accessed
   (default 180 s; ~8 s is a common choice for HDDs).
6. Right-click a drive to enable/disable, pause/resume, ping now, or view details.
7. Minimize to tray to run in the background.

---

## Command line

| Option | Description |
|--------|-------------|
| `--portable` | Run in portable mode (config/logs beside the executable). |
| `--no-autostart` | Disable autostart setup. |
| `--fix-autostart` | Repair the autostart entry and exit. |
| `--config-info` | Print resolved configuration information and exit. |
| `--debug` | Increase log verbosity. |
| `--version` | Show version info. |

---

## Configuration

Configuration is created with safe defaults on first run and migrated from older
versions automatically. Keys live in `config.json`.

```jsonc
{
  "version": 5,
  "install_id": "<uuid>",
  "portable": false,
  "autostart": true,
  "autostart_method": "scheduler",          // "scheduler" or "registry"
  "default_interval_sec": 180,
  "interval_min_sec": 5,
  "jitter_sec": 2,
  "hdd_max_gap_sec": 300.0,                // 5 min cap for HDDs
  "deadline_margin_sec": 0.3,
  "pause_on_battery": false,
  "idle_pause_min": 0,                       // 0 = disabled
  "fsync": true,
  "max_flush_ms": 150,
  "lock_retry_ms": 750,
  "simulate_writes": true,                 // SAFE mode: true = simulate, no real writes
  "error_quarantine_after": 5,
  "error_quarantine_sec": 60,               // base; exponential backoff extends this
  "log_max_kb": 150,
  "log_history_count": 5,
  "log_ndjson": true,
  "gui_update_interval_ms": 500,
  "gui_update_interval_editing_ms": 1000,
  "cli_countdown_interval_sec": 15,
  "scheduler_grid_ms": 250,
  "scheduler_min_read_spacing_ms": 500,
  "scheduler_min_write_spacing_ms": 1000,
  "drive_stale_removal_days": 15,           // 0 = disabled
  "drive_scan_mode": "quick",               // "quick" or "full"
  "forced_drive_letters": "",               // e.g. "F,J,K"
  "per_drive": {
    "E:": { "enabled": true, "interval": 10, "type": "HDD", "ping_dir": null }
  }
}
```

**Important settings**

- `default_interval_sec` — interval for newly discovered drives.
- `interval_min_sec` — hard floor applied to every drive.
- `hdd_max_gap_sec` — maximum gap allowed for HDDs before the interval is capped.
- `simulate_writes` — SAFE mode (default `true`): when `true`, all operations are
  simulated and nothing is written to drives. Set `false` (or uncheck **SAFE** in the
  GUI) to enable real drive pings.
- `error_quarantine_after` — consecutive failed ticks before a drive is quarantined.
- `pause_on_battery` / `idle_pause_min` — policy pauses.
- `drive_stale_removal_days` — remove drives not seen for this many days (only at max
  quarantine level; 0 disables removal).

### Modes

**Standard mode (default)** stores config in `%APPDATA%\DriveRevenant\` and uses Task
Scheduler for autostart. **Portable mode** (`--portable`, or a `config.json` with
`"portable": true` beside the executable) keeps everything in the app folder and uses
the Registry for autostart.

---

## Architecture

```
main.py                     Entry point, CLI, single-instance, lifecycle
app_config.py               Pure persistence layer (load/save/migrate config)
app_core.py                 CoreEngine + Scheduler (single source of truth) + JitterPlanner
app_io.py                   I/O operations, drive detection, failure classification
app_logging.py              Human log rotation + NDJSON events
app_gui.py                  MainWindow (menus, toolbar, tray, status bar)
app_gui_drive_table.py      Drive table (in-cell editing, countdown, context menu)
app_gui_status_thread.py    Background snapshot emitter (change/tick gated)
app_gui_settings_dialog.py  Preferences dialog
app_gui_log_viewer.py       Log viewer
app_autostart.py            Task Scheduler / Registry autostart
app_types.py                Shared dataclasses + enums
app_utils.py                Small shared helpers
```

### Scheduling model

- `Scheduler` owns all drive timing/state in `_drive_timing` and publishes immutable
  `StatusSnapshot`s under a lock.
- `JitterPlanner` computes the **effective interval** (min-clamped, HDD-capped) without
  mutating the user's configured interval, and places operations with deterministic
  jitter and spacing.
- `CoreEngine._scheduler_loop` plans, executes due operations, and re-plans on a
  ~500 ms cadence; it never re-plans a paused or quarantined drive.

---

## Testing

```bash
pytest                          # run the current suite (defaults to `-m "not slow"`)
pytest -m slow                  # run the opt-in slow suite (real drive detection/fsync)
pytest tests/TEST_scheduler_centralized.py   # run a specific module
```

The `tests/` directory holds the **current** suite (254 tests: 240 fast + 14 `slow`).
`pytest.ini` deselects the `slow`-marked tests by default, since they exercise real drive
detection, fsync, and performance timings that depend on the machine. Legacy tests from
older architectures (pre-Scheduler, pre-`drive_states` removal, script-style verification
files) were moved to `archive/legacy_tests/` and are intentionally not collected.

`tests/conftest.py` provides the shared fixtures and stubs out the I/O manager so the
fast suite runs offline and quickly.

---

## Repository layout & git

The repository is a Git working tree. Runtime/scratch artifacts are ignored via
`.gitignore`: `__pycache__/`, `.pytest_cache/`, `logs/`, `test_logs/`, `config.json`,
`build/`, `dist/`, and `archive/` (kept on disk for history, not tracked).

- `README.md` — this document.
- `VERSION_HISTORY.md` — project-level change log.
- `TODO.md` — remaining and deferred issues.

---

## Troubleshooting

- **Autostart not working** — File -> Fix Autostart, or `python main.py --fix-autostart`.
- **Drive shows "Quarantine"** — right-click -> Release from Quarantine. Quarantine is
  automatic after repeated failures and uses exponential backoff.
- **Countdown stuck at "Due now"** — resolves within a second or two; use File ->
  Full Rescan (Clear All) if it persists.
- **Drive locked (antivirus)** — operations skip as `SKIP_LOCKED`; the schedule continues.
- **Sluggish UI** — increase `gui_update_interval_ms`, or hide heavy columns.

---

## Security & privacy

- No network access, no telemetry, no data exfiltration.
- All operations are local file I/O.
- Only autostart registry/scheduler writes (optional).
- Logs are local only.

See `TODO.md` for known limitations and deferred work, and `SECURITY.md` for the
safety model and reporting process.

---

## License

[MIT](LICENSE) © 2026 Drive Revenant contributors. See [CONTRIBUTING.md](CONTRIBUTING.md)
for how to build, test, and contribute.
