# Security Policy

## What this software does

Drive Revenant performs tiny, local read/write operations on your drives to keep
them from sleeping. It has **no network access, no telemetry, and no data
exfiltration** — all activity is local file I/O.

## Safety model

- **SAFE mode is on by default.** On first start, every operation is simulated and
  nothing is written to your drives. Real pings begin only after you uncheck the
  **SAFE** checkbox in the bottom-left of the window.
- Writes are **atomic** (temp file + replace), bounded by a flush budget, and
  spaced to avoid I/O storms.
- Only autostart registry/Task Scheduler writes are performed (optional).

## Reporting a vulnerability

If you find a security issue, please **do not open a public issue**. Instead:

1. Report it privately by email (or open a private security advisory on GitHub if
   the repository enables them).
2. Include a clear description, affected versions, and steps to reproduce.

We will respond as soon as possible and credit reporters who follow responsible
disclosure.
