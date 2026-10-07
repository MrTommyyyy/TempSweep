# TempSweep

[![Tests](https://github.com/MrTommyyyy/TempSweep/actions/workflows/tests.yml/badge.svg)](https://github.com/MrTommyyyy/TempSweep/actions/workflows/tests.yml)
[![Windows build](https://github.com/MrTommyyyy/TempSweep/actions/workflows/windows.yml/badge.svg)](https://github.com/MrTommyyyy/TempSweep/actions/workflows/windows.yml)
[![MIT license](https://img.shields.io/badge/license-MIT-0f766e)](LICENSE)

**See what can go before you delete it.** A small, offline Windows desktop tool for old temporary files, optional crash dumps and separately confirmed Recycle Bin cleanup.

[**Download the Windows app**](https://github.com/MrTommyyyy/TempSweep/releases/latest) · [Report a bug](https://github.com/MrTommyyyy/TempSweep/issues/new?template=bug_report.md) · [Suggest a feature](https://github.com/MrTommyyyy/TempSweep/issues/new?template=feature_request.md)

I built this because cleaning a PC should be understandable: a list of files, a clear choice and a result that explains what happened. I’m interested in practical utilities that are easy to try and improve through real feedback.

## Start on Windows

1. Download **`TempSweep-0.1.0-Windows-x64.zip`** from Releases.
2. Extract the ZIP and double-click **`TempSweep.exe`**. Python is included; no installation or account is required.
3. Leave **Your temporary files** selected, or choose optional categories. The default keeps files modified within the last **7 days**.
4. Click **Preview cleanup** and review the file list, size estimates and scan issues.
5. Click **Delete previewed files…** and confirm if you want those files removed.

**File deletion is permanent and bypasses the Recycle Bin.** TempSweep has no restore feature. Close installers and applications first; file age does not prove that an old temporary file is no longer needed.

The separate **Empty Recycle Bin…** button refreshes the current totals and asks for confirmation. It empties the current user’s Recycle Bin across all drives. **The age filter does not apply to the Bin.** Files added before that operation finishes may also be removed.

## What it cleans

| Category | Scope | Default |
| :--- | :--- | :--- |
| Your temporary files | The current Windows known Local AppData folder’s `Temp` subfolder | Selected; older than 7 days |
| Windows temporary files | The Windows known folder’s `Temp` subfolder | Off; protected files may be skipped |
| Old application crash dumps | `.dmp` files in Local AppData’s `CrashDumps` subfolder | Off; keep these if investigating crashes |
| Recycle Bin | Current user’s Bin across drives through the Windows Shell API | Separate explicit action |

Custom `%TEMP%` and `%TMP%` locations are intentionally not followed. Cleanup does not target Downloads, Documents, Desktop, browser profiles, installed programs, registry entries, Windows Update files or arbitrary user-selected folders. All directories, including empty ones, stay in place.

## Review and cleanup rules

- **Preview is read-only.** Nothing runs automatically when you open the app.
- Pick an age threshold of 1, 7, 14, 30, 90 or 365 days. The cutoff uses last-modified time, not last-access time.
- Changing categories or the age invalidates the old preview. A preview expires after 30 minutes.
- Links, junctions, reparse points, hard-linked files and special files are skipped. Linked ancestors also make a cleanup folder unavailable.
- Each file and its parent folder identities are rechecked immediately before cleanup. Changed, missing, busy, read-only and permission-denied files are kept and reported.
- On Windows, deletion uses an exclusive file handle; its identity, last-modified time, size and final path are checked before deletion through that same handle.
- **Stop** prevents further file deletions after the current operation. It cannot undo completed deletions. Windows’ Recycle Bin operation cannot be cancelled inside TempSweep.
- A preview stops at 100,000 entries and produces no cleanup plan if the limit is exceeded. Up to 200 issue details are retained per report.
- JSON exports create a new `.json` file outside cleanup folders. They refuse existing files and links. Reports are for reading; they cannot be imported as deletion plans.

Displayed sizes are **logical file bytes**, not a promise of disk space recovered. Sparse files, compression and filesystem allocation can change the actual space gain. TempSweep deletes files normally; it does not securely erase storage or guarantee a faster PC. It does not force-delete locked files, request elevation or change permissions.

## Read-only command line

The Windows ZIP also includes **`TempSweep-CLI.exe`**. Its normal commands only preview; PC deletion is an interactive desktop action.

```powershell
.\TempSweep-CLI.exe --version
.\TempSweep-CLI.exe --older-than 14
.\TempSweep-CLI.exe --category user-temp --category windows-temp --json
.\TempSweep-CLI.exe --category crash-dumps --output .\new-preview.json
```

Exit codes: **0** successful preview, **1** preview with scan issues, **2** input or export error. Missing optional folders and inaccessible items are reported; they do not trigger deletion. The CLI never empties the Recycle Bin.

## Try it without cleaning your PC

```powershell
.\TempSweep-CLI.exe --demo
```

The demo creates its own temporary fixture folder, deletes one old sample file and verifies that a recent sample and an outside sample document remain. It never discovers PC cleanup folders or touches a real Recycle Bin.

From the source ZIP, use Python 3.11+:

```sh
python demo.py
python -m unittest discover -s tests -v
```

Run `python gui.py` or `python tempsweep.py --json` on Windows. The disposable demo and portable core tests also run on macOS and Linux; the actual PC cleanup interface and Windows Shell features are Windows only.

## Testing and downloads

The suite covers age boundaries, stale previews, changed/replaced files and folders, outside-root attempts, cancellation, permission failures, hard links, links/junctions, report protection and Recycle Bin confirmation/error handling. Windows jobs also exercise actual Tk buttons and dialogs, exclusive locks, read-only files and native junctions. Recycle Bin writes are mocked in tests so a runner’s real Bin is never emptied.

The Windows release workflow builds both executables, tests the packaged CLI on disposable files, verifies the real packaged desktop window opens and closes, then publishes the download. It preserves an existing version’s assets. SHA-256 checksums of both executables are included in the ZIP; GitHub lists asset digests too.

Portable Windows x64 is the release target. Windows 11 is the intended desktop; Windows 10 may work but is not separately tested here. Builds are unsigned and do not auto-update. Use Releases to obtain a newer version. Source has no third-party runtime dependencies; PyInstaller is needed only for packaging.

## Privacy and limits

There is no telemetry, background service, account, network request or scheduled cleaning. Reports and issue messages can contain private paths and filenames: review them before sharing. Known-folder relocation and unusual filesystems may cause conservative skips. The portable core is intended for local disposable tests; it is not a security boundary against an attacker changing paths concurrently on other operating systems.

The implementation uses documented Windows APIs: [known folders](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath), [file-handle deletion](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle), [Recycle Bin query](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shqueryrecyclebinw), [Recycle Bin emptying](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shemptyrecyclebinw) and [the default crash-dump folder](https://learn.microsoft.com/en-us/windows/win32/wer/collecting-user-mode-dumps).

## Contributing

Small, reproducible bug reports and usability feedback are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). This is an early release: keeping cleanup scope clear matters more than adding a button that deletes everything.

MIT licensed. Copyright © 2026 Thomas Griffiths.
