"""管理台「定时任务」配置的持久化 —— **读写都归采集层**。

配置回答：**什么时候跑（cron）、对哪些源跑、按什么模式跑、采样多少**。
落盘位置见 `comic_core.paths.SCHEDULE_FILE`（`<data>/schedule.json`，与图库、源开关
同在运行时数据目录），env `COMIC_SCHEDULE_FILE` 可覆盖。

## 节奏：5 段 cron（把「每天定点」与「每隔一段时间」合并成一个表达式）

解析规则见 `scheduling/cron.py`（`分 时 日 月 周`）：

| 想要的效果 | 表达式 |
|---|---|
| 每天 03:00（默认） | `0 3 * * *` |
| 每隔 15 分钟 | `*/15 * * * *` |
| 每 6 小时 | `0 */6 * * *` |
| 每周一 03:00 | `0 3 * * 1` |
| 每月 1 号 03:00 | `0 3 1 * *` |

⚠️ **旧格式（`frequency` / `startAt` / `intervalMinutes` 三个字段）已下线、不再读取**
（2026-10-06 定：合并成一个 cron 表达式，不保留兼容）。读到旧格式会**记一条 error 并回落
默认表达式**（不静默），手上那份配置已在同一次改动里迁移成 `cron`。

## 动作：`action`

| 值 | 做什么 |
|---|---|
| `sync`（默认） | 对 `sources` 里每个源各跑一轮采集（`mode` / `limit` / `since` 生效） |
| `inspect` | **失效巡检**：转存未转存页 + 全表校验已转存对象 + 恢复丢失（`since` 限定转存窗口；`mode`/`limit` 不适用） |

⚠️ 定时巡检**不含**管理台手动「失效巡检」的第 3 步「全库封面自愈」—— 那一步偏重，留给手动按钮；
与旧的轮询调度是同一个取舍：巡检频率高，不该每次都多打一轮源站请求。
`inspect` 时 `sources` **恰好点名一个源** → 只巡检它（同时限定转存范围），否则全库/全源
（校验部分本来就是全表，见 `scheduling/heal.py`）。

## 与 `sources/state.py` 的分工

| 文件 | 存什么 |
|---|---|
| `source_state.json` | 各源的**启停**（管理台那张开关） |
| `schedule.json` | **定时任务的参数**（cron / 数据源 / 模式 / limit / since） |

⚠️ **定时任务不看 `source_state.json`**：它由管理台显式声明"对哪些源、什么时候跑"，
**参数即准入**。此前 `comic-scheduler` 读的是代码里的 `SOURCES[].enabled`，于是留下
"管理台关掉的源仍会被定时采集"这条长期差异（见 `deploy/docker-compose.yml` 与 `docs/deploy.md`）。

⚠️ env 覆盖**只接受绝对路径**（相对路径忽略并回落默认）—— 理由同 `sources/state.py`：
wheel 装进 site-packages 后默认位置落在镜像内部，容器里必须由 env 指到 bind 的 `/data`。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from comic_core.paths import SCHEDULE_FILE

from ..sources import SOURCES
from .cron import DEFAULT_CRON

logger = logging.getLogger(__name__)

#: 采集模式（与管理台「触发采集」的 `mode` 同义，见 api-service/schemas.py 的 AdminSyncBody）
MODE_INCREMENTAL = "incremental"
MODE_FULL = "full"
MODES: tuple[str, ...] = (MODE_INCREMENTAL, MODE_FULL)

#: 定时任务的**动作**（这一轮到底干什么）
#: - `sync`    逐源采集（`mode` / `limit` / `since` 生效）
#: - `inspect` 失效巡检：转存未转存页 + 全表校验已转存对象 + 恢复丢失（`since` 限定转存窗口）
ACTION_SYNC = "sync"
ACTION_INSPECT = "inspect"
ACTIONS: tuple[str, ...] = (ACTION_SYNC, ACTION_INSPECT)

#: 已下线的旧字段：读到它们说明配置没迁移（见模块 docstring）
_LEGACY_KEYS = ("frequency", "startAt", "intervalMinutes")


@dataclass
class ScheduleConfig:
    """定时任务参数（空 `sources` = 全部已注册源）。"""

    enabled: bool = False
    cron: str = DEFAULT_CRON
    #: 这一轮干什么：`sync`（默认，逐源采集）/ `inspect`（失效巡检）
    action: str = ACTION_SYNC
    sources: list[str] = field(default_factory=list)
    mode: str = MODE_INCREMENTAL
    limit: int | None = None
    since: str | None = None

    def normalized(self) -> ScheduleConfig:
        """把外部写进来的值收敛为合法值（文件可手改、接口可传脏值）。

        cron 这里只做**空白归一化**（折掉多余空格/首尾空白），**不做语义校验**：
        语义校验由接口层（保存时 `parse_cron` → 400）与执行器（触发前解析，失败则本轮不跑
        并把原因报到管理台）分别负责 —— 这样"配置被手改坏"不会让服务起不来，也不会静默改掉
        用户写的表达式（好让管理台能把错的那串原样显示出来）。
        """
        cron = " ".join(str(self.cron or "").split()) or DEFAULT_CRON

        action = self.action if self.action in ACTIONS else ACTION_SYNC

        mode = self.mode if self.mode in MODES else MODE_INCREMENTAL

        limit = self.limit
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            limit = None

        since = str(self.since).strip() if self.since else None
        if not since:
            since = None

        # 源名收敛到已注册清单（未知名字丢弃并告警）—— 避免配置里留一个永远跑不到的源
        known = {s.name for s in SOURCES}
        sources: list[str] = []
        for raw in self.sources or []:
            name = str(raw).strip()
            if not name:
                continue
            if name not in known:
                logger.warning("定时任务里的数据源 %r 未注册，已忽略", raw)
                continue
            if name not in sources:
                sources.append(name)

        return ScheduleConfig(
            enabled=bool(self.enabled),
            cron=cron,
            action=action,
            sources=sources,
            mode=mode,
            limit=limit,
            since=since,
        )

    def to_dict(self) -> dict:
        return asdict(self)


def schedule_path() -> Path:
    """配置文件的实际位置：env `COMIC_SCHEDULE_FILE`（绝对路径）优先，否则用默认值。"""
    env = os.environ.get("COMIC_SCHEDULE_FILE", "").strip()
    if env and os.path.isabs(env):
        return Path(env)
    return SCHEDULE_FILE


def load_schedule_config() -> ScheduleConfig:
    """读取配置（**始终返回可用对象**）。

    文件不存在 → 全默认（`enabled=False`，等于没开定时任务）；解析失败 → 回落默认并记日志；
    读到**已下线的旧格式** → 记 error 并回落默认表达式（不静默）。
    """
    path = schedule_path()
    if not path.exists():
        return ScheduleConfig()
    try:
        raw = json.loads(path.read_text("utf-8"))
    except Exception:
        logger.exception("读取定时任务配置失败，回落默认值：%s", path)
        return ScheduleConfig()
    if not isinstance(raw, dict):
        logger.warning("定时任务配置不是 JSON 对象，回落默认值：%s", path)
        return ScheduleConfig()

    if "cron" not in raw and any(k in raw for k in _LEGACY_KEYS):
        logger.error(
            "定时任务配置仍是已下线的旧格式（%s），请改写成 cron 表达式（如 `0 3 * * *`）；"
            "本次按默认 %s 处理：%s",
            "/".join(k for k in _LEGACY_KEYS if k in raw), DEFAULT_CRON, path,
        )

    return ScheduleConfig(
        enabled=raw.get("enabled", False),
        cron=raw.get("cron", DEFAULT_CRON),
        action=raw.get("action", ACTION_SYNC),
        sources=list(raw.get("sources") or []),
        mode=raw.get("mode", MODE_INCREMENTAL),
        limit=raw.get("limit"),
        since=raw.get("since"),
    ).normalized()


def save_schedule_config(config: ScheduleConfig) -> ScheduleConfig:
    """写入配置，返回**归一化后**的对象。

    与开关状态不同，这里**写失败让它抛**：管理台点了「保存」却根本没落盘，
    比"静默继续用旧值"更难排查。（cron 的语义校验由调用方先做，见 `normalized` 的说明。）
    """
    normalized = config.normalized()
    schedule_path().write_text(
        json.dumps(normalized.to_dict(), ensure_ascii=False, indent=2), "utf-8"
    )
    return normalized


# ---------------- 由配置推导的时刻（**纯函数**：执行器与 api 共用） ----------------
#
# 收在这里而不是各写一份：执行器（comic-scheduler 进程）要判「现在该不该跑」，
# api 要显示「下次执行」—— 两边必须用同一个 cron 引擎与同一套窗口语义。

#: 命中后的宽限窗口（秒）：窗口内仍算这一轮，避免"点前几秒重启 → 这一轮不跑"
GRACE_SECONDS = 300

#: 「最近一次命中」只需回看宽限窗口那么久（更早的命中早就过窗了）
_LOOKBACK_MINUTES = GRACE_SECONDS // 60 + 1


def _spec(cron: str):
    """解析 cron（延迟导入，避免本模块的持久化职责被解析器初始化拖着）。"""
    from .cron import parse_cron

    return parse_cron(cron)


def is_due(config, now: datetime, last_run_ts: float | None = None) -> datetime | None:
    """`now` 是否该触发一轮：该触发返回**那一轮的命中时刻**，否则 `None`。

    判定 = cron 在宽限窗口内命中过 **且** 那一轮还没跑过（`last_run_ts` 早于命中时刻）。
    窗口外直接放弃（**错过不补**）。表达式非法会抛 `ValueError`，由调用方决定怎么记。
    """
    if not config.enabled:
        return None
    spec = _spec(config.cron)
    base = now.replace(second=0, microsecond=0)
    for back in range(_LOOKBACK_MINUTES + 1):
        moment = base - timedelta(minutes=back)
        if not spec.matches(moment):
            continue
        if now >= moment + timedelta(seconds=GRACE_SECONDS):
            return None                                   # 已过窗：这一轮放弃
        if last_run_ts is not None and last_run_ts >= moment.timestamp():
            return None                                   # 这一轮已经跑过
        return moment
    return None


def next_run_at(config, now: datetime) -> datetime | None:
    """下一次执行时刻（**严格晚于 `now`**）；未启用 / 表达式非法 / 无解返回 `None`。

    刻意**不**返回"正处在窗口内、还没跑"的那一轮 —— 它的时刻在过去，而这是给页面显示
    「下次执行」用的；那种"待跑"状态由运行态（`schedule_state.json`）体现。
    """
    if not config.enabled:
        return None
    return _spec(config.cron).next_after(now)
