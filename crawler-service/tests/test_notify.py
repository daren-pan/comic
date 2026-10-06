"""进程间**服务令牌**（`comic_core/notify.py`）—— 纯逻辑，不联网、不连库。

消息中心的写入只走 `POST /api/messages`，所以独立进程（`comic-scheduler`）需要一个
不依赖用户账号的凭据。做法是 HMAC 服务令牌：`<ts>.<HMAC-SHA256(secret, ts)>`，
密钥复用 `COMIC_JWT_SECRET`（compose 的 x-app-env 已同时注入两个服务），**不新增密钥、不新增依赖**。

本文件钉住四件事：正常校验通过、过期被拒、改一个字符就被拒、密钥不符被拒 ——
前两条防"令牌永不失效"，后两条防"谁都能签"。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from comic_core import notify  # noqa: E402

SECRET = "unit-test-secret"


class TestServiceToken(unittest.TestCase):
    def test_round_trip(self) -> None:
        token = notify.make_service_token(SECRET, ts=1_800_000_000)
        self.assertTrue(notify.verify_service_token(token, SECRET, now=1_800_000_000))

    def test_expired_is_rejected(self) -> None:
        token = notify.make_service_token(SECRET, ts=1_800_000_000)
        late = 1_800_000_000 + notify.TOKEN_TTL_SECONDS + 1
        self.assertFalse(notify.verify_service_token(token, SECRET, now=late), "过期令牌必须失效")

    def test_clock_skew_within_window_is_ok(self) -> None:
        token = notify.make_service_token(SECRET, ts=1_800_000_000)
        early = 1_800_000_000 - notify.TOKEN_TTL_SECONDS + 5
        self.assertTrue(notify.verify_service_token(token, SECRET, now=early), "轻微时钟偏差要容忍")

    def test_tampered_digest_is_rejected(self) -> None:
        token = notify.make_service_token(SECRET, ts=1_800_000_000)
        stamp, _, digest = token.partition(".")
        flipped = ("0" if digest[0] != "0" else "1") + digest[1:]
        self.assertFalse(notify.verify_service_token(f"{stamp}.{flipped}", SECRET, now=1_800_000_000))

    def test_tampered_timestamp_is_rejected(self) -> None:
        """改时间戳（想续命）会让签名对不上。"""
        token = notify.make_service_token(SECRET, ts=1_800_000_000)
        _, _, digest = token.partition(".")
        self.assertFalse(notify.verify_service_token(f"1800000001.{digest}", SECRET, now=1_800_000_001))

    def test_wrong_secret_is_rejected(self) -> None:
        token = notify.make_service_token(SECRET, ts=1_800_000_000)
        self.assertFalse(notify.verify_service_token(token, "another-secret", now=1_800_000_000))

    def test_garbage_is_rejected(self) -> None:
        for bad in ("", "nodot", "abc.def", ".", "1800000000.", "1800000000.nothex"):
            self.assertFalse(notify.verify_service_token(bad, SECRET, now=1_800_000_000), bad)

    def test_empty_secret_never_passes(self) -> None:
        """密钥没配（或配成空串）时必须一律拒绝 —— 否则等于人人可写。"""
        self.assertFalse(notify.verify_service_token("1800000000.abc", "", now=1_800_000_000))


class TestApiBase(unittest.TestCase):
    def test_env_override_and_default(self) -> None:
        import os

        old = os.environ.pop("COMIC_API_BASE", None)
        try:
            self.assertEqual(notify.api_base(), notify.DEFAULT_API_BASE)
            os.environ["COMIC_API_BASE"] = "http://comic-app:8000/"
            self.assertEqual(notify.api_base(), "http://comic-app:8000", "末尾斜杠要去掉")
        finally:
            os.environ.pop("COMIC_API_BASE", None)
            if old is not None:
                os.environ["COMIC_API_BASE"] = old


if __name__ == "__main__":
    unittest.main()
