"""TaskBridge 的配置与常量。

全部可用环境变量覆盖，默认值面向「本地 Windows 开发机直跑」；
上服务器时只改 `TB_REPO_ROOT` / `TB_OPENCODE_BIN` 即可，代码零改动。
"""

from __future__ import annotations

import os
from pathlib import Path

#: 仓库根目录（worktree、git 都在它下面操作）
REPO_ROOT = Path(os.environ.get("TB_REPO_ROOT", r"D:\software\RuoYi\comic")).resolve()

#: 运行时目录：worktree 副本 / 产物 / 日志。放 logs/ 下，天然被 gitignore
RUN_ROOT = Path(os.environ.get("TB_RUN_ROOT", REPO_ROOT / "logs" / "taskbridge"))

#: apply 之后是否自动把 main 推到远端。推不上去**不回滚本地提交**，
#: 只把错误回报到 QQ —— 本地提交已经在，人工补一次 push 即可。
GIT_PUSH_ENABLED = os.environ.get("TB_GIT_PUSH", "true").lower() in ("1", "true", "yes")

#: 推哪个远端、哪个分支（服务器上用 SSH remote，见 deploy/docs/NOTES.md §三）
GIT_REMOTE = os.environ.get("TB_GIT_REMOTE", "origin")
GIT_BRANCH = os.environ.get("TB_GIT_BRANCH", "main")

#: push 超时（秒）：网络差时别把队列卡死
GIT_PUSH_TIMEOUT = int(os.environ.get("TB_GIT_PUSH_TIMEOUT", "120"))

#: opencode 的数据/缓存目录。Windows 与 Linux 生成的库不通用，因此容器里必须指向独立路径
#: （compose 用命名卷挂到 /root/ocdata，避免与宿主那份互相踩）
XDG_ROOT = Path(os.environ.get("TB_XDG_ROOT", str(RUN_ROOT / "ocdata"))).expanduser()

#: 本地运行参数文件（KEY=VALUE，一行一个）：推送令牌这类敏感值放这儿，不进版本库
ENV_FILE = Path(os.environ.get("TB_ENV_FILE", RUN_ROOT / "env"))


def _load_env_file(path: Path) -> None:
    """把 `KEY=VALUE` 读进环境变量（已存在的环境变量优先，不覆盖）。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(ENV_FILE)

#: SQLite 任务库
DB_PATH = Path(os.environ.get("TB_DB_PATH", RUN_ROOT / "taskbridge.db"))

#: opencode 可执行文件；留空则从 PATH 查找
OPENCODE_BIN = os.environ.get("TB_OPENCODE_BIN", "opencode")

#: 使用的模型（provider/model 形式，provider 在 worktree 的 opencode.json 里定义）
#: 实测：deepseek-v4.1-flash 在 opencode 下改文件稳定；换 kimi-k2.7-code 备选
OPENCODE_MODEL = os.environ.get("TB_OPENCODE_MODEL", "opencode-zen/deepseek-v4.1-flash")

#: zen 网关的 key 来源：从 chat-service 的 rag/.env 读，避免另存一份密钥
KEY_ENV_FILE = Path(
    os.environ.get(
        "TB_KEY_ENV_FILE",
        REPO_ROOT / "chat-service" / "src" / "comic_chat" / "rag" / ".env",
    )
)
KEY_ENV_NAME = os.environ.get("TB_KEY_ENV_NAME", "COMIC_LLM_API_KEY")
ZEN_BASE_URL = os.environ.get("TB_ZEN_BASE_URL", "https://opencode.ai/zen/go/v1")

#: 单任务最长执行时间（秒）：超时杀进程并判失败
TASK_TIMEOUT = int(os.environ.get("TB_TASK_TIMEOUT", "600"))

#: 允许的最大改动文件数，超过视为「跑飞」
MAX_FILES = int(os.environ.get("TB_MAX_FILES", "20"))

#: 绝对禁止改动的路径前缀（相对于仓库根）
FORBIDDEN_PREFIXES = tuple(
    p.strip()
    for p in os.environ.get(
        "TB_FORBIDDEN_PREFIXES", ".git/,deploy/.env,deploy/qq-bot/,logs/"
    ).split(",")
    if p.strip()
)

#: 允许的动作枚举 —— 不接受自由文本命令
ALLOWED_ACTIONS = tuple(
    a.strip()
    for a in os.environ.get("TB_ALLOWED_ACTIONS", "code,doc,test").split(",")
    if a.strip()
)

#: 提交信息前缀（按 AGENTS.md 的 Conventional Commits 约定，由调用方给全文）
DEFAULT_COMMIT_SCOPE = os.environ.get("TB_DEFAULT_COMMIT_SCOPE", "tools")

#: 服务监听地址：必须是 0.0.0.0，否则同机 Docker 里的 Dify 访问不到
HOST = os.environ.get("TB_HOST", "0.0.0.0")
PORT = int(os.environ.get("TB_PORT", "8020"))

# ---- 主动推送（任务收尾时直接发 QQ，不再靠轮询）----
#: 通道：`qqofficial`（QQ 官方机器人 API，唯一在用的）| `onebot`（NapCat 遗留，2026-11-23 已停用）
PUSH_CHANNEL = os.environ.get("TB_PUSH_CHANNEL", "qqofficial").strip().lower()
#: 官方机器人的 appid / secret（开放平台拿；与 LangBot 里配的是同一套）
QQ_APPID = os.environ.get("TB_QQ_APPID", "").strip()
QQ_SECRET = os.environ.get("TB_QQ_SECRET", "").strip()
#: 推送目标 openid（官方适配器下的用户标识，**不是 QQ 号**），逗号分隔
QQ_OPENIDS = tuple(t.strip() for t in os.environ.get("TB_QQ_OPENIDS", "").split(",") if t.strip())
#: 官方 API：取 token 与发消息的地址（2026-11 文档）
QQ_TOKEN_URL = os.environ.get("TB_QQ_TOKEN_URL", "https://api.bot.qq.com/app/getAppAccessToken")
QQ_API_BASE = os.environ.get("TB_QQ_API_BASE", "https://api.bot.qq.com")
#: 单条文本上限：超长会被官方以 40054007 拒收，超出部分截断并提示发「进度」
PUSH_MAX_CHARS = int(os.environ.get("TB_PUSH_MAX_CHARS", "800"))

# ---- 遗留：NapCat 的 OneBot HTTP 通道（默认不用，留着只为回滚）----
PUSH_BASE = os.environ.get("TB_PUSH_BASE", "")
PUSH_TOKEN = os.environ.get("TB_PUSH_TOKEN", "")
PUSH_TARGETS = tuple(
    t.strip() for t in os.environ.get("TB_PUSH_TARGETS", "").split(",") if t.strip()
)
PUSH_ENABLED = os.environ.get("TB_PUSH_ENABLED", "true").lower() in ("1", "true", "yes")
PUSH_TIMEOUT = int(os.environ.get("TB_PUSH_TIMEOUT", "10"))
