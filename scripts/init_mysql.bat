@echo off
rem ============================================================
rem  Init MySQL database "comic" schema from crawler-service/sql/mysql_schema.sql
rem  Idempotent: CREATE DATABASE IF NOT EXISTS + DROP TABLE + re-create.
rem  WARNING: existing comic.* tables in target MySQL will be DROPPED!
rem  Usage:  init_mysql.bat [mysql-host] [port]
rem ============================================================
chcp 65001 >nul
set HOST=%~1
set PORT=%~2
if "%HOST%"=="" set HOST=127.0.0.1
if "%PORT%"=="" set PORT=3307

cd /d "%~dp0.."

echo Importing schema into mysql://%HOST%:%PORT% ...
mysql -h%HOST% -P%PORT% -uroot -ppassword --default-character-set=utf8mb4 < crawler-service\sql\mysql_schema.sql
if errorlevel 1 (
    echo [ERROR] import failed. Check MySQL reachable and credentials (root/password).
    exit /b 1
)
echo Done. comic schema ready (tables created; run cli run to populate data).
