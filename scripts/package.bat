@echo off
setlocal enabledelayedexpansion
rem ============================================================
rem  Package a deployable bundle (generated on demand; NOT committed).
rem  Usage:  package.bat [output-dir]     (default: build\deploy)
rem  See scripts/package.sh header for the full output layout.
rem ============================================================
for %%i in ("%~dp0..") do set "ROOT=%%~fi"
set "OUT=%~1"
if "%OUT%"=="" set "OUT=%ROOT%\build\deploy"

if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%\src" 2>nul

echo -^> copy HTTP layer (api-service)
copy /y "%ROOT%\api-service\main.py"         "%OUT%\" >nul
copy /y "%ROOT%\api-service\schemas.py"      "%OUT%\" >nul
copy /y "%ROOT%\api-service\serializers.py"  "%OUT%\" >nul
xcopy /e /i /q /y "%ROOT%\api-service\core"     "%OUT%\core"     >nul
xcopy /e /i /q /y "%ROOT%\api-service\routers"  "%OUT%\routers"  >nul
xcopy /e /i /q /y "%ROOT%\api-service\services" "%OUT%\services" >nul

echo -^> copy crawler package -^> src\comic_crawler
xcopy /e /i /q /y "%ROOT%\crawler-service\src\comic_crawler" "%OUT%\src\comic_crawler" >nul

echo -^> merge requirements (api + crawler, dedup)
type "%ROOT%\api-service\requirements.txt" "%ROOT%\crawler-service\requirements.txt" | sort /unique > "%OUT%\requirements.txt"

echo -^> copy schema
mkdir "%OUT%\sql" 2>nul
copy /y "%ROOT%\crawler-service\sql\mysql_schema.sql" "%OUT%\sql\" >nul

if exist "%ROOT%\comic-web\dist" (
  echo -^> copy frontend dist\
  xcopy /e /i /q /y "%ROOT%\comic-web\dist" "%OUT%\dist" >nul
) else (
  echo !! comic-web\dist not found -- run: cd comic-web ^&^& npm install ^&^& npm run build
)

for /d /r "%OUT%" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"

echo.
echo OK  bundle ready: %OUT%
echo     cd %OUT% ^&^& python -m pip install -r requirements.txt
echo     python -m uvicorn main:app --host 0.0.0.0 --port 8000
