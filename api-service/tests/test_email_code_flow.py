"""邮箱验证码流程单测：归一 / 频控 / 次数 / 过期 / 单次消费 / 脱敏 / 改密后旧 token 失效。

**纯逻辑、不连库、不起 HTTP**（与 `test_response_contract.py` 同一路数）：存储层用
`_stub_db.CODES`（内存里做**真语义**，见那里的注释），账号用 `_stub_db.USERS`。

为什么这些点必须有测试（都是"看起来能跑、实际会悄悄坏"的地方）：

- **反枚举**：未注册邮箱也落库、同样占 60 秒冷却；一旦有人给"查不到用户"加了 404/不发信之外的
  差异，攻击者就能拿它当「这个邮箱注册过没有」的探针；
- **频控**：冷却 / 每小时配额是纯时序逻辑，改一个比较符号就全线失效，而且**不会报错**；
- **单次消费**：靠条件 UPDATE 的 `rowcount == 1`，写成"先查后写"在双击下就会放行两次；
- **改密后旧 token 失效**（`core/security.get_current_user`）：这是**全站生效**的判断，
  写错会把所有人踢成 401（设计 R7），`password_changed_at IS NULL` 与 5 秒容差两条边界必须钉住。
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from _stub_db import CODES, USERS, install_stub

install_stub()  # ⚠️ 必须在导入任何应用模块之前（应用模块是 `from core.db import ...`，导入时绑定值）

from fastapi import HTTPException  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402

from core.security import decode_token, get_current_user, make_token  # noqa: E402
from services import email_codes, mailer  # noqa: E402


def _add_user(uid: int = 1, username: str = "alice", email: str | None = None) -> dict:
    """造一行用户并放进桩（`email=None` = 未绑定，与老库里的存量行同形）。"""
    row = USERS.make(uid, username, "user")
    row["email"] = email
    USERS.rows.append(row)
    return row


class _MailFallbackCase(unittest.TestCase):
    """所有会触发"发信"的用例的公共基类：把邮件通道压成 `COMIC_MAIL_FALLBACK=log`。

    这样测的是**验证码业务**，而不是"这台机器有没有配 SMTP"。要测发信失败的用例自己再覆盖环境变量。
    """

    def setUp(self) -> None:
        CODES.reset()
        USERS.reset()
        env = patch.dict(
            os.environ,
            {
                "COMIC_MAIL_FALLBACK": "log",
                "COMIC_SMTP_HOST": "",
                "COMIC_SMTP_USER": "",
                "COMIC_MAIL_FROM": "",
            },
        )
        env.start()
        self.addCleanup(env.stop)


# ============================ 归一 / 校验 / 脱敏 ============================


class TestEmailHelpers(unittest.TestCase):
    def test_normalize_strips_and_lowers(self) -> None:
        self.assertEqual(email_codes.normalize_email("  Alice@QQ.com "), "alice@qq.com")
        self.assertEqual(email_codes.normalize_email(None), "")  # type: ignore[arg-type]

    def test_check_email_accepts_common_forms(self) -> None:
        for ok in ("a@qq.com", "ab.c@mail.example.com", "a_b+c@x.cn"):
            self.assertEqual(email_codes.check_email(ok), "", ok)

    def test_check_email_rejects_malformed(self) -> None:
        for bad in ("", "no-at", "a@b", "a@b.", "a@.com", "a b@x.com", "a@@x.com", "a@x..com"):
            self.assertEqual(email_codes.check_email(bad), "邮箱格式不正确", bad)

    def test_check_email_rejects_too_long(self) -> None:
        long_email = "a" * 120 + "@example.com"          # 132 位 > 128
        self.assertEqual(email_codes.check_email(long_email), "邮箱长度不能超过 128 个字符")
        # 恰好 128 位仍算合法（列宽就是 128）
        edge = "a" * (128 - len("@qq.com")) + "@qq.com"
        self.assertEqual(len(edge), 128)
        self.assertEqual(email_codes.check_email(edge), "")

    def test_mask_email(self) -> None:
        self.assertEqual(mailer.mask_email("abc@qq.com"), "ab***@qq.com")   # 本地名 ≥3 → 前 2
        self.assertEqual(mailer.mask_email("ab@qq.com"), "a***@qq.com")     # 本地名 <3 → 首字母
        self.assertEqual(mailer.mask_email("a@qq.com"), "a***@qq.com")
        self.assertEqual(mailer.mask_email(""), "***")                      # 脏值整串打码

    def test_hash_code_depends_on_purpose(self) -> None:
        """同一串码在 reset / bind 下哈希必须不同 —— 防"拿绑定的码去重置密码"。"""
        self.assertNotEqual(
            email_codes.hash_code("a@qq.com", "reset", "123456"),
            email_codes.hash_code("a@qq.com", "bind", "123456"),
        )
        # 同一入参必须稳定（否则发出去的码永远验不过）
        self.assertEqual(
            email_codes.hash_code("a@qq.com", "reset", "123456"),
            email_codes.hash_code("a@qq.com", "reset", "123456"),
        )
        self.assertEqual(len(email_codes.hash_code("a@qq.com", "reset", "123456")), 64)


# ============================ 发码：冷却 / 配额 / 反枚举 ============================


class TestIssue(_MailFallbackCase):
    def test_ok_then_cooldown(self) -> None:
        _add_user(email="old@qq.com")
        self.assertEqual(email_codes.issue("old@qq.com", "reset", "1.1.1.1"), ("ok", 60))
        result, seconds = email_codes.issue("old@qq.com", "reset", "1.1.1.1")
        self.assertEqual(result, "cooldown")
        self.assertGreater(seconds, 0)
        self.assertLessEqual(seconds, 60)

    def test_cooldown_releases_after_60s(self) -> None:
        _add_user(email="old@qq.com")
        email_codes.issue("old@qq.com", "reset", "1.1.1.1")
        CODES.backdate(61)
        self.assertEqual(email_codes.issue("old@qq.com", "reset", "1.1.1.1"), ("ok", 60))

    def test_email_quota_after_5_per_hour(self) -> None:
        _add_user(email="old@qq.com")
        for _ in range(5):
            email_codes.issue("old@qq.com", "reset", "1.1.1.1")
            CODES.backdate(61)      # 每次都不触发冷却，但都还在同一小时内
        self.assertEqual(email_codes.issue("old@qq.com", "reset", "1.1.1.1")[0], "quota_email")

    def test_ip_quota_after_20_per_hour(self) -> None:
        for i in range(20):
            CODES.insert_code(
                f"other{i}@qq.com", "reset", "x" * 64, datetime.now() + timedelta(minutes=10), "9.9.9.9"
            )
        CODES.backdate(61)          # 同一小时内，但都不触发"同邮箱"冷却
        self.assertEqual(email_codes.issue("new@qq.com", "reset", "9.9.9.9")[0], "quota_ip")

    def test_unregistered_email_follows_the_same_path(self) -> None:
        """**反枚举的核心**：查不到账号时不发信，但落库、占冷却、返回值与已注册完全一致。"""
        _add_user(email="old@qq.com")           # 库里只有一个 old@qq.com
        with patch.object(email_codes.mailer, "send_verify_code") as send:
            result = email_codes.issue("nobody@qq.com", "reset", "1.1.1.1")
        self.assertEqual(result, ("ok", 60))
        send.assert_not_called()                 # 没发信 → 日志里也不会有码
        self.assertEqual(len(CODES.rows), 1)     # 但**真的落了一行**
        self.assertEqual(email_codes.issue("nobody@qq.com", "reset", "1.1.1.1")[0], "cooldown")

    def test_registered_email_is_actually_sent(self) -> None:
        _add_user(email="old@qq.com")
        with patch.object(email_codes.mailer, "send_verify_code", return_value=True) as send:
            self.assertEqual(email_codes.issue("old@qq.com", "reset", "1.1.1.1"), ("ok", 60))
        send.assert_called_once()
        code = send.call_args[0][1]
        self.assertTrue(code.isdigit() and len(code) == 6, code)

    def test_bind_purpose_always_sends(self) -> None:
        """绑定邮箱要绑的正是「还没被任何账号绑定的邮箱」—— 这时**必须真发信**。

        这就是设计 §3.4「#1 / #3 统一：若邮箱在 user 表存在则发信」对 #3 不成立的地方
        （照抄会让绑定功能永远收不到码），见 03-impl §6 偏差 1。
        """
        _add_user(email="old@qq.com")
        with patch.object(email_codes.mailer, "send_verify_code", return_value=True) as send:
            self.assertEqual(email_codes.issue("brand-new@qq.com", "bind", "1.1.1.1"), ("ok", 60))
        send.assert_called_once()

    def test_send_failure_rolls_back_the_row(self) -> None:
        """发信失败 → 删掉刚插入的码行 → 用户能立刻重试，不被自己的失败请求锁 60 秒。"""
        _add_user(email="old@qq.com")
        with patch.dict(os.environ, {"COMIC_MAIL_FALLBACK": ""}):
            with patch.object(email_codes.mailer, "send_verify_code", return_value=False):
                self.assertEqual(email_codes.issue("old@qq.com", "reset", "1.1.1.1"), ("send_failed", 0))
        self.assertEqual(CODES.rows, [])
        # 没有被锁：立刻重试不会再撞 60 秒冷却
        self.assertEqual(email_codes.issue("old@qq.com", "reset", "1.1.1.1"), ("ok", 60))

    def test_new_code_invalidates_the_old_one(self) -> None:
        _add_user(email="old@qq.com")
        email_codes.issue("old@qq.com", "reset", "1.1.1.1")
        first_id = CODES.rows[-1]["id"]
        CODES.backdate(61)
        email_codes.issue("old@qq.com", "reset", "1.1.1.1")
        active = CODES.active_rows()
        self.assertEqual(len(active), 1)                       # 同时只有一条有效码
        self.assertNotEqual(active[0]["id"], first_id)          # 且是最新那条
        self.assertIsNotNone(
            next(r for r in CODES.rows if r["id"] == first_id)["consumed_at"]
        )


# ============================ 校验 + 消费 ============================


class TestCheckAndConsume(_MailFallbackCase):
    def _seed(self, code: str = "123456", purpose: str = "reset", email: str = "a@qq.com",
              expires_in: int = 600, attempts: int = 0) -> int:
        code_id = CODES.insert_code(
            email, purpose, email_codes.hash_code(email, purpose, code),
            datetime.now() + timedelta(seconds=expires_in), "1.1.1.1",
        )
        CODES.rows[-1]["attempts"] = attempts
        return code_id

    def test_ok_and_single_use(self) -> None:
        self._seed()
        self.assertEqual(email_codes.check_and_consume("a@qq.com", "reset", "123456"), "ok")
        # 第二次（复用）：行已消费 → 没有可用码，对外就是「验证码错误或已失效」
        self.assertEqual(email_codes.check_and_consume("a@qq.com", "reset", "123456"), "no_code")

    def test_wrong_code_counts_then_invalidates(self) -> None:
        self._seed()
        for _ in range(4):
            self.assertEqual(email_codes.check_and_consume("a@qq.com", "reset", "000000"), "mismatch")
        self.assertEqual(CODES.rows[0]["attempts"], 4)
        # 第 5 次错 → 到上限，整行作废
        self.assertEqual(email_codes.check_and_consume("a@qq.com", "reset", "000000"), "too_many")
        self.assertIsNotNone(CODES.rows[0]["consumed_at"])
        # 作废之后**连正确码也不认**
        self.assertEqual(email_codes.check_and_consume("a@qq.com", "reset", "123456"), "no_code")

    def test_too_many_when_attempts_already_exhausted(self) -> None:
        self._seed(attempts=5)
        self.assertEqual(email_codes.check_and_consume("a@qq.com", "reset", "123456"), "too_many")

    def test_expired_code_is_not_accepted(self) -> None:
        self._seed(expires_in=-1)        # 已过期
        self.assertEqual(email_codes.check_and_consume("a@qq.com", "reset", "123456"), "no_code")

    def test_no_code_at_all(self) -> None:
        self.assertEqual(email_codes.check_and_consume("nobody@qq.com", "reset", "123456"), "no_code")

    def test_purpose_isolation(self) -> None:
        """绑定邮箱的码不能用来重置密码（反之亦然）。"""
        self._seed(purpose="bind")
        self.assertEqual(email_codes.check_and_consume("a@qq.com", "reset", "123456"), "no_code")
        self.assertEqual(email_codes.check_and_consume("a@qq.com", "bind", "123456"), "ok")

    def test_uppercase_email_hits_the_same_row(self) -> None:
        """前端可能传 `A@QQ.com`：归一后必须命中同一行，否则用户"收到的码无效"。"""
        self._seed(email="a@qq.com")
        self.assertEqual(email_codes.check_and_consume(" A@QQ.com ", "reset", "123456"), "ok")


# ============================ 改密后旧 token 失效 ============================


class TestPasswordChangedInvalidatesToken(unittest.TestCase):
    """`core/security.get_current_user` 的「改密 / 重置后旧 token 立即失效」。

    这是**全站生效**的判断（设计 R7）：写错会把所有已登录用户踢成 401，
    所以三条边界各钉一个用例 —— NULL 跳过、超期失效、5 秒时钟容差内不失效。
    """

    def setUp(self) -> None:
        CODES.reset()
        USERS.reset()
        self.user = _add_user(uid=7, username="bob")

    def _cred(self, token: str) -> HTTPAuthorizationCredentials:
        return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    def test_null_password_changed_at_keeps_existing_tokens(self) -> None:
        """老库/老用户 `password_changed_at IS NULL` → 跳过判定，存量 7 天 token 不被本次上线踢掉。"""
        token = make_token(self.user["id"], self.user["username"])
        self.assertEqual(get_current_user(self._cred(token))["id"], 7)

    def test_token_issued_before_the_change_is_rejected(self) -> None:
        token = make_token(self.user["id"], self.user["username"])
        iat = int(decode_token(token)["iat"])
        # 改密时刻比 token 的 iat 晚 60 秒（远超 5 秒容差）→ 旧 token 必须失效
        USERS.rows[0]["password_changed_at"] = datetime.fromtimestamp(iat + 60)
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(self._cred(token))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(ctx.exception.detail, "登录已失效，请重新登录")

    def test_five_second_tolerance(self) -> None:
        """改密后前端立刻重登：新 token 的 iat 可能比库里时刻早几秒，5 秒内必须放行。"""
        token = make_token(self.user["id"], self.user["username"])
        iat = int(decode_token(token)["iat"])
        USERS.rows[0]["password_changed_at"] = datetime.fromtimestamp(iat + 3)
        self.assertEqual(get_current_user(self._cred(token))["id"], 7)

        USERS.rows[0]["password_changed_at"] = datetime.fromtimestamp(iat + 6)
        with self.assertRaises(HTTPException):
            get_current_user(self._cred(token))

    def test_new_token_after_change_works(self) -> None:
        """改密后再签发的新 token（iat ≥ changed）必须能用 —— 否则改完密码谁也登不进去。"""
        USERS.rows[0]["password_changed_at"] = datetime.now().replace(microsecond=0) - timedelta(seconds=10)
        token = make_token(self.user["id"], self.user["username"])
        self.assertEqual(get_current_user(self._cred(token))["id"], 7)


if __name__ == "__main__":
    unittest.main()
