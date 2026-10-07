"""Windows desktop interface for TempSweep."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from tempsweep import (VERSION, LABELS, CleanupResult, Plan, cleanup, discover_targets,
                       empty_recycle_bin, format_bytes, query_recycle_bin, scan_targets,
                       write_report)


class TempSweepApp:
    def __init__(self, root):
        self.root = root
        self.plan = None
        self.last_report = None
        self.busy = False
        self.bin_info = None
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.closed = False
        root.title(f"TempSweep {VERSION}")
        root.geometry("980x730")
        root.minsize(760, 590)
        root.configure(bg="#f1f5f9")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f1f5f9")
        style.configure("TLabel", background="#f1f5f9", foreground="#0f172a", font=("Segoe UI", 10))
        style.configure("TCheckbutton", background="#f1f5f9", font=("Segoe UI", 10))
        style.configure("TButton", padding=(10, 7), font=("Segoe UI", 10))
        style.configure("Accent.TButton", background="#0f766e", foreground="white")
        style.map("Accent.TButton", background=[("active", "#115e59"), ("disabled", "#cbd5e1")])
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=27)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)
        header = tk.Frame(root, bg="#0f172a", padx=20, pady=14)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="TempSweep", bg="#0f172a", fg="white", font=("Segoe UI", 23, "bold")).pack(anchor="w")
        tk.Label(header, text="Preview first. Clean what you choose.", bg="#0f172a", fg="#5eead4", font=("Segoe UI", 11)).pack(anchor="w")
        options = ttk.Frame(root, padding=(20, 12, 20, 0))
        options.grid(row=1, column=0, sticky="ew")
        options.columnconfigure(0, weight=1)
        try:
            self.targets = discover_targets()
            discovery_error = None
        except (OSError, ValueError) as error:
            self.targets = ()
            discovery_error = str(error)
        self.selected = {}
        self.toggles = []
        for row, key in enumerate(LABELS):
            variable = tk.BooleanVar(value=key == "user-temp")
            self.selected[key] = variable
            target = next((t for t in self.targets if t.key == key), None)
            extra = " — optional; keep dumps if investigating a crash" if key == "crash-dumps" else " — optional; protected files may be skipped" if key == "windows-temp" else " — selected by default"
            toggle = ttk.Checkbutton(options, text=LABELS[key] + extra, variable=variable, command=self.invalidate)
            toggle.grid(row=row * 2, column=0, sticky="w")
            self.toggles.append(toggle)
            label = ttk.Label(options, text=str(target.root) if target else "Folder unavailable", foreground="#64748b", font=("Segoe UI", 9))
            label.grid(row=row * 2 + 1, column=0, sticky="w", padx=(25, 0))
        controls = ttk.Frame(root, padding=(20, 10))
        controls.grid(row=2, column=0, sticky="ew")
        ttk.Label(controls, text="Keep files modified within the last").pack(side="left")
        self.age = tk.StringVar(value="7")
        self.age_choice = ttk.Combobox(controls, textvariable=self.age, values=("1", "7", "14", "30", "90", "365"), state="readonly", width=5)
        self.age_choice.pack(side="left", padx=6)
        self.age_choice.bind("<<ComboboxSelected>>", lambda _event: self.invalidate())
        ttk.Label(controls, text="days").pack(side="left")
        self.scan_button = ttk.Button(controls, text="Preview cleanup", style="Accent.TButton", command=self.preview)
        self.scan_button.pack(side="right")
        self.summary = tk.StringVar(value="Choose categories, then preview. Nothing is deleted during a preview.")
        ttk.Label(root, textvariable=self.summary, padding=(20, 0, 20, 10), font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky="ew")
        table = ttk.Frame(root, padding=(20, 0))
        table.grid(row=4, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=("category", "file", "size", "modified"), show="headings")
        for key, text, width in (("category", "Category", 130), ("file", "File inside cleanup folder", 370), ("size", "Size", 95), ("modified", "Last modified", 150)):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, minwidth=65, stretch=key == "file")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        actions = ttk.Frame(root, padding=(20, 10))
        actions.grid(row=5, column=0, sticky="ew")
        self.clean_button = ttk.Button(actions, text="Delete previewed files…", command=self.clean, state="disabled")
        self.clean_button.pack(side="left")
        self.save_button = ttk.Button(actions, text="Save report", command=self.save, state="disabled")
        self.save_button.pack(side="left", padx=8)
        self.stop_button = ttk.Button(actions, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="right")
        bin_row = ttk.Frame(root, padding=(20, 0, 20, 10))
        bin_row.grid(row=6, column=0, sticky="ew")
        self.bin_text = tk.StringVar(value="Recycle Bin: refresh during preview; emptied only with separate confirmation.")
        ttk.Label(bin_row, textvariable=self.bin_text).pack(side="left", fill="x", expand=True)
        self.bin_button = ttk.Button(bin_row, text="Empty Recycle Bin…", command=self.empty_bin, state="disabled")
        self.bin_button.pack(side="right", padx=(10, 0))
        bottom = ttk.Frame(root, padding=(20, 0, 20, 12))
        bottom.grid(row=7, column=0, sticky="ew")
        self.status = tk.StringVar(value=discovery_error or "Ready. Close installers and apps before cleaning their old temporary files.")
        self.status_label = ttk.Label(bottom, textvariable=self.status, foreground="#475569", wraplength=900)
        self.status_label.pack(anchor="w", fill="x")
        self.progress = ttk.Progressbar(bottom, mode="indeterminate")
        self.progress.pack(fill="x", pady=(6, 0))
        self.details = tk.Text(bottom, height=3, wrap="word", bg="#e2e8f0", fg="#334155", relief="flat", font=("Segoe UI", 9), state="disabled")
        self.details.pack(fill="x", pady=(8, 0))
        root.bind("<Configure>", self.resize)
        if not self.targets:
            self.scan_button.configure(state="disabled")
        self.timer = root.after(50, self.poll)

    def resize(self, event):
        if event.widget is self.root:
            self.status_label.configure(wraplength=max(300, event.width - 45))

    def invalidate(self):
        if self.busy:
            return
        self.plan = None
        self.clean_button.configure(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self.summary.set("Options changed. Preview again before deleting files.")

    def set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", tk.END)
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def start(self, action, task):
        if self.busy:
            return
        self.busy = True
        self.cancel_event.clear()
        self.scan_button.configure(state="disabled")
        self.clean_button.configure(state="disabled")
        self.bin_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.stop_button.configure(state="normal" if action != "bin" else "disabled")
        for toggle in self.toggles:
            toggle.configure(state="disabled")
        self.age_choice.configure(state="disabled")
        self.progress.start(15)

        def run():
            try:
                self.events.put((action, task()))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=run, daemon=True).start()

    def finish(self):
        self.busy = False
        self.progress.stop()
        self.scan_button.configure(state="normal" if self.targets else "disabled")
        self.clean_button.configure(state="normal" if self.plan and self.plan.files else "disabled")
        self.save_button.configure(state="normal" if self.last_report is not None else "disabled")
        self.bin_button.configure(state="normal" if self.bin_info and self.bin_info["items"] > 0 else "disabled")
        self.stop_button.configure(state="disabled")
        for toggle in self.toggles:
            toggle.configure(state="normal")
        self.age_choice.configure(state="readonly")

    def preview(self):
        if self.busy:
            return
        selected = tuple(t for t in self.targets if self.selected[t.key].get())
        if not selected:
            messagebox.showinfo("Choose a category", "Select at least one cleanup category.", parent=self.root)
            return
        self.plan = None
        self.status.set("Scanning selected folders. Nothing is being deleted.")
        self.set_details("")
        age = int(self.age.get())

        def task():
            plan = scan_targets(selected, age, cancel=self.cancel_event, progress=lambda n: self.events.put(("scan-progress", n)))
            try:
                recycle = query_recycle_bin()
            except OSError as error:
                recycle = {"error": str(error)}
            return plan, recycle
        self.start("preview", task)

    def show_plan(self, plan: Plan):
        self.plan = plan
        self.last_report = plan.report()
        self.tree.delete(*self.tree.get_children())
        for f in plan.files:
            self.tree.insert("", "end", values=(f.category, str(f.path.relative_to(f.root)), format_bytes(f.size), datetime.fromtimestamp(f.fingerprint[3] / 1e9).strftime("%Y-%m-%d %H:%M")))
        self.summary.set(f"{len(plan.files):,} files eligible · {format_bytes(plan.size)} logical bytes · {plan.kept:,} files kept · older than {plan.older_than} days")
        self.status.set(f"Preview complete. {plan.issue_count:,} scan issue(s). Review the list before deleting.")
        details = "\n".join(plan.issues)
        if plan.issue_count > len(plan.issues):
            details += f"\nShowing the first {len(plan.issues)} issues."
        self.set_details(details or "Recent files are kept. Links and junctions are skipped. Directories stay in place.")

    def clean(self):
        if self.busy or self.plan is None or not self.plan.files:
            return
        plan = self.plan
        # The options cannot change while this modal is displayed.
        if not messagebox.askyesno("Delete the previewed files?", f"Permanently delete {len(plan.files):,} previewed files ({format_bytes(plan.size)} logical bytes)?\n\nThese files will not go to the Recycle Bin and TempSweep cannot restore them. Only the files in this preview will be attempted; changed, busy or protected files are skipped.\n\nThe Recycle Bin is a separate action.", parent=self.root, default="no", icon="warning"):
            self.status.set("Cleanup cancelled. Nothing was deleted.")
            return
        self.plan = None
        self.status.set("Deleting confirmed files. Stop prevents further deletions; it cannot restore completed ones.")
        self.start("cleanup", lambda: cleanup(plan, confirmed=True, cancel=self.cancel_event, progress=lambda n, total: self.events.put(("clean-progress", (n, total)))))

    def empty_bin(self):
        if self.busy or not self.bin_info:
            return
        # Refresh now so consent is based on current totals, not an old preview.
        try:
            info = query_recycle_bin()
        except OSError as error:
            messagebox.showerror("Could not query Recycle Bin", str(error), parent=self.root)
            return
        if not info["items"]:
            self.bin_info = info
            self.bin_text.set("Recycle Bin: already empty.")
            self.bin_button.configure(state="disabled")
            return
        if not messagebox.askyesno("Empty your Recycle Bin on all drives?", f"Permanently delete every item in your Recycle Bin on all drives?\n\nWindows currently reports {info['items']:,} items ({format_bytes(info['bytes'])}). Files added before the operation finishes are included too.\n\nThe file-age setting does not apply to the Recycle Bin. TempSweep cannot restore these items.", parent=self.root, default="no", icon="warning"):
            self.status.set("Recycle Bin action cancelled. Nothing was emptied.")
            return
        self.status.set("Emptying the Recycle Bin…")

        def task():
            empty_recycle_bin(confirmed=True)
            try:
                return query_recycle_bin()
            except OSError as error:
                return {"error": str(error)}
        self.start("bin", task)

    def save(self):
        if self.busy or self.last_report is None:
            return
        name = filedialog.asksaveasfilename(parent=self.root, title="Save a new report", defaultextension=".json", filetypes=[("JSON report", "*.json")])
        if not name:
            return
        try:
            write_report(name, self.last_report, protected_roots=[t.root for t in self.targets])
            self.status.set("Report saved. Review private paths before sharing it.")
        except (OSError, ValueError) as error:
            messagebox.showerror("Report was not saved", str(error), parent=self.root)

    def stop(self):
        if self.busy:
            self.cancel_event.set()
            self.stop_button.configure(state="disabled")
            self.status.set("Stopping after the current file…")

    def update_bin(self, info):
        if "error" in info:
            self.bin_info = None
            self.bin_text.set("Recycle Bin unavailable: " + info["error"])
        else:
            self.bin_info = info
            self.bin_text.set(f"Recycle Bin: {info['items']:,} items · {format_bytes(info['bytes'])} · separate action")

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                action, value = self.events.get_nowait()
                if action == "scan-progress":
                    self.status.set(f"Preview: {value:,} entries checked. Nothing deleted.")
                elif action == "clean-progress":
                    self.status.set(f"Cleanup: {value[0]:,} of {value[1]:,} previewed files attempted.")
                elif action == "preview":
                    self.show_plan(value[0])
                    self.update_bin(value[1])
                    self.finish()
                elif action == "cleanup":
                    result: CleanupResult = value
                    self.last_report = result.report()
                    self.tree.delete(*self.tree.get_children())
                    state = "Stopped" if result.cancelled else "Cleanup complete"
                    self.summary.set(f"{state} · {result.deleted_files:,} files deleted · {format_bytes(result.deleted_bytes)} logical bytes · {result.skipped_files:,} skipped")
                    self.status.set("Preview again to see what remains. Completed deletions cannot be restored.")
                    self.set_details("\n".join(result.issues) or "Only confirmed preview files were deleted. Directories were kept.")
                    self.finish()
                elif action == "bin":
                    self.update_bin(value)
                    self.status.set("Windows completed the Recycle Bin operation. Remaining totals are shown above.")
                    self.finish()
                elif action == "error":
                    self.plan = None
                    self.summary.set("Action stopped. Preview again before cleaning.")
                    self.status.set(value)
                    self.set_details(value)
                    self.finish()
        except queue.Empty:
            pass
        self.timer = self.root.after(50, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo("An action is running", "Wait for the action to finish, or use Stop and then close the window.", parent=self.root)
            return
        self.closed = True
        self.root.after_cancel(self.timer)
        self.root.destroy()


def main():
    root = tk.Tk()
    TempSweepApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
