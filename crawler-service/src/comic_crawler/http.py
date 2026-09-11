"""抓取客户端：UA 池轮换、随机延迟、指数退避重试、可选代理池。

对应架构方案 §2.4「反爬处理（合规框架内）」：
- 随机 UA 轮换，避免固定指纹被识别；
- 请求间随机延迟（min_delay ~ max_delay），控制访问频率；
- 指数退避重试（max_retries 次），失败不风暴式重试；
- proxy_pool 预留自建代理池轮换入口。

额外能力：支持 file:// 与本地路径读取，便于用 fixture 离线重放
（联调 / 单测 / 复现问题），真实运行直接走 http(s)。
"""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DEFAULT_UA_POOL: list[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

# ---- 抓取限速默认值（**单一真源**；要按源定制就直接给 HttpFetcher 传参）----
DEFAULT_MIN_DELAY = 0.5    # 请求间隔下限（秒）
DEFAULT_MAX_DELAY = 2.0    # 请求间隔上限（秒）
DEFAULT_MAX_RETRIES = 3    # 失败重试次数（指数退避）
DEFAULT_BASE_DELAY = 1.0   # 退避基数（秒）：第 n 次重试等待 base_delay * 2**n
DEFAULT_TIMEOUT = 10.0     # 单请求超时（秒）


class HttpFetcher:
    """带反爬礼仪的 HTTP 抓取客户端（线程安全：每次请求独立 client）。"""

    def __init__(
        self,
        min_delay: float = DEFAULT_MIN_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        timeout: float = DEFAULT_TIMEOUT,
        ua_pool: list[str] | None = None,
        proxy_pool: list[str] | None = None,
    ) -> None:
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_retries = max(0, max_retries)
        self.base_delay = base_delay
        self.timeout = timeout
        self.ua_pool = ua_pool or DEFAULT_UA_POOL
        self.proxy_pool = proxy_pool or []
        self._last_request_at = 0.0

    # ------------------------------------------------------------------
    def get(self, url: str) -> str:
        """抓取一个页面，返回 HTML 文本。失败抛 httpx.HTTPError。"""
        if url.startswith("file://"):
            return Path(url[len("file://"):]).read_text(encoding="utf-8")
        if not url.startswith(("http://", "https://")):
            local = Path(url)
            if local.exists():
                return local.read_text(encoding="utf-8")
            raise ValueError(f"无法识别的地址（本地文件不存在?）：{url}")

        return self._get_http(url)

    # ------------------------------------------------------------------
    def _get_http(self, url: str) -> str:
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._pace()
            headers = {"User-Agent": self._pick_ua()}
            proxy = self._pick_proxy()
            try:
                with httpx.Client(
                    timeout=self.timeout,
                    follow_redirects=True,
                    proxy=proxy,
                    headers=headers,
                ) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    return resp.text
            except (httpx.HTTPError, httpx.TransportError) as exc:
                last_err = exc
                if attempt < self.max_retries:
                    sleep_s = self.base_delay * (2**attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        "GET %s 失败(%s)，第 %d/%d 次重试，%.1fs 后…",
                        url, exc.__class__.__name__, attempt + 1, self.max_retries, sleep_s,
                    )
                    time.sleep(sleep_s)
        raise last_err if last_err else RuntimeError(f"GET {url} 失败")

    # ------------------------------------------------------------------
    def _pace(self) -> None:
        """请求间隔节流：距上次请求至少 (min_delay ~ max_delay) 随机值。"""
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if self._last_request_at and elapsed < self.min_delay:
            wait = random.uniform(self.min_delay, max(self.max_delay, self.min_delay))
            time.sleep(max(0.0, wait - elapsed))
        self._last_request_at = time.monotonic()

    def _pick_ua(self) -> str:
        return random.choice(self.ua_pool)

    def _pick_proxy(self) -> str | None:
        """从代理池轮换（若配置了代理池则循环取一个，避免单 IP 高频）。"""
        if not self.proxy_pool:
            return None
        idx = int(time.monotonic()) % len(self.proxy_pool)
        return self.proxy_pool[idx]
