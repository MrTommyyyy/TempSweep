"""Test the packaged CLI; deletion happens only in newly created demo fixtures."""
import json
from pathlib import Path
import subprocess

exe = Path("dist/TempSweep-CLI.exe")
version = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=30)
assert version.returncode == 0 and version.stdout.strip() == "0.1.0", version
demo = subprocess.run([str(exe), "--demo"], capture_output=True, text=True, timeout=45)
assert demo.returncode == 0, demo.stdout + demo.stderr
data = json.loads(demo.stdout)
assert data["passed"] and data["deleted_files"] == 1 and data["skipped_files"] == 0, data
assert data["recent_file_kept"] and data["outside_file_kept"], data
invalid = subprocess.run([str(exe), "--older-than", "0"], capture_output=True, text=True, timeout=30)
assert invalid.returncode == 2 and "1 to 365" in invalid.stderr, invalid
print("Packaged CLI: correct version; disposable cleanup; recent/outside files kept; invalid age rejected.")
