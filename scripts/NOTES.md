# scripts · 知识库（AI 维护）

> 本文件是 scripts（启动 / 自检 / 打包脚本）的**踩坑与知识沉淀**，由 AI 协作时维护 ——
> **每次踩坑 / 实测 / 复盘写到这里**，不再写进 `README.md`。

## 条目模板（新增知识时按此写）

```markdown
#### 标题（一句话说清是什么）

- **日期**：YYYY-MM-DD（多个用 ` / ` 分隔）
- **背景 / 现象**：发生了什么（决策类写"当时的背景"）
- **根因**：为什么会这样（决策类写"为什么这么定"）
- **结论**：怎么解决 / 最终决定是什么
- **实测**（可选）：关键数字 / 验证方式
- **位置**（可选）：涉及的文件 / 页面
```

---

## 一、门禁脚本（`check.sh`）

### 1.1 ⚠️ 缺 `PYTHONPATH` 会让 crawler 测试"看起来全挂"（2026-10-13 修复）

- **背景 / 现象**：脚本跑 crawler 测试时 21 个 `unittest.loader._FailedTest` ——
  看起来像"测试挂了"，其实是环境没配好。
- **根因**：`comic_core` / `comic_crawler` 两个本地包**并未安装进 venv**，只靠源码路径导入；
  脚本没设 `PYTHONPATH` → 测试模块在 import 阶段就失败。
- **结论**：第 1 步固定带 `PYTHONPATH="src;../comic-core/src"`。

### 1.2 门禁的演进（2026-10-13）

- **背景 / 现象**：原第 3 步在检查**已冻结的** comic-web 的 `tsc`（无实际意义）。
- **结论**：改为 —— ① crawler 单测 ② api 单测 ③ comic-front ESLint ④ comic-front vitest
  ⑤ comic-front `tsc --noEmit`（**纳入当天就抓到 `stores/message.ts` 一个真实缺字段错误**）。
  第 5 步只查 `.ts`（`tsc` 不认 `.vue`；模板类型要 vue-tsc，暂未纳入）。

## 二、开发启动脚本（`dev.sh`）

### 2.1 前端命令：标准 `npm run dev` 即可（2026-10-22 更正）

- **背景**：早前 agent 收到"启动前端"时跑 `npm run dev` 报
  `PROGRAM BLOCKED BY SECURITY POLICY ... wsl.exe`，于是 NOTES 记成"npm 被安全策略拦"，
  `dev.sh` 改用 `node node_modules/vite/bin/vite.js` 直调。
- **2026-10-22 复查更正**：**不是 WorkBuddy 沙箱拦的，也不是 npm 本身的问题** ——
  当时裸名 `npm` 解析到了 WSL 侧的 shim（真正被 Windows 应用控制策略拦的是 `wsl.exe`）。
  现在 PATH 里 `npm` 命中 WorkBuddy 受管 Node（`~/.workbuddy/binaries/node/versions/22.22.2-6/npm`），
  实测 `npm run dev`（1.2s ready）、`npm run dev:h5`、`npm run typecheck` 全部正常。
- **沙箱侧**：`~/.workbuddy/settings.json` 的 `sandbox.orderedRules.command` 当前 **0 条规则**
  （即没有命令白名单限制）；`safe-bin/` 只放了 `rm` / `rmdir` / `unlink`（删除守卫），与 npm 无关。
- **结论**：`dev.sh` 已改回**标准 `npm run dev` / `npm run dev:h5`**，并保留
  `npm --version` 探测 + `node` 直调兜底（换机器 / PATH 变化时自动降级）。
  **不要再写"本机禁止 npm"** —— 这条已证伪。

### 2.2 ⚠️ Git Bash 会把 `/api/health` 转成 Windows 路径（2026-10-22 实测）

- **背景 / 现象**：`dev.sh status` 用 `node -e` 探活，传 `/api/health` 一直 404；
  `logs/api.log` 里能看到 `GET D%3A/software/workbuddy/resources/vendor/PortableGit/api/health`。
- **根因**：MSYS（Git Bash）对以 `/` 开头的参数做路径转换，node 收到的是 Windows 路径。
- **结论**：路径参数不传前导 `/`，在 JS 里 `"/" + process.argv[2]` 拼（或用 `MSYS_NO_PATHCONV=1`）。
- **位置**：`scripts/dev.sh` 的 `http_code()`。

### 2.3 `up` 为什么是前台进程

- **背景**：工具调用结束后子进程树会被回收，`nohup` / `&` 起的长驻服务活不过一次工具调用。
- **结论**：`up` 前台 exec；agent 用 `run_in_background: true` 托管，人在终端直接跑（Ctrl+C 停）。
- **实测**：`up front` → 5 秒后 5174 LISTENING、日志 `ready in 3817ms`；
  `down front` → 端口释放（后台任务会显示为 failed，属正常：进程是被 taskkill 的）。

### 2.4 python 环境：项目内两层 `.python/` + `crawler-service/.venv`（2026-10-22 定稿）

- **背景**：`dev.sh` / `check.sh` 硬编码 `crawler-service/.venv`，而 `.venv/` 在 `.gitignore` ——
  新克隆 / 新机器一上来就报"找不到 python"；而本机现成的 `.venv` 又是用 WorkBuddy 托管解释器建的
  （`pyvenv.cfg` 的 `home` 指向 `~/.workbuddy/.../3.13.12.old.36492`），托管目录一清理就全废。
- **走过的弯路（均已否决）**：
  1. 挪到 `~/.workbuddy/.../envs/comic` + 多级解析（`$COMIC_PY` / `$VIRTUAL_ENV` / 系统 python）——
     路径依赖"装了 WorkBuddy 才有"，别人机器不可复现，且各机器版本会漂移。
  2. 只要求机器上有 Python 3.13、没有就报错 —— 达不到"新机器一条命令起"。
- **定稿**：python 拆成**项目内两层**，都用 `.gitignore` 排除，**完全不碰系统 python**：
  - `.python/` —— 基础解释器：官方 CPython（`dev.sh` 里 `PY_VERSION=3.13.17`），缺了自动下载解压。
    来源是 nuget 上的官方 `python` 包（`api.nuget.org`，约 15MB，跟随 302 到 `nuget.azure.cn` 国内镜像，
    实测 3.7s 下完）。包内是**完整安装**（`tools/python.exe` + `Lib/` + `DLLs/`，含 `venv` / `ensurepip` / 预装 pip），
    不是 embeddable 精简包 —— 后者没有 venv，用不了。
  - `crawler-service/.venv` —— 运行环境，由 `.python` 创建（`home` 指向 `.python`），装三份 requirements。
- **一致性**：`ensure_env` 比对 `pyvenv.cfg` 的 `home` 与 `.python`，不一致就**重建**（先 `mv` 成 `.venv.old-<ts>`，
  成功后再尽力清理）—— 这样旧机器上的 venv 会被自动收敛到统一底座。
- **平台边界**：nuget 包只有 Windows 构建。非 Windows 走系统 `python3.13` 作底座（`apt install python3.13-venv` /
  `brew install python@3.13`）；Linux 便携 CPython 只能从 GitHub releases 取，本机到该资源域不通，故不做。

#### 踩坑（都实测过）

- **`rm -rf` 会被删除守卫拦**：本环境对单次删除 >50 个文件要求批量确认，脚本里静默失败 → 曾出现
  "venv 没删掉、脚本却打印环境就绪"。**结论**：重建一律 `mv` 挪开，`rm` 只做尽力而为且不据此判断成败；
  建完必须核对 `home`，否则会假成功。
- **`mktemp -d` 在 Git Bash 下返回 `C:\...\Temp/tmp.xxx`**（带盘符的混合路径），删除守卫报
  `SAFE_DELETE_INVALID_PATH`，且临时目录散落在系统 temp 没人清。**结论**：临时目录固定用项目内 `$ROOT/.python.tmp`（已 gitignore）。
- **路径形态不统一会误判底座**：`/d/ruoyi/...`（MSYS）与 `d:/ruoyi/...`（Python 报告）是同一条路径。
  `norm_path()` 统一转小写、反斜杠转正斜杠、`/d/x` → `d:/x` 后再比。

- **实测**：`.python` = 3.13.17（41MB）；重建后 `sys.base_prefix` = `D:\RuoyiProject\comic\.python`，
  依赖全绿，`up api` health 200；`bootstrap` 重复执行只做校验、不重装。

### 2.5 Windows 上 venv 的 `python.exe` 是 trampoline，监听的是它的子进程

- **现象**：用 venv 的 `Scripts/python.exe` 起 uvicorn 后，`Get-Process -Id <监听PID>` 显示的是
  base 解释器路径（如 `versions/3.13.12/python.exe`），容易误判成"环境没生效 / 用了全局解释器"。
- **根因**：CPython 3.13 在 Windows 上 `Scripts/python.exe` 是启动垫片，再 `CreateProcess`
  拉起 base 解释器作为子进程（cmdline 仍显示 venv 路径）；真正监听端口的是子进程。
- **结论**：判断"到底用的哪个环境"看 `sys.prefix` / `site.getsitepackages()`，不看 `Get-Process.Path`。
  `down` 用 netstat 拿到的正是子进程，杀掉后垫片随之退出，按 PID 停仍然成立。
