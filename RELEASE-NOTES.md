TempSweep 0.1.0 is the first release: preview old Windows temporary files, then confirm exactly the files you want to delete.

- Portable desktop app, file list, age choices, progress, Stop and protected JSON reports.
- User temp selected by default; optional Windows temp and `.dmp` crash-dump cleanup.
- Separate, explicitly confirmed Recycle Bin emptying across the current user’s drives.
- Changed, busy, read-only, permission-denied and linked items are skipped. Cleanup uses a checked exclusive Windows file handle.
- Read-only CLI plus a disposable sample demo.
- Automated core, real Tk interface, native Windows filesystem and packaged executable checks.

**Download `TempSweep-0.1.0-Windows-x64.zip`, extract it and open `TempSweep.exe`.** Python is bundled. `TempSweep-CLI.exe` and executable SHA-256 checksums are also included. The source ZIP is for Python 3.11+.

**Cleanup permanently deletes files and bypasses the Recycle Bin.** The separate Bin action deletes all its items regardless of the age setting. TempSweep cannot restore deleted files. Close installers/apps and review the preview first.

Sizes are logical file bytes; actual disk-space gain varies. This is normal deletion, not secure erasure. The app is unsigned, offline and has no automatic cleaning or elevation. Windows 11 x64 is intended; other Windows releases are not separately tested.
