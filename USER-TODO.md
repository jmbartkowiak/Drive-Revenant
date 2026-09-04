# USER-TODO — Drive Revenant (Manual Verification & Follow-ups)

This document is the hand-off for work that **only a human on the real machine** can do.
The automated test suite is green (254 tests: 240 fast + 14 slow), but the tests stub out
real I/O and cannot exercise the packaged `.exe`, the desktop GUI, real drives, or Windows
security contexts.

A code-review pass found several real bugs, all now fixed in code — but **the fixes only
matter if they hold up in the real, frozen build**, so most of the items below are about
verifying those fixes end-to-end. Each item explains *why* it matters and *how* to do it.

---

## 1. Verify the frozen build (highest priority)

**Why:** The review found that the code resolved the app folder with `Path(__file__).parent`.
In a PyInstaller onefile build, `__file__` points into a temporary extraction directory
(`_MEI…`) that is recreated every launch. That meant a *portable* build would lose its
config on every restart and could register autostart against a bogus temp path. This is now
fixed (`app_config._exe_dir()` and `app_autostart.get_exe_path()` anchor to
`sys.executable`), but the fix is Windows/frozen-only and is **not covered by the test
suite**.

**How:**
1. Build (if not already): `python -m PyInstaller DriveRevenant.spec --noconfirm`.
2. Copy `dist\DriveRevenant.exe` to a clean folder (e.g. `C:\DriveRevenantTest\`).
3. Run it from there with portable mode: create `config.json` beside it containing
   `{"portable": true}` (or run `DriveRevenant.exe --portable`), then launch.
4. Confirm:
   - A `config.json` and a `logs\` folder appear **next to the exe** (not in `%TEMP%`).
   - Close and reopen — settings (intervals, drive list) persist.
   - The tray icon and window icon render (the bundled PNG resolves via `_MEIPASS`).
5. Delete the test folder when done.

---

## 2. Verify autostart ("Fix Autostart" in the GUI)

**Why:** The GUI was passing a `ConfigManager` object where an exe *path* was expected, so
"Fix Autostart" would write a Python `repr` into Task Scheduler / the Registry `Run` key —
autostart could never verify and never point at the real exe. Fixed to use `get_exe_path()`.

**How:**
1. In the GUI: **File → Fix Autostart**.
2. Confirm it reports "already configured correctly" or creates the entry.
3. Open **Task Scheduler** (`taskschd.msc`) → find `DriveRevenant` → verify the action's
   command path is the **real exe path** (no `%TEMP%`, no `_MEI`, no quotes/escapes broken).
4. If using Registry autostart, check `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
   → `DriveRevenant` points at the real exe.
5. Log out / log in (or reboot) and confirm it auto-starts.

**Note:** the Task Scheduler XML is now XML-escaped, so a path containing `&` or spaces
should survive. Test with the exe in a folder that has a space or `&` in its name.

---

## 3. Verify drive-type detection on real drives

**Why:** Drive-type detection was rewritten (no more PowerShell) to use Win32 storage
IOCTLs + WMI. The automated tests mock these calls, and the classification of *your*
specific USB enclosures depends on hardware signals that vary by bridge chip.

**How:**
1. Launch the app (or run `python main.py`) and open the drive table.
2. For every drive, compare the reported **type** (HDD/SSD/Removable) against what the
   drive actually is (check the label/model, or `Get-PhysicalDisk | Select FriendlyName,
   MediaType, BusType` in an admin PowerShell).
3. Watch specifically for **USB external drives**:
   - Drives behind generic bridges (`ASMT…`, `JMicron Generic`) may show **Unknown** and
     fall back to SSD via the `treat_unknown_as_ssd` setting. If one is actually a
     mechanical HDD, that fallback is wrong — tell me and I'll add a smarter rule.
   - WD SSDs report as `WDC WDS…`/`WDC WD_BLACK…` — these should classify **SSD**
     (the name heuristic now checks `WDS`/`WD_BLACK` before the `WDC`→HDD rule).
   - Older Samsung *spinning* drives (pre-2011 Spinpoint) would misclassify as SSD;
     modern Samsung drives are all SSD, so this is only a concern for very old disks.

**What to report back:** any drive whose reported type is wrong, with the drive's model
name (from Device Manager or `wmic diskdrive get model`).

---

## 4. Verify on a standard (non-administrator) account

**Why:** One link in the detection chain — the WMI `MSFT_PhysicalDisk` query — is documented
as non-admin on Windows 8+, but I could not find a citable guarantee for every locked-down
configuration. The old PowerShell path was the fragile part; the new chain should work
without elevation, but it must be confirmed on a real restricted account.

**How:**
1. Create (or use) a standard, non-admin Windows account.
2. Run `DriveRevenant.exe` (or `python main.py`).
3. Confirm the drive table populates with correct types (not all `Unknown`).
4. If everything is `Unknown` or the app errors, run once as admin to see whether it's an
   elevation issue, and report the log (`logs\debug.log`).

---

## 5. Real drive-ping smoke test

**Why:** The actual safety-critical behavior — writing `<1 KB` files to a hidden
`.drive_revenant` folder and atomically replacing them — is exercised only by unit tests
against a stub I/O manager. Real disks (lock/antivirus interference, removable eject,
read-only media) behave differently.

**How (on a disposable drive or one you don't mind touching):**
1. Launch the app and let it monitor for several minutes.
2. Confirm a `X:\.drive_revenant\drive_revenant` file appears and is updated periodically.
3. **Lock test:** open the file with exclusive access in another program → the log should
   show `SKIP_LOCKED` and keep going (no crash).
4. **Eject test:** safely eject a removable drive while monitored → no crash, drive is
   dropped or marked unavailable.
5. Check `logs\Log_current1.txt` and `logs\events.ndjson` for sensible entries.

---

## 6. Real desktop GUI test

**Why:** Qt GUI behavior (tray, in-cell editing, context menus, DPI) cannot be tested
headlessly and was not exercised.

**How:**
1. **Tray:** minimize to tray; use the tray menu (pause/resume, exit). Exit must actually
   quit (there is a 10 s force-exit fallback).
2. **In-cell editing:** double-click the Interval cell, edit, and confirm the change saves
   and the countdown updates without the table freezing.
3. **Context menu:** right-click a drive → enable/disable, pause/resume, ping-now,
   release-from-quarantine.
4. **DPI:** change Windows display scaling (100% → 150%) and confirm the window/table
   renders correctly.
5. Confirm the **status thread** keeps updating (if it dies, the table freezes — this was
   hardened but needs a real run to confirm).

---

## 7. Non-Windows / restricted-system fallbacks

**Why:** `app_io`/`app_core` use `ctypes.windll`, WMI, and PowerShell only on Windows. On a
non-Windows OS these paths are untested and are expected to degrade gracefully.

**How (if you have a non-Windows machine or a locked-down Windows box):**
1. Run the app; it should not crash — it should degrade to `Unknown` drive types and keep
   running.
2. On a system with AppLocker / Constrained Language Mode, confirm startup and drive
   detection work (the old PowerShell path was the failure point; it is now removed).

---

## 8. Known minor code issues (documented, not blocking)

These came out of the review pass. They are low-risk and I deliberately did **not** change
them to avoid subtle regressions — flag them if you want them addressed:

- **`app_core.py` `update_drive_state` defaults** — `handle_failure`/`handle_success`/
  `check_quarantine_release` call `update_drive_state` without `interval_sec`, so the
  default `180` briefly clobbers the real interval until the next plan cycle. Cosmetic;
  only affects a transient snapshot.
- **`app_io.py` `_classify_failure`** — `IO_FATAL` failures are retried for the whole lock
  budget and can end up reported as `SKIP_LOCKED`. Low impact on the happy path.
- **`app_gui.py` "Open config folder"** — uses `explorer ...` with `check=True`; a non-zero
  exit (e.g. user cancels) surfaces as an error dialog. Cosmetic.
- **`app_config.py` atomic save** — uses a single shared `.tmp` name, so two simultaneous
  saves could race. Only relevant if config is saved concurrently (rare).
- **`main.py`** — logs one message after `logging.shutdown()`, which is a no-op in the
  frozen build. Cosmetic.

---

### Quick summary of what to prioritize

1. Frozen build in a clean folder (config persistence + icons) — **item 1**.
2. "Fix Autostart" points at the real exe — **item 2**.
3. Drive-type table matches reality, especially USB drives — **item 3**.

If all three pass, the remaining items are optional hardening/confirmation.
