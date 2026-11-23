@echo off
REM ============================================
REM  Invoice & Billing System - Launcher
REM  Double-click to start: server runs + browser opens the app
REM ============================================
cd /d "%~dp0"

REM First-time setup? (venv missing)
if not exist "venv\Scripts\python.exe" (
    echo [SETUP] First-time setup in progress, please wait...
    python -m venv venv
    venv\Scripts\pip install -r requirements.txt
)

venv\Scripts\python launcher.py
