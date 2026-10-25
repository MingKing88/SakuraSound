@echo off
cd /d %~dp0
python qt_app.py
if errorlevel 1 pause
