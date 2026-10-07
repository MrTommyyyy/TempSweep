"""Actual Windows file handles/junctions; never empty a real Recycle Bin."""
import ctypes
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import tempsweep as ts


@unittest.skipUnless(sys.platform == "win32", "Native Windows filesystem checks")
class WindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "Temp"
        self.root.mkdir()
        self.path = self.root / "old.tmp"
        self.path.write_bytes(b"disposable")
        stamp = time.time() - 10 * ts.DAY
        os.utime(self.path, (stamp, stamp))
        self.target = ts.Target("fixture", "Disposable test", self.root)

    def test_exclusive_open_file_is_skipped_then_deletes_after_release(self):
        plan = ts.scan_targets([self.target])
        api = ts._kernel_api()
        # Attribute-only handles do not impose a data sharing lock. Open the
        # contents with GENERIC_READ and no sharing to exercise a real lock.
        handle = api.CreateFileW(str(self.path), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            result = ts.cleanup(plan, confirmed=True)
            self.assertEqual((result.deleted_files, result.skipped_files), (0, 1))
            self.assertTrue(self.path.exists())
        finally:
            api.CloseHandle(handle)
        result = ts.cleanup(plan, confirmed=True)
        self.assertEqual((result.deleted_files, result.skipped_files), (1, 0), result.issues)
        self.assertFalse(self.path.exists())

    def test_readonly_file_is_kept(self):
        os.chmod(self.path, stat.S_IREAD)
        try:
            result = ts.cleanup(ts.scan_targets([self.target]), confirmed=True)
            self.assertEqual((result.deleted_files, result.skipped_files), (0, 1))
            self.assertTrue(self.path.exists())
        finally:
            if self.path.exists():
                os.chmod(self.path, stat.S_IWRITE | stat.S_IREAD)

    def test_junction_is_not_followed(self):
        outside = self.base / "outside"
        outside.mkdir()
        document = outside / "keep.txt"
        document.write_text("keep", encoding="utf-8")
        stamp = time.time() - 10 * ts.DAY
        os.utime(document, (stamp, stamp))
        junction = self.root / "linked"
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True, text=True)
        self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
        self.addCleanup(lambda: junction.rmdir() if junction.exists() else None)
        plan = ts.scan_targets([self.target])
        self.assertEqual([f.path for f in plan.files], [self.path])
        self.assertGreater(plan.issue_count, 0)
        result = ts.cleanup(plan, confirmed=True)
        self.assertEqual(result.deleted_files, 1, result.issues)
        self.assertTrue(document.exists() and junction.exists())

    def test_discovery_uses_known_folders_and_only_fixed_subfolders(self):
        targets = ts.discover_targets()
        self.assertEqual([t.key for t in targets], ["user-temp", "windows-temp", "crash-dumps"])
        self.assertEqual([t.root.name for t in targets], ["Temp", "Temp", "CrashDumps"])
        self.assertTrue(all(t.root.is_absolute() for t in targets))
        self.assertEqual(targets[-1].suffix, ".dmp")


if __name__ == "__main__":
    unittest.main()
