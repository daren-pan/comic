@echo off
setlocal enabledelayedexpansion
rem ============================================================
rem  Package a deployable bundle (generated on demand; NOT committed).
rem  Usage:  package.bat [output-dir]     (default: build\deploy)
rem
rem  Refresh policy: 纯覆盖，**本脚本不做任何删除**（与 scripts/package.sh 一致）。
rem  代价："上一版有、这一版没有"的文件会留在输出目录里 —— 末尾做遗留检查并列出（只报告）。
rem  See scripts/package.sh header for the full output layout.
rem ============================================================
for %%i in ("%~dp0..") do set "ROOT=%%~fi"
set "OUT=%~1"
if "%OUT%"=="" set "OUT=%ROOT%\build\deploy"

mkdir "%OUT%\src" 2>nul
mkdir "%OUT%\sql" 2>nul

echo -^> copy HTTP layer (api-service)
copy /y "%ROOT%\api-service\main.py"         "%OUT%\" >nul
copy /y "%ROOT%\api-service\schemas.py"      "%OUT%\" >nul
copy /y "%ROOT%\api-service\serializers.py"  "%OUT%\" >nul
rem robocopy 原生排除缓存目录/字节码 —— 复制阶段就排除，无需事后扫描删除
robocopy "%ROOT%\api-service" "%OUT%" core routers services /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP >nul

echo -^> copy crawler package -^> src\comic_crawler
robocopy "%ROOT%\crawler-service\src" "%OUT%\src" comic_crawler /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP >nul

echo -^> merge requirements (api + crawler, dedup)
type "%ROOT%\api-service\requirements.txt" "%ROOT%\crawler-service\requirements.txt" | sort /unique > "%OUT%\requirements.txt"

echo -^> copy schema
copy /y "%ROOT%\crawler-service\sql\mysql_schema.sql" "%OUT%\sql\" >nul

if exist "%ROOT%\comic-web\dist" (
  echo -^> copy frontend dist\
  robocopy "%ROOT%\comic-web\dist" "%OUT%\dist" /E /NFL /NDL /NJH /NJS /NP >nul
) else (
  echo !! comic-web\dist not found -- run: cd comic-web ^&^& npm install ^&^& npm run build
)

echo.
echo -^> check leftovers
set "LEFT="
call :leftovers "%OUT%\core"              "%ROOT%\api-service\core"
call :leftovers "%OUT%\routers"           "%ROOT%\api-service\routers"
call :leftovers "%OUT%\services"          "%ROOT%\api-service\services"
call :leftovers "%OUT%\src\comic_crawler" "%ROOT%\crawler-service\src\comic_crawler"
call :leftovers "%OUT%\dist"              "%ROOT%\comic-web\dist"
call :leftovers "%OUT%\sql"               "%ROOT%\crawler-service\sql"
if not defined LEFT echo     无遗留文件

echo.
echo OK  bundle ready: %OUT%
echo     cd %OUT% ^&^& python -m pip install -r requirements.txt
echo     python -m uvicorn main:app --host 0.0.0.0 --port 8000
exit /b 0

rem ---- 遗留检查（只报告，不删除）----
rem 纯覆盖不会清掉"上一版有、这一版没有"的文件；重构改名/挪位置后旧文件会赖在输出目录里。
:leftovers
if not exist "%~1" exit /b 0
if not exist "%~2" exit /b 0
for /r "%~1" %%f in (*) do (
  set "REL=%%f"
  set "REL=!REL:%~1\=!"
  if not exist "%~2\!REL!" (
    if not defined LEFT echo !! 以下文件在输出目录里存在、但源目录已没有（纯覆盖不会清除）:
    set "LEFT=1"
    echo      %~nx1\!REL!
  )
)
exit /b 0
