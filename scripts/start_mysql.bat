@echo off
rem ============================================================
rem  Start site on :8000 reading the MySQL comic database (唯·存储方案).
rem  Requires: local/remote MySQL reachable (see crawler-service
rem  README for COMIC_MYSQL_* env overrides, default 3307/root/password)
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0..\api-service"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found. Install Python 3.10+ first.
    exit /b 1
)

echo Starting comic site (MySQL mode) on http://127.0.0.1:8000 ...
python -m uvicorn main:app --host 127.0.0.1 --port 8000
