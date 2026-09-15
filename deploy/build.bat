@echo off
setlocal enabledelayedexpansion
rem ============================================================
rem  构建部署产物与镜像（分层：每个模块一个文件夹 + 一个 Dockerfile）
rem
rem  步骤 1  生成各模块产物到 deploy\<模块>\dist\
rem             crawler-service\  --wheel-->  deploy\crawler\dist\comic_crawler-<版本>.whl
rem             api-service\      --wheel-->  deploy\api\dist\comic_api-<版本>.whl
rem             sql\mysql_schema.sql --复制--> deploy\mysql\sql\
rem             comic-web\dist\   --复制---->  deploy\web\dist\
rem  步骤 2  按依赖顺序构建镜像
rem             mysql -> web -> crawler -> api -> nginx
rem
rem  其中 mysql 镜像当前**不被编排使用**（项目复用现有的 MySQL 实例，见 docker-compose.yml
rem  末尾「数据库」），构建它只为"需要一个独立干净的库"时备用。
rem          （顺序不能乱：api 的 Dockerfile 会 FROM comic-crawler:1.0.0 并 COPY --from=comic-web:1.0.0）
rem
rem  用法：deploy\build.bat            （Linux/macOS: ./deploy/build.sh）
rem        构建完启动：docker compose -f deploy\docker-compose.yml up -d
rem
rem  可选：依赖从 PyPI 下载，国内或网速慢的机器先设 PIP_INDEX 换源（crawler / api 两层用它装依赖）：
rem        set PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
rem        deploy\build.bat
rem
rem  依赖：构建 wheel 需要一个带 pip 的 Python 3.10+（默认用 PATH 里的 python，
rem        可用 set PYTHON=D:\path\to\python.exe 覆盖）。
rem ============================================================
for %%i in ("%~dp0..") do set "ROOT=%%~fi"
set "DEPLOY=%~dp0"

rem ---------- 选定 Python 解释器 ----------
if defined PYTHON (set "PY=%PYTHON%") else (set "PY=python")
"%PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo !! %PY% 里没有可用的 pip -- 可用 set PYTHON=路径 指定解释器
  exit /b 1
)

rem ---------- 步骤 1：产物 ----------
echo -^> [1/2] 生成模块产物到 deploy\<模块>\dist\

rem 构建 wheel。必须在模块目录里用 `.` 作为源：
rem   传裸名字（如 api-service）会被 pip 当成**包名**去 PyPI 找，而 PyPI 上真有个同名的第三方包，
rem   会静默下回来一个假产物。输出目录用相对路径（..\deploy\...）避免路径形态问题。
echo    crawler-service\  --wheel--^>  deploy\crawler\dist\
if not exist "%DEPLOY%crawler\dist" mkdir "%DEPLOY%crawler\dist"
pushd "%ROOT%\crawler-service"
"%PY%" -m pip wheel --no-deps --wheel-dir "..\deploy\crawler\dist" . >nul || (popd & exit /b 1)
popd

echo    api-service\      --wheel--^>  deploy\api\dist\
if not exist "%DEPLOY%api\dist" mkdir "%DEPLOY%api\dist"
pushd "%ROOT%\api-service"
"%PY%" -m pip wheel --no-deps --wheel-dir "..\deploy\api\dist" . >nul || (popd & exit /b 1)
popd

echo    sql\mysql_schema.sql  --复制--^>  deploy\mysql\sql\
if not exist "%DEPLOY%mysql\sql" mkdir "%DEPLOY%mysql\sql"
copy /y "%ROOT%\crawler-service\sql\mysql_schema.sql" "%DEPLOY%mysql\sql\mysql_schema.sql" >nul

echo    comic-web\dist  --复制--^>  deploy\web\dist\
if not exist "%ROOT%\comic-web\dist" (
  echo    !! comic-web\dist 不存在 -- 先构建前端：cd comic-web ^&^& npm run build
  exit /b 1
)
robocopy "%ROOT%\comic-web\dist" "%DEPLOY%web\dist" /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP >nul

echo.
echo -^> 产物检查
for %%m in (crawler api) do (
  set "N=0"
  for %%f in ("%DEPLOY%%%m\dist\*.whl") do set /a N+=1
  if "!N!"=="0" (
    echo    !! deploy\%%m\dist\ 下没有 whl -- 构建失败了？
  ) else if !N! GTR 1 (
    echo    !! deploy\%%m\dist\ 下有 !N! 个 whl（版本变更残留），镜像只装最新的 ^(ls -t^)；建议手动删旧的
  ) else (
    echo    deploy\%%m\dist\ 就绪
  )
)

echo.
echo -^> 遗留检查（产物目录有、源目录已没有的文件）
set "LEFT="
call :leftovers "%DEPLOY%web\dist" "%ROOT%\comic-web\dist"
if not defined LEFT echo    无遗留文件

rem ---------- 步骤 2：按序构建镜像 ----------
echo.
echo -^> [2/2] 构建镜像（顺序：mysql -^> web -^> crawler -^> api -^> nginx）
if defined PIP_INDEX echo    [PyPI 源] %PIP_INDEX%
call :buildimg mysql   comic-mysql:1.0.0   || exit /b 1
call :buildimg web     comic-web:1.0.0     || exit /b 1
call :buildimg crawler comic-crawler:1.0.0 || exit /b 1
call :buildimg api     comic-api:1.0.0     || exit /b 1
call :buildimg nginx   comic-nginx:1.0.0   || exit /b 1

echo.
echo OK  镜像已就绪
docker images --format "  {{.Repository}}:{{.Tag}}  {{.Size}}" | findstr /b "  comic-"
echo.
echo 启动：docker compose -f deploy\docker-compose.yml up -d
exit /b 0

rem ---- 构建单个镜像（PIP_INDEX 可选）----
:buildimg
if defined PIP_INDEX (
  docker build --build-arg "PIP_INDEX=%PIP_INDEX%" -t %2 "%DEPLOY%%1"
) else (
  docker build -t %2 "%DEPLOY%%1"
)
exit /b %errorlevel%

rem ---- 遗留检查（只报告，不删除）----
:leftovers
if not exist "%~1" exit /b 0
if not exist "%~2" exit /b 0
for /r "%~1" %%f in (*) do (
  set "REL=%%f"
  set "REL=!REL:%~1\=!"
  if not exist "%~2\!REL!" (
    if not defined LEFT echo !! 以下文件在产物目录里存在、但源目录已没有（纯覆盖不会清除）:
    set "LEFT=1"
    echo      %~nx1\!REL!
  )
)
exit /b 0
