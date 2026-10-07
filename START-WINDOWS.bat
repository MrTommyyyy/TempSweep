@echo off
cd /d "%~dp0"
py -3 gui.py
if errorlevel 1 (
  echo Could not start TempSweep. The source version requires Python 3.11+ with Tk.
  echo For a portable app, download the Windows-x64.zip from GitHub Releases.
  pause
)
