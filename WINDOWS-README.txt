TempSweep 0.1.0 — portable Windows x64

1. Extract all files in this ZIP.
2. Double-click TempSweep.exe.
3. Choose cleanup categories and an age threshold (default: 7 days).
4. Click Preview cleanup. Review the listed files and scan issues.
5. Click Delete previewed files... only if you want permanent deletion.

Files deleted by TempSweep bypass the Recycle Bin and cannot be restored by this app.
Close installers and applications first. An old temporary file can still be needed.
Changed, busy, read-only or permission-denied files are skipped. No automatic elevation.
Directories, including empty folders, remain.

Empty Recycle Bin... is a separate action with a separate confirmation. It empties
the current user's Bin across all drives, regardless of the file-age setting.
Items added before that operation finishes may also be removed.

Nothing is cleaned automatically when the app starts. No installation, Python,
account, API key or network connection is required. The executables are unsigned.

TempSweep-CLI.exe is a read-only preview tool. Open PowerShell in this folder:
  .\TempSweep-CLI.exe --older-than 14
  .\TempSweep-CLI.exe --json
  .\TempSweep-CLI.exe --demo

--demo tests deletion on freshly created disposable samples only. It never touches
real cleanup folders or the Recycle Bin. CLI exit codes: 0 OK, 1 scan issues, 2 error.

SHA256SUMS.txt contains checksums of both executables. Latest source and downloads:
https://github.com/MrTommyyyy/TempSweep/releases/latest

Windows 11 x64 is intended; Windows 10 is not separately tested. No secure erase,
registry cleaning, browser-data deletion, automatic updates or speed-up guarantee.
