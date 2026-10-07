"""Deletion tests are restricted to fresh disposable directories."""
import contextlib
import ctypes
import io
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tempsweep as ts


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "Temp"
        self.root.mkdir()
        self.target = ts.Target("sample", "Disposable samples", self.root)

    def file(self, name="old.tmp", age=10, data=b"sample"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        stamp = time.time() - age * ts.DAY
        os.utime(path, (stamp, stamp))
        return path

    def scan(self, **kwargs):
        return ts.scan_targets([self.target], **kwargs)

    def test_preview_does_not_delete_and_respects_age_and_subfolders(self):
        old = self.file("nested/old.tmp")
        recent = self.file("recent.tmp", 2)
        future = self.file("future.tmp", -2)
        plan = self.scan()
        self.assertEqual([f.path for f in plan.files], [old])
        self.assertEqual(plan.kept, 2)
        self.assertEqual(plan.size, 6)
        self.assertTrue(all(p.exists() for p in (old, recent, future)))

    def test_age_boundary_is_kept_and_invalid_ages_fail(self):
        path = self.file()
        plan = self.scan()
        os.utime(path, ns=(plan.cutoff_ns, plan.cutoff_ns))
        exact = self.scan(now=plan.created)
        self.assertEqual(exact.files, ())
        for age in (0, -1, 366, 1.5, True):
            with self.subTest(age=age), self.assertRaises(ValueError):
                self.scan(older_than=age)

    def test_cleanup_requires_confirmation(self):
        path = self.file()
        plan = self.scan()
        for flag in (False, None, 1, "yes"):
            with self.subTest(flag=flag), self.assertRaises(ts.SafetyError):
                ts.cleanup(plan, confirmed=flag)
        self.assertTrue(path.is_file())

    def test_confirmed_cleanup_keeps_recent_outside_files_and_folders(self):
        old = self.file("one/two/old.tmp")
        recent = self.file("recent.tmp", 2)
        outside = self.base / "my-document.txt"
        outside.write_text("keep", encoding="utf-8")
        result = ts.cleanup(self.scan(), confirmed=True)
        self.assertEqual((result.deleted_files, result.skipped_files), (1, 0), result.issues)
        self.assertFalse(old.exists())
        self.assertTrue(old.parent.is_dir())
        self.assertTrue(recent.exists() and outside.exists() and self.root.is_dir())

    def test_changed_and_missing_files_are_skipped(self):
        changed = self.file("a.tmp")
        missing = self.file("b.tmp")
        plan = self.scan()
        changed.write_bytes(b"new content")
        missing.unlink()
        result = ts.cleanup(plan, confirmed=True)
        self.assertEqual((result.deleted_files, result.skipped_files), (0, 2))
        self.assertEqual(changed.read_bytes(), b"new content")

    def test_replacement_with_same_length_and_mtime_is_kept(self):
        path = self.file()
        plan = self.scan()
        previous = path.stat()
        path.rename(self.root / "moved.tmp")
        path.write_bytes(b"sample")
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        result = ts.cleanup(plan, confirmed=True)
        self.assertEqual(result.skipped_files, 1)
        self.assertTrue(path.exists())

    def test_parent_folder_replacement_is_kept(self):
        path = self.file("nested/old.tmp")
        plan = self.scan()
        path.parent.rename(self.root / "previous")
        self.file("nested/old.tmp")
        result = ts.cleanup(plan, confirmed=True)
        self.assertEqual((result.deleted_files, result.skipped_files), (0, 1))
        self.assertTrue(path.exists())

    def test_modified_preview_cannot_delete_an_outside_file(self):
        self.file()
        plan = self.scan()
        outside = self.base / "private.txt"
        outside.write_bytes(b"sample")
        fake = replace(plan.files[0], path=outside, fingerprint=ts._fingerprint(outside.stat()))
        result = ts.cleanup(replace(plan, files=(fake,)), confirmed=True)
        self.assertEqual(result.skipped_files, 1)
        self.assertTrue(outside.exists())

    def test_missing_folder_chain_is_rejected(self):
        path = self.file("nested/old.tmp")
        plan = self.scan()
        fake = replace(plan.files[0], parents=())
        result = ts.cleanup(replace(plan, files=(fake,)), confirmed=True)
        self.assertEqual(result.skipped_files, 1)
        self.assertTrue(path.exists())

    def test_expired_preview_is_rejected(self):
        path = self.file()
        plan = self.scan()
        with self.assertRaises(ts.SafetyError):
            ts.cleanup(replace(plan, created=time.time() - 1801), confirmed=True)
        with self.assertRaises(ts.SafetyError):
            ts.cleanup(replace(plan, created=time.time() + 60), confirmed=True)
        self.assertTrue(path.exists())

    def test_cancellation_stops_further_deletion(self):
        a, b = self.file("a.tmp"), self.file("b.tmp")
        cancel = threading.Event()
        result = ts.cleanup(self.scan(), confirmed=True, cancel=cancel, progress=lambda n, total: cancel.set())
        self.assertEqual(result.deleted_files, 1)
        self.assertTrue(result.cancelled)
        self.assertFalse(a.exists())
        self.assertTrue(b.exists())
        with self.assertRaises(InterruptedError):
            self.scan(cancel=cancel)

    def test_permission_failure_does_not_stop_other_files(self):
        a, b = self.file("a.tmp"), self.file("b.tmp")
        plan = self.scan()
        original = ts._windows_delete if sys.platform == "win32" else Path.unlink

        def deny_one(arg, *args, **kwargs):
            path = arg.path if isinstance(arg, ts.Candidate) else arg
            if path == a:
                raise PermissionError("synthetic locked file")
            return original(arg, *args, **kwargs)
        name = "tempsweep._windows_delete" if sys.platform == "win32" else "pathlib.Path.unlink"
        with patch(name, side_effect=deny_one) if sys.platform == "win32" else patch(name, deny_one):
            result = ts.cleanup(plan, confirmed=True)
        self.assertEqual((result.deleted_files, result.skipped_files), (1, 1), result.issues)
        self.assertTrue(a.exists())
        self.assertFalse(b.exists())

    def test_crash_dump_category_keeps_other_extensions(self):
        dmp = self.file("crash.DMP")
        txt = self.file("notes.txt")
        target = replace(self.target, suffix=".dmp")
        plan = ts.scan_targets([target])
        self.assertEqual([f.path for f in plan.files], [dmp])
        ts.cleanup(plan, confirmed=True)
        self.assertTrue(txt.exists())

    def test_hard_links_are_kept(self):
        a = self.file("a.tmp")
        try:
            os.link(a, self.root / "b.tmp")
        except OSError as error:
            self.skipTest("Hard links unavailable: " + str(error))
        plan = self.scan()
        self.assertEqual(plan.files, ())
        self.assertEqual(plan.issue_count, 2)

    def test_symlink_file_folder_and_root_are_skipped(self):
        outside = self.base / "outside"
        outside.mkdir()
        target = outside / "document.txt"
        target.write_bytes(b"keep")
        age = time.time() - 10 * ts.DAY
        os.utime(target, (age, age))
        try:
            (self.root / "linked-file").symlink_to(target)
            (self.root / "linked-folder").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest("Symbolic links unavailable: " + str(error))
        plan = self.scan()
        self.assertEqual(plan.files, ())
        self.assertEqual(plan.issue_count, 2)
        root_plan = ts.scan_targets([replace(self.target, root=self.root / "linked-folder")])
        self.assertEqual(root_plan.files, ())
        self.assertGreater(root_plan.issue_count, 0)
        self.assertTrue(target.exists())

    def test_reparse_attribute_is_treated_as_a_link(self):
        self.assertTrue(ts._link(SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)))

    def test_overlapping_roots_and_relative_roots_are_rejected(self):
        with self.assertRaises(ts.SafetyError):
            ts.scan_targets([self.target, ts.Target("two", "Nested", self.root / "nested")])
        with self.assertRaises(ts.SafetyError):
            ts.scan_targets([replace(self.target, root=Path("Temp"))])
        with self.assertRaises(ts.SafetyError):
            ts.scan_targets([replace(self.target, root=self.root / ".." / "Temp")])
        with self.assertRaises(ValueError):
            ts.scan_targets([self.target, self.target])

    def test_scan_limit_returns_no_partial_plan(self):
        self.file("a.tmp")
        self.file("b.tmp")
        with self.assertRaises(ts.SafetyError):
            self.scan(max_entries=1)
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_missing_root_is_reported(self):
        plan = ts.scan_targets([replace(self.target, root=self.base / "missing")])
        self.assertEqual(plan.files, ())
        self.assertEqual(plan.issue_count, 1)

    def test_report_export_refuses_overwrite_symlinks_and_cleanup_folders(self):
        self.file()
        data = self.scan().report()
        output = self.base / "report.json"
        ts.write_report(output, data, protected_roots=[self.root])
        self.assertEqual(json.loads(output.read_text()), data)
        with self.assertRaises(FileExistsError):
            ts.write_report(output, {"replacement": True})
        with self.assertRaises(ValueError):
            ts.write_report(self.base / "not-json.txt", data)
        with self.assertRaises(ts.SafetyError):
            ts.write_report(self.root / "report.json", data, protected_roots=[self.root])
        self.assertEqual(json.loads(output.read_text()), data)
        link = self.base / "link.json"
        try:
            link.symlink_to(output)
        except OSError:
            return
        with self.assertRaises(FileExistsError):
            ts.write_report(link, {"replacement": True})

    def test_cli_preview_never_calls_cleanup_and_exports_report(self):
        self.file()
        output = self.base / "preview.json"
        stdout = io.StringIO()
        with patch("tempsweep.discover_targets", return_value=(replace(self.target, key="user-temp"),)), patch("tempsweep.cleanup") as delete, contextlib.redirect_stdout(stdout):
            code = ts.main(["--json", "--output", str(output)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["candidate_files"], 1)
        self.assertTrue(output.exists())
        delete.assert_not_called()

    def test_disposable_demo(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ts.demo(), 0)
        self.assertTrue(json.loads(output.getvalue())["passed"])


class RecycleTests(unittest.TestCase):
    def test_no_confirmation_means_no_api_call(self):
        with patch("tempsweep._shell_api") as api:
            with self.assertRaises(ts.SafetyError):
                ts.empty_recycle_bin()
        api.assert_not_called()

    def test_query_structure_and_empty_flags(self):
        shell = Mock()

        def query(drive, pointer):
            self.assertIsNone(drive)
            self.assertEqual(pointer._obj.cbSize, ctypes.sizeof(ts.RecycleInfo))
            pointer._obj.i64Size = 4096
            pointer._obj.i64NumItems = 3
            return 0
        shell.SHQueryRecycleBinW.side_effect = query
        shell.SHEmptyRecycleBinW.return_value = 0
        with patch("tempsweep._shell_api", return_value=shell):
            self.assertEqual(ts.query_recycle_bin(), {"bytes": 4096, "items": 3})
            ts.empty_recycle_bin(confirmed=True)
        shell.SHEmptyRecycleBinW.assert_called_once_with(None, None, 7)

    def test_shell_failure_is_reported(self):
        shell = Mock()
        shell.SHQueryRecycleBinW.return_value = -2147024891
        shell.SHEmptyRecycleBinW.return_value = -2147024891
        with patch("tempsweep._shell_api", return_value=shell):
            with self.assertRaisesRegex(OSError, "80070005"):
                ts.query_recycle_bin()
            with self.assertRaisesRegex(OSError, "80070005"):
                ts.empty_recycle_bin(confirmed=True)

    def test_negative_totals_are_rejected(self):
        shell = Mock()

        def query(drive, pointer):
            pointer._obj.i64Size = -1
            return 0
        shell.SHQueryRecycleBinW.side_effect = query
        with patch("tempsweep._shell_api", return_value=shell), self.assertRaises(OSError):
            ts.query_recycle_bin()


if __name__ == "__main__":
    unittest.main()
