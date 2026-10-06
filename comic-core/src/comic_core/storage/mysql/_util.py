"""存储层 MySQL 实现的共用工具：连接参数、热度算法、时间归一。

为什么单独成文件：热度公式与时间边界语义是 **MySQL 实现的通用约定**，
被 `comic_store` 与 `user_store` 共用；集中一处避免权重/时区语义散落漂移。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from pymysql.cursors import DictCursor

logger = logging.getLogger(__name__)

# ---------------- 连接参数 ----------------
# 取值顺序：**环境变量 → 仓库根的 `deploy/.env` → 默认值**。
# 容器部署由 compose 注入环境变量；本地开发没有环境变量，就兜底读 `deploy/.env`
# —— 与 compose 读的是**同一个文件**，所以"本地开发连的库"和"线上连的库"永远是同一个
# （曾出现两套库并存、排序规则/数据不一致的排查成本极高，故刻意收敛到一处配置源）。
_CONFIG_FILE = "deploy/.env"
#  .env 里的键名与 compose 保持一致：宿主端口复用 MYSQL_HOST_PORT、口令复用 MYSQL_ROOT_PASSWORD
_FILE_KEYS = {
    "COMIC_MYSQL_HOST": ("COMIC_MYSQL_HOST",),
    "COMIC_MYSQL_PORT": ("COMIC_MYSQL_PORT", "MYSQL_HOST_PORT"),
    "COMIC_MYSQL_USER": ("COMIC_MYSQL_USER",),
    "COMIC_MYSQL_PASSWORD": ("COMIC_MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD"),
    "COMIC_MYSQL_DB": ("COMIC_MYSQL_DB",),
}


def _read_config_file() -> dict[str, str]:
    """向上查找并解析仓库根的 `deploy/.env`（.gitignore 已忽略）。

    容器/发布包里没有这个文件 → 返回空字典，完全走环境变量（生产形态不受影响）。
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _CONFIG_FILE
        if not candidate.is_file():
            continue
        values: dict[str, str] = {}
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
        return values
    return {}


_FILE_ENV = _read_config_file()


def _cfg(name: str, default: str = "") -> str:
    """环境变量 → deploy/.env（含 compose 的等价键）→ 默认值。"""
    if os.environ.get(name):
        return os.environ[name]
    for key in _FILE_KEYS.get(name, (name,)):
        if _FILE_ENV.get(key):
            return _FILE_ENV[key]
    return default


_DSN = {
    "host": _cfg("COMIC_MYSQL_HOST", "127.0.0.1"),
    # 本项目独占实例的宿主端口（app 在容器内走编排内网 3306，见 deploy/docker-compose.yml）
    "port": int(_cfg("COMIC_MYSQL_PORT", "3309")),
    "user": _cfg("COMIC_MYSQL_USER", "root"),
    # 无默认口令：宁愿连接失败报错，也不要静默连上一个"碰巧能用"的库
    "password": _cfg("COMIC_MYSQL_PASSWORD"),
    "database": _cfg("COMIC_MYSQL_DB", "comic"),
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
    "autocommit": True,
}


# ---------------- 热度算法（唯一真源） ----------------
# 热度 = 起底 + 浏览次数 × 每浏览分 + 收藏数 × 每收藏分
# 热度**不落库**：库里只存真实计数（comic.views）与收藏关系（favorite 表），
# 展示与排序都由 heat_sql() 实时算出 —— 这样调整权重无需回填历史数据。
HEAT_BASE = 1000
HEAT_PER_VIEW = 1
HEAT_PER_FAVORITE = 2


def heat_sql(
    comic_alias: str = "c", favorite_count_sql: str = "COUNT(DISTINCT f.user_id)"
) -> str:
    """生成热度 SQL 表达式（查询需 LEFT JOIN favorite f 才能用收藏项）。

    排序与序列化共用这一处定义，避免权重散落多处导致漂移。
    """
    return (
        f"({HEAT_BASE} + {comic_alias}.views * {HEAT_PER_VIEW}"
        f" + {HEAT_PER_FAVORITE} * {favorite_count_sql})"
    )


def _now() -> datetime:
    """当前时刻（秒精度、naive 本机时间）。

    直接返回 datetime 而不是 ISO 字符串：时间列已是 MySQL `DATETIME`，
    由驱动按 'YYYY-MM-DD HH:MM:SS' 格式化，避免字符串自带 'T' 分隔符/时区
    写法差异导致的隐式转换问题（这是 varchar(32) 时代的遗留坑）。
    """
    return datetime.now().replace(microsecond=0)


def _as_dt(value) -> datetime | None:
    """把 ISO 字符串（可含 'T'，如 SyncStats.started_at）归一成 datetime。

    已是 datetime 的原样返回；None 透传；无法解析时记警告并回落到当前时刻
    （目标列均 NOT NULL，不能写 None）。
    """
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value)).replace(microsecond=0)
    except ValueError:
        logger.warning("时间字段无法解析，已回落为当前时刻: %r", value)
        return _now()


def _until_bound(value) -> tuple[object, bool]:
    """把「截止」参数归一成 (SQL 边界值, 是否用 `<` 排他比较)。

    语义**含边界**：只给日期（`YYYY-MM-DD`）→ 含当天全天，返回 (次日 00:00, True)；
    带时刻（`YYYY-MM-DD HH:MM:SS` / ISO 带 'T' / datetime）→ 含该时刻，返回 (原值, False)。
    这样 UI 上「截止 09-10」就是 09-10 23:59:59 之前都在范围内，符合直觉。
    """
    text = str(value).strip()
    if len(text) == 10 and text.count("-") == 2:  # 纯日期
        try:
            return datetime.strptime(text, "%Y-%m-%d") + timedelta(days=1), True
        except ValueError:
            pass
    return value, False
