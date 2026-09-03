@echo off
rem ============================================================
rem  Release mode (SQLite, no MySQL needed): start site on :8000
rem  Serves comic-deploy (comic_crawler + dist + comic_demo.db created by cli run)
rem  NOTE: repo ships no data file - run cli run first to populate comic_demo.db
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0..\comic-deploy"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found. Install Python 3.10+ first.
    exit /b 1
)

echo Starting comic site (SQLite mode) on http://127.0.0.1:8000 ...
python -m uvicorn main:app --host 127.0.0.1 --port 8000
