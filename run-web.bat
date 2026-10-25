@echo off
cd /d %~dp0
python web\server.py
if errorlevel 1 pause
