"""日志初始化（L0 基础设施，只依赖标准库）。

两件事：

1. **给自家日志加时间戳**：`comic_crawler.*` / `comic.admin` 的消息此前经 root 的
   lastResort 处理器直出，**既没有时间也没有级别** —— 出问题时看 `logs/api.log`
   无法定位时间线（如「16:17 那次转存为什么失败」）。
2. **轮询 / 探活接口不进访问日志**：管理台每几秒轮询一次任务状态与日志、
   预览面板定期探活，这类请求会把 api.log 刷满（实测 `GET /api/admin/tasks` 占 549 行、
   `/api/health` 87 行、`/api/admin/logs` 69 行，而同期真实业务请求才几百行），
   且"谁在轮询"看代码就知道，排查价值为零。

单独成模块（而不是写在 main.py 里）的理由：main.py 是装配入口，导入它会连带
`routers` → `core.db`（建存储实例）；把这段纯 stdlib 逻辑放这里，单测可以直接导入，
**不连库、不引 FastAPI**。
"""
from __future__ import annotations

import logging

# 纯轮询 / 探活接口：只丢这些路径的**访问日志**，业务日志与其他请求照常记录。
# 前缀匹配（`/api/admin/tasks/xxx` 也会命中）。要调整就改这一行。
QUIET_PATHS: tuple[str, ...] = (
    "/api/admin/tasks",   # 任务状态轮询（触发采集/转存后前端每 1~2 秒问一次）
    "/api/admin/logs",    # 管理台「采集/转存日志」弹窗，打开期间每 4 秒拉一次
    "/api/health",        # 探活
)


class QuietPollingFilter(logging.Filter):
    """丢掉纯轮询 / 探活接口的访问日志记录。

    uvicorn 的访问日志调用形态是 ``logger.info('%s - "%s %s HTTP/%s" %d', client, method, path, ver, status)``，
    因此 ``record.args`` 是 5 元组、请求路径在 ``args[2]``（**含 query string**，先切掉再比）。
    """

    @staticmethod
    def is_quiet(path: str) -> bool:
        """路径是否属于「不记访问日志」的那类。

        按**路径边界**匹配（相等或后跟 `/`），避免 `/api/admin/tasksomething` 被误伤。
        """
        return any(path == p or path.startswith(p + "/") for p in QUIET_PATHS)

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3:
            return True  # 形态与预期不符（uvicorn 改过格式）→ 保守放行，宁可多记不可丢
        return not self.is_quiet(str(args[2]).split("?", 1)[0])


_QUIET_FILTER = QuietPollingFilter()  # 单例：重复 setup 时 addFilter 不会叠加


# 这些 logger 前缀调到 INFO（其余第三方库留在 root 的 WARNING，否则 httpx 会对每张图刷一行）。
# 注意 `services` 必须在内：api-service 自己的业务日志（如「读时登记页清单」）用的是
# `logging.getLogger(__name__)`，名字是 `services.*` —— 漏掉的话这些 INFO 会被静默丢弃。
# `comic_core` 是公共内核（存储/图库/标签归一）的日志名前缀，与 `comic_crawler` 同理。
INFO_LOGGERS: tuple[str, ...] = ("comic_crawler", "comic_core", "comic.admin", "services")


def install_db_handler():
    """把日志落库的 Handler 挂到 root（`log_record` 表，见 crawler 的 log_handler 模块）。

    延迟导入：只有真正要装的时候才 import 那个 Handler（会顺带拉起 pymysql 等），
    单测/脚本里只想用过滤器与级别配置时不受影响。
    """
    from comic_core.storage.mysql.log_handler import install

    return install()


def setup() -> None:
    """初始化日志（`main.py` 导入时调用一次；重复调用是幂等的）。"""
    logging.basicConfig(
        level=logging.WARNING,  # INFO 会让 httpx 对每张图刷一行请求日志
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for name in INFO_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
    # uvicorn 自己的 logger 带 handler 且 propagate=False，不受上面格式器影响；
    # 这里只额外挂一个过滤器，把轮询接口的访问记录丢掉。
    logging.getLogger("uvicorn.access").addFilter(_QUIET_FILTER)
    # 业务日志另外落一份到 MySQL（log_record 表）—— 管理台「日志查询」页查它，不再读日志文件
    install_db_handler()
