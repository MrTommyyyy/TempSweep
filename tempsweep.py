"""TempSweep: preview old files in a small Windows cleanup allowlist.

The public CLI is read-only. The GUI is the interactive deletion entry point.
Tests and the demo use explicit disposable targets, never real cleanup roots.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import stat
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

VERSION = "0.1.0"
DAY = 86400
MAX_ENTRIES = 100_000
MAX_ISSUES = 200
LABELS = {"user-temp": "Your temporary files", "windows-temp": "Windows temporary files", "crash-dumps": "Old application crash dumps"}
LOCAL_APPDATA = "f1b32785-6fba-4fcf-9d55-7b8e7f157091"
WINDOWS_FOLDER = "f38bf404-1d43-42f2-9305-67de0b28fc23"


class SafetyError(ValueError):
    """A path or preview is unsuitable for cleanup."""


@dataclass(frozen=True)
class Target:
    key: str
    label: str
    root: Path
    suffix: str | None = None


@dataclass(frozen=True)
class Candidate:
    category: str
    path: Path
    root: Path
    fingerprint: tuple[int, ...]
    parents: tuple[tuple[Path, tuple[int, int]], ...]

    @property
    def size(self):
        return self.fingerprint[2]


@dataclass(frozen=True)
class Plan:
    created: float
    older_than: int
    cutoff_ns: int
    targets: tuple[Target, ...]
    files: tuple[Candidate, ...]
    kept: int
    issues: tuple[str, ...]
    issue_count: int

    @property
    def size(self):
        return sum(f.size for f in self.files)

    def report(self):
        return {
            "tool": "TempSweep", "version": VERSION, "mode": "preview",
            "created": self.created, "older_than_days": self.older_than,
            "candidate_files": len(self.files), "candidate_bytes": self.size,
            "kept_files": self.kept, "issue_count": self.issue_count,
            "issues": list(self.issues),
            "categories": [{"key": t.key, "label": t.label, "root": str(t.root)} for t in self.targets],
            "files": [{"category": f.category, "path": str(f.path), "bytes": f.size} for f in self.files],
        }


@dataclass
class CleanupResult:
    deleted_files: int = 0
    deleted_bytes: int = 0
    skipped_files: int = 0
    cancelled: bool = False
    issues: list[str] = field(default_factory=list)

    def report(self):
        return {"tool": "TempSweep", "version": VERSION, "mode": "cleanup",
                "deleted_files": self.deleted_files, "deleted_bytes": self.deleted_bytes,
                "skipped_files": self.skipped_files, "cancelled": self.cancelled,
                "issues": self.issues}


def _link(st):
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _identity(st):
    return (st.st_dev, st.st_ino)


def _fingerprint(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _guard_directory(path: Path):
    """Reject reparse points in the entire path, including cleanup roots."""
    if not path.is_absolute() or path == Path(path.anchor):
        raise SafetyError("The cleanup root must be an absolute subfolder, never a drive root.")
    for part in [*reversed(path.parents), path]:
        info = part.lstat()
        if _link(info) or not stat.S_ISDIR(info.st_mode):
            raise SafetyError("A folder is a link, junction or other reparse point: " + str(part))
    return path.lstat()


def _bind(dll, name, args, result):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn


def _require_windows():
    if sys.platform != "win32":
        raise OSError("PC cleanup and Recycle Bin operations require Windows. Use --demo for a disposable sample on another OS.")


class RecycleInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("i64Size", ctypes.c_int64), ("i64NumItems", ctypes.c_int64)]


def _shell_api():
    _require_windows()
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    _bind(shell, "SHGetKnownFolderPath", [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)], ctypes.c_int32)
    _bind(shell, "SHQueryRecycleBinW", [ctypes.c_wchar_p, ctypes.POINTER(RecycleInfo)], ctypes.c_int32)
    _bind(shell, "SHEmptyRecycleBinW", [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32], ctypes.c_int32)
    return shell


def _hresult(code, operation):
    if code != 0:
        raise OSError(f"{operation} failed (Windows HRESULT 0x{code & 0xffffffff:08X}).")


def _known_folder(folder_id):
    shell = _shell_api()
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    free = _bind(ole, "CoTaskMemFree", [ctypes.c_void_p], None)
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(folder_id).bytes_le)
    address = ctypes.c_void_p()
    try:
        _hresult(shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(address)), "Find Windows folder")
        if not address.value:
            raise OSError("Windows returned no folder path.")
        path = Path(ctypes.wstring_at(address))
        if not path.is_absolute() or path == Path(path.anchor):
            raise SafetyError("Windows returned an unsuitable cleanup base folder.")
        return path
    finally:
        if address.value:
            free(address)


def discover_targets():
    """Only known Windows folders are exposed; custom TEMP variables are ignored."""
    _require_windows()
    local = _known_folder(LOCAL_APPDATA)
    windows = _known_folder(WINDOWS_FOLDER)
    return (
        Target("user-temp", LABELS["user-temp"], local / "Temp"),
        Target("windows-temp", LABELS["windows-temp"], windows / "Temp"),
        Target("crash-dumps", LABELS["crash-dumps"], local / "CrashDumps", ".dmp"),
    )


def query_recycle_bin():
    """Read the current user's Recycle Bin totals across drives."""
    info = RecycleInfo()
    info.cbSize = ctypes.sizeof(info)
    _hresult(_shell_api().SHQueryRecycleBinW(None, ctypes.byref(info)), "Query Recycle Bin")
    if info.i64Size < 0 or info.i64NumItems < 0:
        raise OSError("Windows returned invalid Recycle Bin totals.")
    return {"items": info.i64NumItems, "bytes": info.i64Size}


def empty_recycle_bin(*, confirmed=False):
    """The GUI must obtain separate explicit consent immediately before this call."""
    if confirmed is not True:
        raise SafetyError("Emptying the Recycle Bin requires a separate confirmation.")
    # NOCONFIRMATION | NOPROGRESSUI | NOSOUND: our UI already asks the user.
    _hresult(_shell_api().SHEmptyRecycleBinW(None, None, 7), "Empty Recycle Bin")


def scan_targets(targets, older_than=7, *, now=None, cancel=None, progress=None, max_entries=MAX_ENTRIES):
    """Create an in-memory preview. Explicit roots are for library callers/tests.

    The app uses discover_targets(); exported JSON cannot be imported for deletion.
    """
    if isinstance(older_than, bool) or not isinstance(older_than, int) or not 1 <= older_than <= 365:
        raise ValueError("Choose a whole number of days from 1 to 365.")
    targets = tuple(targets)
    if len({t.key for t in targets}) != len(targets):
        raise ValueError("Category keys must be unique.")
    created = time.time() if now is None else now
    # FILETIME stores 100 ns ticks. Round toward keeping the boundary file,
    # so an exact cutoff survives Windows timestamp precision unchanged.
    cutoff = (int(created * 1_000_000_000) // 100) * 100 - older_than * DAY * 1_000_000_000
    files, issues, issue_count, kept, entries = [], [], 0, 0, 0
    seen_roots = []

    def issue(text):
        nonlocal issue_count
        issue_count += 1
        if len(issues) < MAX_ISSUES:
            issues.append(text)

    for target in targets:
        root = target.root
        if not root.is_absolute() or ".." in root.parts:
            raise SafetyError("Cleanup folders must be absolute without parent traversal.")
        if any(root == r or root in r.parents or r in root.parents for r in seen_roots):
            raise SafetyError("Cleanup categories must not overlap.")
        seen_roots.append(root)
        try:
            root_info = _guard_directory(root)
        except (OSError, SafetyError) as error:
            issue(f"{target.label}: {error}")
            continue
        stack = [(root, ((root, _identity(root_info)),))]
        while stack:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Preview cancelled. Nothing was deleted.")
            folder, parents = stack.pop()
            try:
                current = _guard_directory(folder)
                if _identity(current) != parents[-1][1]:
                    raise SafetyError("Folder changed during preview.")
                with os.scandir(folder) as listing:
                    for entry in listing:
                        entries += 1
                        if entries > max_entries:
                            raise SafetyError(f"Preview stopped at {max_entries:,} entries. No cleanup plan was created.")
                        if cancel is not None and cancel.is_set():
                            raise InterruptedError("Preview cancelled. Nothing was deleted.")
                        path = Path(entry.path)
                        try:
                            info = path.lstat()
                            if _link(info):
                                issue("Skipped link, junction or reparse point: " + str(path))
                            elif stat.S_ISDIR(info.st_mode):
                                stack.append((path, (*parents, (path, _identity(info)))))
                            elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                                issue("Skipped special or hard-linked file: " + str(path))
                            elif target.suffix and path.suffix.lower() != target.suffix:
                                kept += 1
                            elif info.st_mtime_ns >= cutoff:
                                kept += 1
                            else:
                                files.append(Candidate(target.key, path, root, _fingerprint(info), parents))
                        except OSError as error:
                            issue(f"Skipped {path}: {error}")
                        if progress is not None and entries % 100 == 0:
                            progress(entries)
            except OSError as error:
                issue(f"Could not scan {folder}: {error}")
    files.sort(key=lambda f: (f.category, str(f.path).casefold(), str(f.path)))
    if progress is not None:
        progress(entries)
    return Plan(created, older_than, cutoff, targets, tuple(files), kept, tuple(issues), issue_count)


class FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


class HandleInfo(ctypes.Structure):
    _fields_ = [("attributes", ctypes.c_uint32), ("creation", FileTime), ("access", FileTime),
                ("write", FileTime), ("volume", ctypes.c_uint32), ("size_high", ctypes.c_uint32),
                ("size_low", ctypes.c_uint32), ("links", ctypes.c_uint32),
                ("index_high", ctypes.c_uint32), ("index_low", ctypes.c_uint32)]


class Disposition(ctypes.Structure):
    _fields_ = [("DeleteFile", ctypes.c_ubyte)]


def _kernel_api():
    _require_windows()
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    _bind(api, "CreateFileW", [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p], ctypes.c_void_p)
    _bind(api, "GetFileInformationByHandle", [ctypes.c_void_p, ctypes.POINTER(HandleInfo)], ctypes.c_int32)
    _bind(api, "GetFinalPathNameByHandleW", [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32], ctypes.c_uint32)
    _bind(api, "SetFileInformationByHandle", [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int32)
    _bind(api, "CloseHandle", [ctypes.c_void_p], ctypes.c_int32)
    return api


def _windows_delete(candidate):
    """Check and delete the same exclusively opened file, not a re-resolved name."""
    api = _kernel_api()
    # DELETE | FILE_READ_ATTRIBUTES, exclusive sharing, OPEN_EXISTING,
    # FILE_FLAG_OPEN_REPARSE_POINT. Busy/read-only/protected files are skipped.
    handle = api.CreateFileW(str(candidate.path), 0x10080, 0, None, 3, 0x00200000, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = HandleInfo()
        if not api.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        size = (info.size_high << 32) | info.size_low
        inode = (info.index_high << 32) | info.index_low
        mtime = (((info.write.high << 32) | info.write.low) - 116444736000000000) * 100
        if info.attributes & (0x400 | 0x10) or info.links != 1:
            raise SafetyError("Opened item is linked or is not a regular single-link file.")
        if (inode, size, mtime) != (candidate.fingerprint[1], candidate.size, candidate.fingerprint[3]):
            raise SafetyError("Opened file changed since preview.")
        final = ctypes.create_unicode_buffer(32768)
        length = api.GetFinalPathNameByHandleW(handle, final, len(final), 0)
        if not length or length >= len(final):
            raise SafetyError("Could not verify the opened file location.")
        name = final.value
        if name.startswith("\\\\?\\UNC\\"):
            name = "\\\\" + name[8:]
        elif name.startswith("\\\\?\\"):
            name = name[4:]
        if os.path.normcase(name) != os.path.normcase(str(candidate.path)):
            raise SafetyError("Opened file location differs from preview.")
        disposition = Disposition(1)
        # FileDispositionInfo is enum value 4; closing this handle completes deletion.
        if not api.SetFileInformationByHandle(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        api.CloseHandle(handle)


def _verify_candidate(candidate, plan):
    target = next((t for t in plan.targets if t.key == candidate.category and t.root == candidate.root), None)
    if target is None:
        raise SafetyError("File is not in a previewed category.")
    path = candidate.path
    if not path.is_absolute() or ".." in path.parts or path == candidate.root or not path.is_relative_to(candidate.root):
        raise SafetyError("File is outside its previewed cleanup folder.")
    if target.suffix and path.suffix.lower() != target.suffix:
        raise SafetyError("File type is outside its category.")
    expected_parents = tuple(reversed(path.parent.relative_to(candidate.root).parents))
    # Check the exact chain recorded by the scan, not a caller-supplied subset.
    chain = [candidate.root, *[candidate.root / p for p in expected_parents if str(p) != "."]]
    if path.parent != candidate.root:
        chain.append(path.parent)
    if [p for p, _ in candidate.parents] != chain:
        raise SafetyError("Preview folder chain is invalid.")
    for parent, identity in candidate.parents:
        current = _guard_directory(parent)
        if _identity(current) != identity:
            raise SafetyError("A previewed folder was replaced.")
    current = path.lstat()
    if _link(current) or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
        raise SafetyError("File is linked or no longer a regular file.")
    if _fingerprint(current) != candidate.fingerprint or current.st_mtime_ns >= plan.cutoff_ns:
        raise SafetyError("File changed since preview.")


def cleanup(plan, *, confirmed=False, cancel=None, progress: Callable | None = None):
    """Delete only the confirmed, fresh in-memory preview; keep every directory."""
    if confirmed is not True:
        raise SafetyError("Cleanup requires confirmation of the current preview.")
    elapsed = time.time() - plan.created
    if elapsed < -5 or elapsed > 30 * 60:
        raise SafetyError("The preview expired. Scan again before deleting.")
    result = CleanupResult()
    for number, candidate in enumerate(plan.files, 1):
        if cancel is not None and cancel.is_set():
            result.cancelled = True
            break
        try:
            _verify_candidate(candidate, plan)
            if sys.platform == "win32":
                _windows_delete(candidate)
            else:
                # Portable disposable-fixture demo/tests. The PC app is Windows only.
                candidate.path.unlink()
            result.deleted_files += 1
            result.deleted_bytes += candidate.size
        except (OSError, SafetyError) as error:
            result.skipped_files += 1
            if len(result.issues) < MAX_ISSUES:
                result.issues.append(f"Skipped {candidate.path}: {error}")
        if progress is not None:
            progress(number, len(plan.files))
    return result


def format_bytes(value):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024


def write_report(output, data, *, protected_roots=()):
    path = Path(output).absolute()
    if path.suffix.lower() != ".json":
        raise ValueError("Reports must use a .json filename.")
    resolved = path.parent.resolve() / path.name
    if any(resolved == root.resolve() or resolved.is_relative_to(root.resolve()) for root in protected_roots):
        raise SafetyError("Save reports outside cleanup folders.")
    # Exclusive creation refuses existing files and symbolic links.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def demo():
    """A real delete test, restricted to fixtures created inside this function."""
    with tempfile.TemporaryDirectory(prefix="TempSweep-demo-") as name:
        base = Path(name).resolve()
        root = base / "Temp"
        nested = root / "installer"
        nested.mkdir(parents=True)
        old = nested / "old.tmp"
        recent = root / "recent.tmp"
        outside = base / "keep-my-document.txt"
        old.write_bytes(b"disposable old temporary file\n")
        recent.write_bytes(b"recent temporary file\n")
        outside.write_text("outside the cleanup root", encoding="utf-8")
        age = time.time() - 10 * DAY
        os.utime(old, (age, age))
        plan = scan_targets([Target("demo", "Disposable demo", root)])
        result = cleanup(plan, confirmed=True)
        passed = result.deleted_files == 1 and not old.exists() and recent.is_file() and outside.is_file() and nested.is_dir()
        print(json.dumps({"demo": "disposable fixtures only", "preview_files": len(plan.files),
                          **result.report(), "recent_file_kept": recent.is_file(),
                          "outside_file_kept": outside.is_file(), "passed": passed}, indent=2))
        return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview old Windows temp files. Cleanup is interactive in TempSweep.exe; this CLI never cleans your PC.")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--demo", action="store_true", help="test cleanup on newly created disposable samples only")
    parser.add_argument("--category", action="append", choices=tuple(LABELS), help="repeat to preview multiple categories; default: user-temp")
    parser.add_argument("--older-than", type=int, default=7, metavar="DAYS")
    parser.add_argument("--json", action="store_true", help="print a JSON preview")
    parser.add_argument("--output", metavar="NEW.json", help="save a new report outside cleanup folders")
    args = parser.parse_args(argv)
    try:
        if args.demo:
            if args.category or args.output or args.older_than != 7:
                parser.error("--demo cannot be combined with real cleanup categories, output or age options")
            return demo()
        wanted = set(args.category or ["user-temp"])
        targets = [t for t in discover_targets() if t.key in wanted]
        plan = scan_targets(targets, args.older_than)
        data = plan.report()
        if args.output:
            write_report(args.output, data, protected_roots=[t.root for t in targets])
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(f"TempSweep {VERSION} | preview only | older than {plan.older_than} days")
            print(f"{len(plan.files):,} candidate files, {format_bytes(plan.size)} logical bytes; {plan.kept:,} files kept.")
            for t in targets:
                print(f"{t.label}: {t.root}")
            for issue in plan.issues:
                print(issue)
            print("Use the desktop app to review and confirm deletion. This command deleted nothing.")
        return 1 if plan.issue_count else 0
    except (OSError, ValueError) as error:
        print("TempSweep: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
