@echo off
rem DesktopPet one-click launcher (ASCII-only, uses %~dp0 to avoid path encoding issues)
cd /d %~dp0
start "" ".venv\Scripts\pythonw.exe" main.py
