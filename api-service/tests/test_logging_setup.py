"""轮询 / 探活接口不进访问日志的过滤器（`core/logging_setup.QuietPollingFilter`）。

**纯逻辑：不连库、不引 FastAPI**（被测模块只依赖标准库；这也是把这段逻辑从 main.py
拆到 core/logging_setup.py 的原因）。

为什么要守：管理台每几秒轮询任务状态与日志、预览面板定期探活，实测这些请求在 api.log 里
占 549 + 69 + 87 行，而同期真实业务请求才几百行 —— 过滤失效的话，日志会被"自己人"的轮询刷满。
"""
from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.logging_setup import INFO_LOGGERS, QUIET_PATHS, QuietPollingFilter  # noqa: E402


def _access_record(path: str) -> logging.LogRecord:
    """模拟 uvicorn 的访问日志记录：

    `logger.info('%s - "%s %s HTTP/%s" %d', client, method, path, ver, status)`
    """
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:36846", "GET", path, "1.1", 200),
        exc_info=None,
    )


class TestQuietPollingFilter(unittest.TestCase):
    def setUp(self) -> None:
        self.f = QuietPollingFilter()

    def test_polling_paths_are_dropped(self):
        """三个纯轮询/探活入口（含带 query 与带子路径的形态）都不记。"""
        for path in (
            "/api/admin/tasks",
            "/api/admin/tasks/inspect-2-1789373866",
            "/api/admin/logs?level=WARNING&page=1",  # query string 要能被切掉
            "/api/admin/logs",
            "/api/health",
        ):
            self.assertFalse(self.f.filter(_access_record(path)), path)

    def test_real_business_paths_are_kept(self):
        """真实业务请求照常记录（包括管理台里非轮询的那些）。"""
        for path in (
            "/api/comics?page=1&page_size=50",
            "/api/chapters/679/pages",
            "/api/admin/sources",
            "/api/admin/transfer",
            "/api/admin/sync",
            "/api/covers/138",
            "/api/images/151/679/1",
            "/api/sources/search?q=test",
        ):
            self.assertTrue(self.f.filter(_access_record(path)), path)

    def test_prefix_match_respects_path_boundary(self):
        """按路径边界匹配：带子路径的轮询要滤掉，但 `tasksomething` / `healthy` 不能被误伤。"""
        self.assertTrue(self.f.is_quiet("/api/admin/tasks"))          # 列表轮询
        self.assertTrue(self.f.is_quiet("/api/admin/tasks/1"))        # 单任务轮询
        self.assertFalse(self.f.is_quiet("/api/admin/tasksomething"))  # 只是前缀相同
        self.assertFalse(self.f.is_quiet("/api/healthy"))             # 只是前缀相同

    def test_unexpected_record_shape_is_kept(self):
        """uvicorn 若改了日志格式（args 不是 5 元组）→ 保守放行，不静默丢日志。"""
        rec = logging.LogRecord(
            name="uvicorn.access", level=logging.INFO, pathname=__file__, lineno=1,
            msg="Application startup complete.", args=(), exc_info=None,
        )
        self.assertTrue(self.f.filter(rec))

    def test_quiet_paths_are_documented_entries(self):
        """过滤清单必须只包含这三个轮询入口（改这里就等于改行为，测试随即失效提醒）。"""
        self.assertEqual(
            set(QUIET_PATHS), {"/api/admin/tasks", "/api/admin/logs", "/api/health"}
        )

    def test_info_loggers_cover_api_side_modules(self):
        """调到 INFO 的 logger 前缀必须覆盖 api-service 自己的业务日志。

        踩过的坑：`services.ondemand` 用 `getLogger(__name__)`，名字是 `services.*`，
        最初只放开了 `comic_crawler` / `comic.admin`，导致「读时登记页清单」这句 INFO
        被 root 的 WARNING 静默丢掉。
        """
        self.assertIn("services", INFO_LOGGERS)
        self.assertIn("comic_crawler", INFO_LOGGERS)
        self.assertIn("comic.admin", INFO_LOGGERS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
