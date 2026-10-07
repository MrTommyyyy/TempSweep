"""Package tracked source files for the release; never include local scratch files."""
from pathlib import Path
import subprocess
import sys
import zipfile

name, version = sys.argv[1:]
files = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
with zipfile.ZipFile(f"{name}-{version}-Source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for file in files:
        if file and Path(file).is_file():
            archive.write(file, f"{name}-{version}/{file}")
