@echo off
rem ============================================================
rem  One-shot self-check: crawler tests + api layering + tsc.
rem  Usage: scripts\check.bat     (equivalent to scripts/check.sh)
rem ============================================================
chcp 65001 >nul
setlocal
set "ROOT=%~dp0.."
set "PY=%ROOT%\crawler-service\.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] venv python not found: %PY%
    exit /b 1
)

echo -^> [1/3] crawler-service unit tests
pushd "%ROOT%\crawler-service"
"%PY%" -m unittest discover -s tests
if errorlevel 1 goto fail
popd

echo -^> [2/3] api-service layering guard
pushd "%ROOT%\api-service"
"%PY%" -m unittest discover -s tests
if errorlevel 1 goto fail
popd

echo -^> [3/3] frontend type check ^(tsc --noEmit^)
pushd "%ROOT%\comic-web"
call npx tsc --noEmit
if errorlevel 1 goto fail
popd

echo OK  all checks passed
exit /b 0

:fail
echo [FAILED] check did not pass
exit /b 1
