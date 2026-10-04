@echo off
cd /d %~dp0
python steve_app.py
if errorlevel 1 pause
