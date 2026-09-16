"""标题归一化与指纹生成 —— **"可能是同一部作品"的观测标记**。

对应架构方案 §2.3：
- **判重只按 `source + source_comic_id`**（同源精确判重，由存储层唯一约束保证）；
- `fingerprint`（归一化标题 + 作者）**不再参与合并** —— 用户 2026-09-16 决策：
  不同源、不同译本各自成行、各自记章节进度（合并反而丢信息），所以这里算出来的指纹
  只用于标注"这几行可能是同一部作品"，供运维查重与人工判断。

归一化处理顺序：小写 → 全角转半角 → 去空白 → 去括号注释（如"海贼王（重置版）"）。

⚠️ 刻意**不做繁转简**：繁体（港台译本）与简体（大陆译本）是两个译本，章节进度往往不同，
折叠会把它们并成一行、丢掉其中一版的章节。**标签侧（`taxonomy`）仍然折叠繁简** ——
那是"概念归一"，与"作品是不是同一部"无关。
"""

from __future__ import annotations

import hashlib
import re

_FULLWIDTH_MAP = {
    ord(c): ord(c) - 0xFEE0
    for c in "！＂＃＄％＆＇（）＊＋，－．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～"
}

# 中英文括号内的注释内容，如（重置版）、[新装版]、【高清】
_BRACKET_RE = re.compile(r"[（(【\[][^（（）【\]\[\]]*[）)】\]]")


def _to_halfwidth(text: str) -> str:
    return text.translate(_FULLWIDTH_MAP)


def normalize_title(title: str) -> str:
    """归一化标题：小写、半角、去空白、去括号注释。"""
    t = (title or "").strip().lower()
    t = _to_halfwidth(t)
    t = re.sub(r"\s+", "", t)
    t = _BRACKET_RE.sub("", t)
    return t.strip()


def normalize_author(author: str) -> str:
    """归一化作者：小写 + 半角 + 去空白。"""
    a = (author or "").strip().lower()
    return _to_halfwidth(a)


def build_fingerprint(title: str, author: str = "") -> str:
    """作品指纹：normalize_title + normalize_author 的 sha1 前 16 位。

    **不用于判重**（判重看 `(source, source_comic_id)`）。用途是"同标题同作者"的
    跨源观测：两个源分别写作「海贼王」「海贼王（重置版）」、作者一致时指纹相同，
    可据此发现可能的重复行（繁简/中英写法不同则指纹不同，刻意如此）。
    """
    raw = f"{normalize_title(title)}|{normalize_author(author)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
