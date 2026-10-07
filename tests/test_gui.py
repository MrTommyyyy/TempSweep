"""Exercise real Tk widgets on Windows with disposable roots and a mock Bin."""
import json
import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from gui import TempSweepApp
from tempsweep import DAY, VERSION, Target


@unittest.skipUnless(sys.platform == "win32" or os.environ.get("TEMPSWEEP_GUI_TESTS") == "1", "Desktop checks run on Windows; opt in on another desktop")
class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.folder = self.base / "Temp"
        self.folder.mkdir()
        self.old = self.folder / "old.tmp"
        self.old.write_bytes(b"disposable")
        stamp = time.time() - 10 * DAY
        os.utime(self.old, (stamp, stamp))
        self.recent = self.folder / "recent.tmp"
        self.recent.write_bytes(b"keep recent")
        self.addCleanup(patch.stopall)
        patch("gui.discover_targets", return_value=(Target("user-temp", "Your temporary files", self.folder),)).start()
        self.query = patch("gui.query_recycle_bin", return_value={"items": 3, "bytes": 8192}).start()
        self.empty = patch("gui.empty_recycle_bin").start()
        self.errors = patch("gui.messagebox.showerror").start()
        patch("gui.messagebox.showinfo").start()
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("No Tk display: " + str(error))
        self.addCleanup(self.destroy)
        self.app = TempSweepApp(self.root)
        self.root.update()

    def destroy(self):
        self.app.closed = True
        self.root.after_cancel(self.app.timer)
        self.root.destroy()

    def wait(self, predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Desktop action did not finish in ten seconds")

    def preview(self):
        self.app.scan_button.invoke()
        self.wait(lambda: self.app.plan is not None and not self.app.busy)

    def test_startup_preview_and_age_change_requires_new_preview(self):
        self.assertIn(VERSION, self.root.title())
        self.assertEqual(self.app.age.get(), "7")
        self.assertFalse(self.app.selected["windows-temp"].get())
        self.assertFalse(self.app.selected["crash-dumps"].get())
        self.assertEqual(str(self.app.clean_button["state"]), "disabled")
        self.preview()
        self.assertEqual(len(self.app.tree.get_children()), 1)
        self.assertTrue(self.old.exists())
        self.app.age_choice.set("14")
        self.app.age_choice.event_generate("<<ComboboxSelected>>")
        self.root.update()
        self.assertIsNone(self.app.plan)
        self.assertEqual(str(self.app.clean_button["state"]), "disabled")
        self.preview()
        self.assertEqual(len(self.app.tree.get_children()), 0)

    def test_cancel_delete_then_confirm_keeps_recent_and_requires_new_preview(self):
        self.preview()
        with patch("gui.messagebox.askyesno", return_value=False):
            self.app.clean_button.invoke()
        self.assertTrue(self.old.exists())
        with patch("gui.messagebox.askyesno", return_value=True):
            self.app.clean_button.invoke()
        self.wait(lambda: not self.app.busy)
        self.assertFalse(self.old.exists())
        self.assertTrue(self.recent.exists())
        self.empty.assert_not_called()
        self.assertIsNone(self.app.plan)
        self.assertEqual(str(self.app.clean_button["state"]), "disabled")
        self.assertEqual(self.app.last_report["deleted_files"], 1)
        self.errors.assert_not_called()

    def test_bin_requires_separate_confirmation_and_does_not_clean_temp(self):
        self.preview()
        with patch("gui.messagebox.askyesno", return_value=False):
            self.app.bin_button.invoke()
        self.empty.assert_not_called()
        with patch("gui.messagebox.askyesno", return_value=True):
            self.app.bin_button.invoke()
        self.wait(lambda: not self.app.busy)
        self.empty.assert_called_once_with(confirmed=True)
        self.assertTrue(self.old.exists())
        self.query.assert_called()

    def test_report_export_does_not_replace_existing_report(self):
        self.preview()
        report = self.base / "report.json"
        with patch("gui.filedialog.asksaveasfilename", return_value=str(report)):
            self.app.save_button.invoke()
        data = json.loads(report.read_text())
        self.assertEqual(data["candidate_files"], 1)
        with patch("gui.filedialog.asksaveasfilename", return_value=str(report)):
            self.app.save_button.invoke()
        self.assertEqual(json.loads(report.read_text()), data)
        self.errors.assert_called_once()

    def test_bin_failure_and_resize(self):
        self.query.side_effect = OSError("synthetic unavailable Bin")
        self.preview()
        self.assertIsNone(self.app.bin_info)
        self.assertEqual(str(self.app.bin_button["state"]), "disabled")
        self.root.geometry("760x590")
        self.root.update()
        self.assertLessEqual(self.app.status_label["wraplength"], 720)
        for button in (self.app.scan_button, self.app.clean_button, self.app.save_button, self.app.stop_button, self.app.bin_button):
            self.assertLessEqual(button.winfo_rootx() + button.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())


if __name__ == "__main__":
    unittest.main()
