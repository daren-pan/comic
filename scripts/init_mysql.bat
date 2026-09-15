@echo off
rem ============================================================
rem  Import crawler-service\sql\mysql_schema.sql into a MySQL (create db + tables).
rem  Idempotent: CREATE DATABASE IF NOT EXISTS + CREATE TABLE IF NOT EXISTS only.
rem  The schema contains NO DROP, so existing data is NEVER deleted.
rem
rem  NOTE: usually NOT needed -- the bundled comic-mysql container runs the schema
rem        automatically on first init of an empty volume. Use this only when
rem        pointing at an EXTERNAL MySQL.
rem
rem  Password source: COMIC_MYSQL_PASSWORD env var, else deploy\.env
rem                   (COMIC_MYSQL_PASSWORD, falling back to MYSQL_ROOT_PASSWORD)
rem  Usage:  init_mysql.bat [mysql-host] [port]
rem ============================================================
chcp 65001 >nul
set HOST=%~1
set PORT=%~2
if "%HOST%"=="" set HOST=127.0.0.1
if "%PORT%"=="" if defined MYSQL_HOST_PORT (set PORT=%MYSQL_HOST_PORT%) else (set PORT=3309)
set "DB=%COMIC_MYSQL_DB%"
if "%DB%"=="" set DB=comic

cd /d "%~dp0.."

set "PW=%COMIC_MYSQL_PASSWORD%"
if "%PW%"=="" if exist "deploy\.env" (
    for /f "usebackq tokens=1,* delims==" %%a in ("deploy\.env") do (
        if /i "%%a"=="MYSQL_ROOT_PASSWORD" set "PW=%%b"
        if /i "%%a"=="COMIC_MYSQL_PASSWORD" set "PW=%%b"
    )
)
if "%PW%"=="" (
    echo [ERROR] No DB password found. Set COMIC_MYSQL_PASSWORD, or run:
    echo           copy deploy\.env.example deploy\.env   ^&^&  fill MYSQL_ROOT_PASSWORD
    exit /b 1
)

echo Importing schema into mysql://%HOST%:%PORT%/%DB% ...
rem The schema is pure DDL without CREATE DATABASE -- create the db first (avoids ERROR 1049).
set "MYSQL_PWD=%PW%"
mysql -h%HOST% -P%PORT% -uroot -e "CREATE DATABASE IF NOT EXISTS `%DB%` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
if errorlevel 1 (
    echo [ERROR] CREATE DATABASE failed. Check host/port/credentials.
    exit /b 1
)
mysql -h%HOST% -P%PORT% -uroot --default-character-set=utf8mb4 %DB% < crawler-service\sql\mysql_schema.sql
if errorlevel 1 (
    echo [ERROR] schema import failed.
    exit /b 1
)
echo Done. %DB% schema ready (nothing was dropped).
