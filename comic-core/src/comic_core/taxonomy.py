"""标签归一化：把各源五花八门的标签名映射到统一的中文规范名。

**为什么需要**：不同源站各说各话 —— mangadex 全英文（Comedy / Romance / Slice of Life）、
zaimanhua 用中文（搞笑 / 爱情 / 校园）、weebcentral 又是英文，甚至混入日文（ゆり）；
`copymanga` 还是**繁体**站（`格鬥` / `職場`）。
不做归一化时，同一个概念在库里是**多行互不相干的标签**（Comedy 30 部、搞笑 9 部各算各的），
既看不出真实规模，也无法按标签筛选。

**做法（最小版）**：一张「规范名 -> 同义词」对照表（`data/tag_synonyms.json`），
**在入库写入标签时**查一次 —— 命中就换成规范名；未命中**回落简体写法**
（只做字形转换，把 `靈異`/`灵异` 这类收成一行；不翻译、不丢词）。
因为统一发生在写入侧，所以搜索、排行、详情页、分类页自动一致，查询侧无需任何翻译逻辑。

**繁简为什么要在这里**：词表是简体词表，繁体站来的 `格鬥` 直接查表查不到（写了 `格斗`），
同一概念会分裂成两行；折叠字形后 `格鬥`→`格斗`→命中 `动作`。

**边界（刻意不做的事）**：
- 不做机器翻译 —— 错译一旦入库就被固化成"规范名"，比保留原文更难收拾；
  繁转简是**确定性字形映射**（一简对多繁的反向是唯一的），不属于翻译；
  刻意用 `zh-hans` 而不是 `zh-cn`（后者会把 `硬碟` 改成 `硬盘`、`雷射` 改成 `激光`，
  那是词汇改译，会把源站写法改掉）；
- 形态类（`Web Comic` / `Full Color` / `Long Strip` / `Oneshot`）、更新季（`2026春`）、
  敏感标签（`Loli` / `Shota` / `Incest` / `Sexual Violence`）**一律不映射**，原样保留；
- 只合并**明确同义**的词，模棱两可的不并。
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import zhconv

# 词表与模块同包（`data/tag_synonyms.json`），打包时随 `src/comic_crawler/` 一起带上
SYNONYMS_PATH = Path(__file__).with_name("data") / "tag_synonyms.json"

# 归一化时抹掉的差异字符：空白 / 连字符 / 下划线 / 撇号 / 句点 / 斜杠 / 间隔号
_NOISE_RE = re.compile(r"[\s\-_'\u2019./·|]+")


def _to_simplified(text: str) -> str:
    """繁体字形 -> 简体字形（`zh-hans`：只换字形，不做词汇改译）。

    与 `fingerprint._to_simplified` 是**同一件事的两处调用**：L0 通用内核约定零内部依赖
    （`tests/test_layering.py` 断言），所以各自 import 外部库，不抽公共模块。
    """
    return zhconv.convert(text, "zh-hans") if text else text


def normalize_tag(name: str) -> str:
    """标签名的**归一化形式**（只用于查表，不用于展示）。

    NFKC 折叠（全角字母数字 -> 半角）+ 繁转简 + 去差异字符 + 小写，因此
    `Sci-Fi` / `Sci Fi` / `scifi` / `ＳＣＩ－ＦＩ` 归一后是同一个键，
    `格鬥` 与 `格斗` 也是同一个键。
    """
    s = unicodedata.normalize("NFKC", name or "").strip().lower()
    s = _to_simplified(s)
    return _NOISE_RE.sub("", s)


@lru_cache(maxsize=1)
def _index() -> dict[str, str]:
    """反向索引 `{归一化写法: 规范名}`；规范名自身也指向自己（保证幂等）。"""
    raw = json.loads(SYNONYMS_PATH.read_text(encoding="utf-8"))
    idx: dict[str, str] = {}
    for canonical, aliases in raw.items():
        for name in (canonical, *(aliases or [])):
            key = normalize_tag(name)
            if key:
                idx.setdefault(key, canonical)   # 先到先得：规范名与别名冲突时以先声明者为准
    return idx


def canonical_tag(name: str) -> str:
    """源站标签名 -> 规范名；**未命中返回简体写法**（字形归一，不猜同义、不丢词）。"""
    text = (name or "").strip()
    if not text:
        return ""
    return _index().get(normalize_tag(text)) or _to_simplified(text)


def is_known(name: str) -> bool:
    """该写法是否在词表内（供测试与运维排查用）。"""
    return normalize_tag(name) in _index()
