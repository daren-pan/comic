@echo off
setlocal enabledelayedexpansion
rem ============================================================
rem  构建部署产物与镜像（分层：每个模块一个文件夹 + 一个 Dockerfile）
rem
rem  步骤 1  生成各模块产物到 deploy\<模块>\dist\
rem             comic-core\       --wheel-->  deploy\core\dist\comic_core-<版本>.whl
rem             crawler-service\  --wheel-->  deploy\crawler\dist\comic_crawler-<版本>.whl
rem             api-service\      --wheel-->  deploy\api\dist\comic_api-<版本>.whl
rem             comic-scheduler\  --wheel-->  deploy\scheduler\dist\comic_scheduler-<版本>.whl
rem             comic-core\sql\mysql_schema.sql --复制--> deploy\mysql\sql\
rem             comic-front\dist\build\h5 --复制--> deploy\front\dist\ （前端产物）
rem  步骤 2  按依赖顺序构建镜像
rem             mysql -> crawler -> api -> scheduler -> front
rem
rem  其中 mysql 镜像是本项目**独占**的数据库（MySQL 8.0，见 docker-compose.yml）——数据卷首次
rem  启动时会自动执行烘在镜像里的建库脚本，10 张表直接建好。
rem          （api 构建时要读采集层的 wheel 产物，scheduler 要读采集层 + 公共内核的 —— 所以
rem           两者的**产物**必须先出（步骤 1 已保证）。模块之间**没有镜像依赖**：都只是在
rem           pyproject.toml 的 dependencies 里声明上游，构建时由 pip 解析安装。）
rem
rem  ⚠️ comic-core 是**纯库、没有镜像** —— 它是 deploy\ 下唯一一个「只出 wheel、不建镜像」的模块，
rem     所以 deploy\core\ 里只有 dist\（和一个说明用的 README.md），没有 Dockerfile。
rem     它的 wheel 以 BuildKit **命名构建上下文 core** 喂给 crawler / api / scheduler 三层
rem     （见下面 :buildimg 调用处的 "core=%DEPLOY%core"）——
rem     少了它，pip 装 comic-crawler / comic-api / comic-scheduler 时会去 PyPI 找 comic-core 并直接报错。
rem     wheel 的拓扑顺序固定为 comic-core -> crawler -> api / scheduler（后三个的 METADATA 里都声明了上游）。
rem
rem  前端镜像（comic-front）**自带 nginx**：静态产物 + 反代在同一个容器里，所以没有
rem  "反代活着但产物不在"的悬空状态。⚠️ comic-web 的镜像部署已于 2026-10-10 下线
rem  （旧前端保留在仓库里仅作参考实现），deploy\web\ 目录已删除。
rem
rem  用法：deploy\build.bat                （构建全部：mysql + 各 wheel + comic-front 镜像）
rem        deploy\build.bat -h             （Linux/macOS: ./deploy/build.sh）
rem        构建完启动：docker compose -f deploy\docker-compose.yml up -d
rem
rem  前端来源：默认 comic-front\dist\build\h5（可用 set FRONT_SRC=... 覆盖）。
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

rem ---------- 参数 ----------
rem --front 兼容保留（前端只有一个，加不加都一样）；--web 已下线，明确报错
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--front" (
  shift
  goto parse
)
if /i "%~1"=="--web" (
  echo !! comic-web 的镜像部署已下线（2026-10-10）：现在唯一前端是 comic-front
  exit /b 1
)
if /i "%~1"=="-h"      goto usage
if /i "%~1"=="--help"  goto usage
echo !! 未知参数：%~1（-h 看用法）
exit /b 1
:parsed

rem 前端产物来源（见文件头）
if not defined FRONT_SRC set "FRONT_SRC=%ROOT%\comic-front\dist\build\h5"

rem ---------- 选定 Python 解释器 ----------
if defined PYTHON (set "PY=%PYTHON%") else (set "PY=python")
"%PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo !! %PY% 里没有可用的 pip -- 可用 set PYTHON=路径 指定解释器
  exit /b 1
)

rem ---------- 步骤 1：产物 ----------
echo.
echo -^> [1/2] 生成模块产物到 deploy\<模块>\dist\

rem 构建 wheel。必须在模块目录里用 `.` 作为源：
rem   传裸名字（如 api-service）会被 pip 当成**包名**去 PyPI 找，而 PyPI 上真有个同名的第三方包，
rem   会静默下回来一个假产物。输出目录用相对路径（..\deploy\...）避免路径形态问题。
rem 拓扑顺序：comic-core 在最前 -- 后两个 wheel 的 METADATA 里声明了它
echo    comic-core\       --wheel--^>  deploy\core\dist\
if exist "%DEPLOY%core\dist" rd /s /q "%DEPLOY%core\dist"
if not exist "%DEPLOY%core\dist" mkdir "%DEPLOY%core\dist"
pushd "%ROOT%\comic-core"
"%PY%" -m pip wheel --no-deps --wheel-dir "..\deploy\core\dist" . >nul || (popd & exit /b 1)
popd

echo    crawler-service\  --wheel--^>  deploy\crawler\dist\
if exist "%DEPLOY%crawler\dist" rd /s /q "%DEPLOY%crawler\dist"
if not exist "%DEPLOY%crawler\dist" mkdir "%DEPLOY%crawler\dist"
pushd "%ROOT%\crawler-service"
"%PY%" -m pip wheel --no-deps --wheel-dir "..\deploy\crawler\dist" . >nul || (popd & exit /b 1)
popd

echo    api-service\      --wheel--^>  deploy\api\dist\
if exist "%DEPLOY%api\dist" rd /s /q "%DEPLOY%api\dist"
if not exist "%DEPLOY%api\dist" mkdir "%DEPLOY%api\dist"
pushd "%ROOT%\api-service"
"%PY%" -m pip wheel --no-deps --wheel-dir "..\deploy\api\dist" . >nul || (popd & exit /b 1)
popd

echo    comic-scheduler\  --wheel--^>  deploy\scheduler\dist\
if exist "%DEPLOY%scheduler\dist" rd /s /q "%DEPLOY%scheduler\dist"
if not exist "%DEPLOY%scheduler\dist" mkdir "%DEPLOY%scheduler\dist"
pushd "%ROOT%\comic-scheduler"
"%PY%" -m pip wheel --no-deps --wheel-dir "..\deploy\scheduler\dist" . >nul || (popd & exit /b 1)
popd

echo    comic-core\sql\mysql_schema.sql  --复制--^>  deploy\mysql\sql\
if not exist "%DEPLOY%mysql\sql" mkdir "%DEPLOY%mysql\sql"
copy /y "%ROOT%\comic-core\sql\mysql_schema.sql" "%DEPLOY%mysql\sql\mysql_schema.sql" >nul

echo    comic-front\dist\build\h5  --复制--^>  deploy\front\dist\
if not exist "%FRONT_SRC%" (
  echo    !! 前端产物目录不存在：%FRONT_SRC%
  echo       先构建前端：cd comic-front ^&^& npm run build:h5
  exit /b 1
)
if exist "%DEPLOY%front\dist" rd /s /q "%DEPLOY%front\dist"
robocopy "%FRONT_SRC%" "%DEPLOY%front\dist" /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP >nul

echo.
echo -^> 产物检查
for %%m in (core crawler api scheduler) do (
  set "N=0"
  for %%f in ("%DEPLOY%%%m\dist\*.whl") do set /a N+=1
  if "!N!"=="0" (
    echo    !! deploy\%%m\dist\ 下没有 whl -- 构建失败了？
  ) else if !N! GTR 1 (
    echo    !! deploy\%%m\dist\ 下有 !N! 个 whl（版本变更残留），镜像只装最新的；建议手动删旧的
  ) else (
    echo    deploy\%%m\dist\ 就绪
  )
)

echo.
echo -^> 遗留检查（前端产物目录有、源目录已没有的文件）
set "LEFT="
call :leftovers "%DEPLOY%front\dist" "%FRONT_SRC%"
if not defined LEFT echo    无遗留文件

rem ---------- 步骤 2：按序构建镜像 ----------
echo.
echo -^> [2/2] 构建镜像（顺序：mysql -^> crawler -^> api -^> scheduler -^> front）
if defined PIP_INDEX echo    [PyPI 源] %PIP_INDEX%
call :buildimg mysql   comic-mysql:1.0.0   || exit /b 1
call :buildimg crawler comic-crawler:1.0.0 "core=%DEPLOY%core" || exit /b 1
rem api 要读**两个**上游 wheel 产物 -> 挂两个命名上下文：
rem   core    = 公共内核（deploy\core\dist\），Dockerfile 里 COPY --from=core dist\
rem   crawler = 采集层（deploy\crawler\dist\），Dockerfile 里 COPY --from=crawler dist\
rem 都不是镜像依赖，只要两个 wheel 已生成即可。
call :buildimg api     comic-api:1.0.0     "crawler=%DEPLOY%crawler" "core=%DEPLOY%core" || exit /b 1
rem scheduler 同样要读两个上游 wheel（采集层里有 cron 引擎与一轮执行，内核里有路径与存储），
rem 所以挂同样的两个命名上下文。它**不是** api 的衍生镜像 —— 两者平级，各自独立启停。
call :buildimg scheduler comic-scheduler:1.0.0 "crawler=%DEPLOY%crawler" "core=%DEPLOY%core" || exit /b 1
call :buildimg front   comic-front:1.0.0   || exit /b 1

echo.
echo OK  镜像已就绪
docker images --format "  {{.Repository}}:{{.Tag}}  {{.Size}}" | findstr /b "  comic-"
echo.
echo 启动：docker compose -f deploy\docker-compose.yml up -d
exit /b 0

:usage
echo 用法：deploy\build.bat
echo        构建全部（mysql + 各 wheel + comic-front 镜像）
echo        --front 兼容保留（前端只有一个，加不加都一样）
echo        详细说明见本文件头部注释
exit /b 0

rem ---- 构建单个镜像（PIP_INDEX 可选）----
rem %1=模块目录  %2=镜像名  %3..%9=额外的 --build-context 值（可选，每个形如 name=dir，可给多个）
rem 注意是**可变个数**：api 要同时挂 core 与 crawler 两个上下文，
rem 早期版本只认 %3 一个，加第二个会被静默丢掉 -> pip 找不到 comic-core 而构建失败。
rem ⚠️ 必须先把 %1/%2 存进变量再 shift，否则 shift 之后它们就变成上下文了。
:buildimg
set "BIMG_DIR=%DEPLOY%%~1"
set "BIMG_TAG=%~2"
set "EXTRA="
shift
shift
:buildimg_args
if "%~1"=="" goto :buildimg_run
set "EXTRA=%EXTRA% --build-context %~1"
shift
goto :buildimg_args
:buildimg_run
if defined PIP_INDEX (
  docker build --build-arg "PIP_INDEX=%PIP_INDEX%" %EXTRA% -t %BIMG_TAG% "%BIMG_DIR%"
) else (
  docker build %EXTRA% -t %BIMG_TAG% "%BIMG_DIR%"
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
