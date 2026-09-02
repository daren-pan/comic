@echo off
rem ============================================================
rem  Refresh the two offline SQLite data files from MySQL comic db
rem  (requires pymysql: pip install -r crawler-service/requirements.txt)
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
python tools\sync_mysql_to_sqlite.py
if errorlevel 1 (
    echo [ERROR] sync failed. Check MySQL reachable (COMIC_MYSQL_* overrides available).
    exit /b 1
)
echo Done. crawler-service/comic_demo.db and comic-deploy/comic_demo.db refreshed.
