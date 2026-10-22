---
name: 启动开发环境
description: >-
  本地开发环境的一键状态检查 / 启动 / 停止。当用户说"启动前后端/起一下服务/跑起来/
  把服务拉起来/重启前端或后端/服务起了没/端口被占了"时触发。
  所有命令都封在 scripts/dev.sh —— 不要探索代码找命令，也不要自己拼启动命令。
when_to_use: >-
  命中任一即触发：
  (a) "启动前后端""起服务""跑起来""拉起来"；
  (b) "重启后端/前端""停掉服务""端口被占了"；
  (c) 问"服务起了没""现在跑的是什么""怎么启动这个项目"。
version: 1.0.0
---

# 启动开发环境

## 铁律（先看这三条）

1. **命令只认 `scripts/dev.sh`** —— 不要自己拼 npm / node / uvicorn 命令。脚本内部已用
   标准 `npm run dev` / `npm run dev:h5`（`npm` 不可用时自动回退 `node` 直调 bin）。
2. **不要探索代码找命令** —— 命令只有这一处真源：`scripts/dev.sh`。
3. **启动服务用 `run_in_background: true`** —— 前台会阻塞；不要用 `nohup` / `&` 模拟后台。

## 标准动作（最多 3 步）

```bash
bash scripts/dev.sh status      # ① 先看现状（MySQL / 端口 / 健康）
bash scripts/dev.sh up api      # ② 只对"未启动"的目标执行；Bash 参数 run_in_background=true
bash scripts/dev.sh status      # ③ 5~10 秒后复查，确认 LISTENING + health 200
```

| 目标 | 端口 | 启动命令（agent 加 `run_in_background=true`） |
|---|---|---|
| `api` | 8000 | `bash scripts/dev.sh up api` |
| `web`（comic-web） | 5173 | `bash scripts/dev.sh up web` |
| `front`（comic-front） | 5174 | `bash scripts/dev.sh up front` |
| 停止 | — | `bash scripts/dev.sh down api`（或 `web` / `front` / `all`） |
| 装/补 python 环境 | — | `bash scripts/dev.sh bootstrap`（幂等，装齐三份 requirements） |

## 成功判据（必须确认，不能假设）

- `api`：`8000` LISTENING **且** `GET http://127.0.0.1:8000/api/health` 返回 200；
- `web` / `front`：`5173` / `5174` LISTENING（日志出现 `ready in`）；
- 三个任一起不来 → 按下面处置，**不要自行改端口或改代码**。

## 失败处置（照表执行）

| 现象 | 处置 |
|---|---|
| 端口被占 / 要重启 | `bash scripts/dev.sh down <target>` → 再 `up` |
| MySQL 未就绪（脚本已打印状态） | 照脚本给的命令做：容器**没建过** → `docker compose -f deploy/docker-compose.yml up -d comic-mysql`；只是**停了** → `docker start comic-mysql`；`no-docker` → 先装 Docker；`docker-down` → 启动 Docker 服务（**不要指定 Docker Desktop**，Linux 上是 `systemctl start docker`） |
| `node_modules` 缺失 / 不完整 | 引导用户 `cd comic-web`（或 `comic-front`）`&& npm ci`；**不要**自己静默装 |
| uvicorn 瞬间退出 | `tail -n 40 logs/api.log`，把报错贴给用户 |
| `up api` 下载/创建 python 失败 | 看日志里的 `[env]` 行；下载走 nuget（`api.nuget.org`），依赖走 `$PIP_INDEX`（默认阿里云）；**不要**改成用系统 python 硬跑 |
| vite 起不来 | `tail -n 40 logs/vite.log`（web）或 `logs/vite-front.log`（front） |

## 环境事实（不用再查）

- Python：项目内**两层**，都进 `.gitignore`、都不碰系统 python：
  `.python/`（基础解释器，官方 CPython 3.13，缺了自动下载约 15MB）+ `crawler-service/.venv`
  （运行环境，`pyvenv.cfg` 的 `home` 指向 `.python`，装三份 requirements）。
  `up api` 会自动补齐；底座与 `.python` 不一致会自动重建。也可 `bash scripts/dev.sh bootstrap` 手动触发（幂等）。
  版本锁 3.13（对齐线上镜像 `python:3.13-slim`），**不要**降级、也不要把包装进系统 python。
- 起不动先看 `bash scripts/dev.sh status`：会打印 mysql 状态、前端依赖（`deps` 行）、
  `base`（`.python` 版本）、`python`（venv 版本）与各端口，缺什么它会给出对应命令。
- 前端 bin：`comic-web/node_modules/vite/bin/vite.js`、`comic-front/node_modules/@dcloudio/vite-plugin-uni/bin/uni.js`；
- 日志：`logs/api.log` / `logs/vite.log` / `logs/vite-front.log`；
- 停止按端口找 PID（`taskkill //PID`），**禁止 `taskkill /IM python.exe`**（会误伤同机其他服务）。
