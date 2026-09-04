# Contributing

Thanks for helping out. Drive Revenant is a Windows desktop app that keeps drives
awake; it favors **safe, small, well-tested changes**.

## Development setup

- Python 3.10+ on Windows.
- Install dependencies: `pip install -r requirements.txt` (PySide6, psutil, pywin32).

## Running & testing

```bash
python main.py            # run the app
pytest -q -m "not slow"   # fast suite (the default)
pytest -q -m slow         # opt-in slow suite (real drive detection/fsync)
```

- New behavior should ship with a test in `tests/` (files are named `TEST_*.py`).
- Tests stub real I/O via `tests/conftest.py`, so the fast suite runs offline.

## Building the exe

```bash
pip install pyinstaller
pyinstaller DriveRevenant.spec
```

The spec produces a onefile `dist/DriveRevenant.exe` with the icon and version
resources. Note: spec files are `exec`'d, so paths resolve via `SPECPATH` (not
`__file__`).

## Conventions

- Keep changes focused and backward-compatible with existing configs (config
  migration lives in `app_config.py`).
- Respect the **SAFE mode** default: on first start all writes are simulated until
  the user unchecks SAFE in the GUI.
- Windows-only APIs (`ctypes.windll`, WMI) must degrade gracefully off-Windows.

Open an issue before starting a large change so the direction can be discussed.
