"""邮箱验证码业务：生成 / 校验 / 频控（「忘记密码」与「绑定邮箱」共用）。

一条验证码的完整生命周期（值都在下面的常量里，逐条对齐设计 §3.2）：

| 项 | 值 | 落在哪 |
|---|---|---|
| 位数 | 6 位纯数字（`secrets.randbelow` 左补 0） | `_new_code()` |
| 存储 | `HMAC-SHA256(secret, "email:purpose:code")` 十六进制，**不存明文** | `hash_code()` |
| 有效期 | 10 分钟 | `CODE_TTL_MINUTES` |
| 单次有效 | 消费即写 `consumed_at`，并顶掉同 `email+purpose` 其它未用码 | `consume()` / `issue()` |
| 错误上限 | 5 次/码，到顶整行作废（正确码也不再认） | `MAX_ATTEMPTS`（与存储层同源） |
| 重发冷却 | 60 秒 | `COOLDOWN_SECONDS` |
| 每邮箱配额 | 1 小时 5 条 | `EMAIL_QUOTA_PER_HOUR` |
| 每 IP 配额 | 1 小时 20 条（取不到 IP 就跳过这层） | `IP_QUOTA_PER_HOUR` |
| 垃圾清理 | 每次发码前删 24h 前的行 | `PURGE_BEFORE_HOURS` |

## 为什么返回「枚举式结果」而不是抛异常

`issue()` / `check_and_consume()` 只回报**原因**（`CodeIssue` / `CodeCheck`），中文文案与 HTTP
状态码由 `routers/auth.py` 决定。这样：① 提示文案集中在一处，双端拿到的是同一句；
② 单测能直接断言原因，不必去猜 HTTP 层；③ `no_code` / `expired` / `mismatch` 三个原因
**对外可以给同一句「验证码错误或已失效」**（不给攻击者探测差异的面）。

## 反枚举（设计 §3.3 的关键约束）

`issue()` 对**已注册**与**未注册**邮箱走完全相同的路径：同样查冷却 → 同样查配额（同样可能
返回 `cooldown` / `quota_*`）→ 同样落一行 `email_code` → **只有该邮箱在 `user` 表存在时才真发信**。
调用方对两者返回同样的状态码与文案，所以「这个邮箱有没有注册」不可从响应判断。
残留侧信道只剩**响应耗时**（已注册要等 SMTP 往返），留后续改后台队列。
"""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
from datetime import datetime, timedelta
from typing import Literal

from comic_core.storage.mysql import MAX_ATTEMPTS

from core.db import codes, users
from core.security import HMAC_SECRET

from . import mailer

#: 发码结果：正常 / 冷却中 / 邮箱小时配额满 / IP 小时配额满 / 发信失败（→ 503）
CodeIssue = Literal["ok", "cooldown", "quota_email", "quota_ip", "send_failed"]
#: 校验结果：正常 / 没有可用的码 / 校验时刚好过期（或被并发抢走）/ 错误次数超限 / 码不对
CodeCheck = Literal["ok", "no_code", "expired", "too_many", "mismatch"]

CODE_LENGTH = 6
CODE_TTL_MINUTES = 10
COOLDOWN_SECONDS = 60
EMAIL_QUOTA_PER_HOUR = 5
IP_QUOTA_PER_HOUR = 20
PURGE_BEFORE_HOURS = 24

#: 邮箱长度上限 = `user.email VARCHAR(128)`，超了写库必失败 → 入口拦掉给中文提示
MAX_EMAIL_LEN = 128


def normalize_email(raw: str) -> str:
    """归一邮箱：去首尾空白 + 转小写。

    必须归一：`uk_email` 在 `utf8mb4_general_ci` 下已把大小写视为重复，但**大小写变体会让
    `email_code` 的冷却 / 配额按不同字符串各算一遍**（同一个邮箱被当成两个地址），
    统一小写后两种计数才一致。
    """
    return (raw or "").strip().lower()


def check_email(email: str) -> str:
    """校验**已归一**的邮箱 → 返回中文错误文案，`''` = 合法。

    只做形状判断（一个 `@`、本地名与域名都非空、域名含 `.`、无空白、长度 ≤ 128）；
    不追求 RFC 5322 的完整实现 —— 真正能否收信由发信结果决定。
    """
    if len(email) > MAX_EMAIL_LEN:
        return f"邮箱长度不能超过 {MAX_EMAIL_LEN} 个字符"
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain or "." not in domain or any(c.isspace() for c in email):
        return "邮箱格式不正确"
    if email.count("@") != 1 or domain.startswith(".") or domain.endswith(".") or ".." in email:
        return "邮箱格式不正确"
    return ""


def hash_code(email: str, purpose: str, code: str) -> str:
    """`HMAC-SHA256(secret, "email:purpose:code")` 十六进制（64 字符 = `code_hash CHAR(64)`）。

    为什么带 `purpose`：同一串 6 位码在 reset / bind 两种用途下哈希不同，
    即便库泄露也无法把两者互相当作有效码。
    """
    message = f"{email}:{purpose}:{code}".encode("utf-8")
    return hmac.new(HMAC_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _new_code() -> str:
    """6 位纯数字（左补 0）：`secrets` 而不是 `random` —— 验证码是凭证，不能用可预测的伪随机。"""
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


def issue(email: str, purpose: str, ip: str) -> tuple[CodeIssue, int]:
    """发一条验证码 → `(结果, 冷却秒数)`。

    顺序**刻意固定**（§3.3 / §3.4）：冷却 → 邮箱配额 → IP 配额 → 清垃圾 → 顶掉旧码 → 生成 →
    **落库** → 发信。落库在发信**之前**，#1 未注册邮箱才会走同一条路径、同样占掉 60 秒冷却 ——
    反枚举成立的前提就是这个顺序。

    `email` 由调用方用 `normalize_email` + `check_email` 处理过（格式错误在 router 就是 400，
    不落库）；这里仍再归一一次，防止直接调用方传入 `A@x.com` / `a@x.com` 各算一遍配额。
    """
    email = normalize_email(email)
    now = datetime.now().replace(microsecond=0)

    # 1) 60 秒重发冷却（不看是否消费：刚点过就点第二次必须被挡）
    last = codes.latest_created_at(email, purpose)
    if last is not None:
        elapsed = (now - last).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            return "cooldown", max(1, int(math.ceil(COOLDOWN_SECONDS - elapsed)))

    hour_ago = now - timedelta(hours=1)
    # 2) 每邮箱 5 条/小时
    if codes.count_recent(email, since=hour_ago) >= EMAIL_QUOTA_PER_HOUR:
        return "quota_email", 0
    # 3) 每 IP 20 条/小时（反代下取不到 IP 时 `ip` 为空 → 跳过，邮箱维度仍是主防线）
    if ip and codes.count_recent(ip=ip, since=hour_ago) >= IP_QUOTA_PER_HOUR:
        return "quota_ip", 0

    # 4) 清 24h 前的垃圾行（走 idx_code_created）
    codes.purge_expired(now - timedelta(hours=PURGE_BEFORE_HOURS))
    # 5) 顶掉旧码：同一 email+purpose 只允许一条有效码（用户可能连点 / 换设备重发）
    codes.invalidate_active(email, purpose)

    # 6) 生成 + **落库**（先落库，再决定要不要真发信 —— 顺序即反枚举）
    code = _new_code()
    code_id = codes.insert_code(
        email, purpose, hash_code(email, purpose, code), now + timedelta(minutes=CODE_TTL_MINUTES), ip
    )

    # 7) 只在「该发」的场合真发信：
    #    · `reset`（匿名找回密码）→ **只有邮箱已注册才发** —— 这是反枚举的核心：
    #      未注册也落库、也占冷却、也可能 429，但对外完全看不出差别；
    #    · `bind`（绑定邮箱，需登录）→ **一律发**。绑定的正是「还没被任何账号绑定的邮箱」，
    #      若也按「user 表存在才发」，个人中心就永远收不到验证码（设计 §3.4 那句
    #      「#1 / #3 统一：若邮箱在 user 表存在则发信」对 #3 不成立，见 03-impl §6 偏差 1）。
    #      「已被别的账号占用」这种拒绝在 router 里先用 409 挡掉。
    if purpose == "bind" or users.get_user_by_email(email):
        if not mailer.send_verify_code(email, code, purpose):
            # 发信失败：删掉刚插入那行 —— 用户可立即重试，不被自己的失败请求锁 60 秒
            codes.delete_code(code_id)
            return "send_failed", 0
    return "ok", COOLDOWN_SECONDS


def check_and_consume(email: str, purpose: str, code: str) -> CodeCheck:
    """校验并**消费**验证码 → 原因。`code` 的 6 位数字格式由 router 先判（→ 400 格式提示）。

    顺序：取最新未消费码 → 次数判 → 哈希比对（失败 +1，到顶整行作废）→ 条件 UPDATE 抢占。
    **绝不把失败吞成 `ok`**：每个分支都返回明确原因，router 再决定状态码。
    """
    email = normalize_email(email)
    row = codes.latest_active(email, purpose)
    if row is None:
        return "no_code"

    # 次数先判：已到上限的行（incr_attempts 已写 consumed_at）不该再被比对，
    # 否则「正确码」会在作废之后又"验过一次"，语义上说不清。
    if int(row.get("attempts") or 0) >= MAX_ATTEMPTS:
        return "too_many"

    if not hmac.compare_digest(str(row.get("code_hash") or ""), hash_code(email, purpose, code)):
        attempts = codes.incr_attempts(int(row["id"]))
        return "too_many" if attempts >= MAX_ATTEMPTS else "mismatch"

    # 条件 UPDATE 抢占：双击 / 重放时只有一个请求能拿到 True（单次有效）
    if not codes.consume(int(row["id"])):
        return "expired"
    # 成功消费后清掉同 email+purpose 其余未用码（多设备各收一条时，剩下的也一并作废）
    codes.invalidate_active(email, purpose)
    return "ok"
