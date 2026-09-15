@echo off
rem ============================================================
rem  Local dev: start site on :8000 reading the MySQL comic database
rem  (use the Docker setup under deploy/ for production).
rem ============================================================
rem  Start site on :8000 reading the MySQL comic database (唯·存储方案).
rem  Requires: DB container up (宿主 127.0.0.1:3309; 参数自动读 deploy\.env,
rem  override with COMIC_MYSQL_* -- see crawler-service README)
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
