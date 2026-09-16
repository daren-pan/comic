"""标题归一化与指纹生成 —— 跨源去重的核心。

对应架构方案 §2.3 去重策略：
- 站内唯一：source + source_comic_id（由存储层唯一约束保证）；
- 跨站合并：归一化标题 + 作者 生成 fingerprint，命中即为同一部漫画。

归一化处理顺序：小写 → 全角转半角 → **繁转简** → 去空白 → 去括号注释（如"海贼王（重置版）"）。

**繁转简为什么放进指纹**：同一部作品在不同源站可能一繁一简 —— `copymanga` 是 zh-hant 站，
《电锯人》在那里叫「電鋸人」。不折叠就会把同一部作品当**两部**，跨源合并直接失效。
折叠只做**字形**（`zh-hans`），不做词汇改译 —— 那是翻译，不是归一。
"""

from __future__ import annotations

import hashlib
import re

import zhconv

_FULLWIDTH_MAP = {
    ord(c): ord(c) - 0xFEE0
    for c in "！＂＃＄％＆＇（）＊＋，－．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～"
}

# 中英文括号内的注释内容，如（重置版）、[新装版]、【高清】
_BRACKET_RE = re.compile(r"[（(【\[][^（（）【\]\[\]]*[）)】\]]")


def _to_halfwidth(text: str) -> str:
    return text.translate(_FULLWIDTH_MAP)


def _to_simplified(text: str) -> str:
    """繁体字形 -> 简体字形（`zh-hans`：只换字形，不做港台/繁中词汇改译）。

    与 `taxonomy._to_simplified` 是**同一件事的两处调用**：L0 通用内核约定零内部依赖
    （`tests/test_layering.py` 断言），所以各自 import 外部库，不抽公共模块。
    """
    return zhconv.convert(text, "zh-hans") if text else text


def normalize_title(title: str) -> str:
    """归一化标题：小写、半角、繁转简、去空白、去括号注释。"""
    t = (title or "").strip().lower()
    t = _to_halfwidth(t)
    t = _to_simplified(t)
    t = re.sub(r"\s+", "", t)
    t = _BRACKET_RE.sub("", t)
    return t.strip()


def normalize_author(author: str) -> str:
    """归一化作者：小写 + 半角 + 繁转简 + 去空白。"""
    a = (author or "").strip().lower()
    a = _to_halfwidth(a)
    return _to_simplified(a)


def build_fingerprint(title: str, author: str = "") -> str:
    """跨站作品指纹：normalize_title + normalize_author 的 sha1 前 16 位。

    示例：两个源站分别写作「海贼王」「海贼王（重置版）」、作者一致时，
    fingerprint 相同 → 调度层判定为同一部作品，只保留一条记录。
    繁简差异同理：「電鋸人」与「电锯人」（作者一致）命中同一指纹。
    """
    raw = f"{normalize_title(title)}|{normalize_author(author)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
