@echo off
rem ============================================================
rem  One-shot self-check: crawler tests + api layering + tsc.
rem  Usage: scripts\check.bat     (equivalent to scripts/check.sh)
rem
rem  python 环境是**两层、都在项目内**（均进 .gitignore，不碰系统 python）：
rem    .python\               基础解释器（官方 CPython 3.13，缺了自动下载解压）
rem    crawler-service\.venv 运行环境（由 .python 创建并装依赖）
rem  环境准备统一交给 scripts/dev.sh bootstrap（唯一实现，避免两份逻辑走偏），
rem  因此本机需要 Git Bash；没有 bash 时给出提示。
rem ============================================================
chcp 65001 >nul
setlocal
set "ROOT=%~dp0.."
set "PY=%ROOT%\crawler-service\.venv\Scripts\python.exe"
set "IMPORTS=fastapi,uvicorn,httpx,parsel,pymysql,cryptography,zhconv,bcrypt,jwt,python_multipart"

if not exist "%PY%" goto need_env
"%PY%" -c "import %IMPORTS%" >nul 2>&1
if errorlevel 1 goto need_env
goto run

:need_env
echo -^> [0/3] 准备 python 环境 ^(.python + crawler-service\.venv^)
where bash >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 需要 Git Bash 来自动准备 python 环境
    echo         或用 Git Bash 手动执行: bash scripts/dev.sh bootstrap
    exit /b 1
)
bash "%ROOT%\scripts\dev.sh" bootstrap
if errorlevel 1 (
    echo [ERROR] python 环境准备失败
    exit /b 1
)
if not exist "%PY%" (
    echo [ERROR] venv python not found after bootstrap: %PY%
    exit /b 1
)

:run
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
