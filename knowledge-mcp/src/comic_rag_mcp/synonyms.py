"""离线构建「用户说法 → 语料用词」的映射表。

## 为什么不用"块向量平均"那套

第一版拿「词出现过的块的向量平均」当词向量，结果所有词的余弦都在 **0.92~0.99** ——
文档块彼此太像（向量空间的各向异性），词与词之间根本分不开，邻居全是噪音。

而且它有个致命缺陷：**用户说的词可能整个语料里一次都没出现**（"提醒"），
压根不在词表里，算不出向量。

## 现在怎么做

1. 用**分词器**扫全库，得到语料词表（df ≥ 2 的才算，太罕见没法比）；
2. 把「语料词」和「种子词」（用户可能说的口语/同义词）都**当独立文本**用 embedding 编码；
3. 每个种子词找最近的 3 个语料词，低于阈值丢弃；
4. 产出候选表 + 人审用的 Markdown；
5. **人工确认后**写进 `synonyms.json`，查询扩展只读这份确认过的表。

词级向量的区分度明显好于块向量平均：实测「提醒 ↔ 通知」0.63、「收藏 ↔ 订阅」0.62。
"""
from __future__ import annotations

import json
import logging
import re

from . import config, tokenizer

_log = logging.getLogger(__name__)

MIN_TERM_LEN = 2
MAX_TERM_LEN = 12
MIN_DF = 2
MAX_DF = 400
MIN_SIMILARITY = 0.55
MAX_NEIGHBORS = 3

_CJK = re.compile(r"[\u4e00-\u9fff]")

_STOPWORDS = {
    "这个", "那个", "可以", "需要", "然后", "如果", "因为", "所以", "但是", "以及",
    "我们", "你们", "他们", "自己", "时候", "问题", "地方", "东西", "什么", "怎么",
    "一个", "没有", "就是", "不是", "还是", "这样", "那样", "这里", "那里", "现在",
}

#: 用户高频说法（种子）。这些词**不要求出现在语料里** —— 正是要把它翻译成语料用词。
SEED_TERMS: tuple[str, ...] = (
    # 提醒/通知
    "提醒", "通知", "告警", "推送", "消息", "站内信",
    # 更新/追更
    "更新", "新章节", "追更", "订阅", "收藏", "书架",
    # 定时/频率
    "定时", "频率", "多久", "周期", "调度", "cron", "间隔",
    # 采集
    "爬虫", "采集", "抓取", "源站", "适配器",
    # 鉴权
    "登录", "鉴权", "角色", "权限", "令牌", "token", "密码",
    # 部署
    "部署", "上线", "端口", "反向代理", "容器",
    # 数据
    "数据库", "表", "字段", "迁移", "索引",
    # 检索
    "检索", "搜索", "召回", "排序", "重排", "切分", "分块",
)


def _is_term(term: str) -> bool:
    if not (MIN_TERM_LEN <= len(term) <= MAX_TERM_LEN):
        return False
    if term in _STOPWORDS or term.isdigit():
        return False
    return bool(_CJK.search(term)) or bool(re.match(r"^[a-zA-Z][\w.:\-]*$", term))


def corpus_vocabulary() -> list[str]:
    """扫全库得到的词表（按文档频率过滤）。"""
    from . import indexer

    raw = indexer.get_store()._collection.get(include=["documents"])
    counts: dict[str, int] = {}
    for text in raw["documents"] or []:
        for term in set(tokenizer.tokens(text or "")):
            if _is_term(term):
                counts[term] = counts.get(term, 0) + 1
    return [term for term, df in counts.items() if MIN_DF <= df <= MAX_DF]


def _embed_terms(texts: list[str]) -> list[list[float]]:
    from comic_chat.rag.embeddings import get_embeddings

    return get_embeddings().embed_documents(texts)


def _llm_synonyms(seeds: tuple[str, ...]) -> dict[str, list[str]]:
    """让 LLM 给出每个词的同义说法（**不要求出现在语料里**，那正是要翻译的对象）。"""
    from .query_rewrite import _build_llm

    prompt = (
        "下面是一组中文技术词。请为每个词给出 5 个**同义的单词或说法**"
        "（中文，不要解释），尽量覆盖不同叫法。"
        "只输出 JSON 对象 {词: [同义词...]}：\n" + "、".join(seeds)
    )
    raw = str(_build_llm().invoke(prompt).content)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return {
        str(key): [str(v).strip() for v in values if str(v).strip()]
        for key, values in data.items()
        if isinstance(values, list)
    }


def build_candidates(seeds: tuple[str, ...] | None = None) -> dict:
    """生成候选：LLM 想同义词 → 只保留**语料里真实出现过**的那些。

    为什么不用 embedding 找近邻：实测词级向量在 bge-small 上被"字形"主导 ——
    「提醒 → 提示/提问/提供」「部署 → 部件/部已/部分」，全是噪音。
    中文小模型做单字词相似度不可靠；让 LLM 出候选、再用词表过滤，质量高得多。
    """
    seeds = tuple(seeds or SEED_TERMS)
    vocab = set(corpus_vocabulary())
    raw = _llm_synonyms(seeds)
    _log.info("LLM 给出 %d 个词的候选，语料词表 %d 个", len(raw), len(vocab))

    result: dict[str, dict] = {}
    for seed, terms in raw.items():
        neighbors = []
        for term in terms:
            if term == seed:
                continue
            # 扩展词最终会被分词后加进 BM25 查询，所以判断"有没有用"要看**分词结果**：
            # 只要切出来有语料里存在的词（且不是种子词自己），就算可用。
            usable = [
                token
                for token in tokenizer.tokens(term)
                if token in vocab and token != seed and token not in seed
            ]
            neighbors.append(
                {"term": term, "usable": usable, "in_corpus": bool(usable)}
            )
        if neighbors:
            result[seed] = {"neighbors": neighbors}
    return result


def write_artifacts(candidates: dict) -> dict:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    candidates_path = config.INDEX_DIR / "synonyms.candidates.json"
    review_path = config.INDEX_DIR / "synonyms.review.md"
    candidates_path.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 同义词候选（LLM 生成，**待人工确认**）",
        "",
        "> 确认后把 `词 → [语料词...]` 手工抄进 `synonyms.json`，查询扩展只读那份。",
        "> `语料里有` = 该词在语料词表中真实出现过（没出现的话，加进查询也命中不了任何块）。",
        "",
        "| 用户说法 | 同义说法 | 真正会加进查询的词 |",
        "|---|---|---|",
    ]
    for seed, info in sorted(candidates.items()):
        for neighbor in info["neighbors"]:
            usable = "、".join(neighbor["usable"]) or "—（不可用）"
            lines.append(f"| {seed} | {neighbor['term']} | {usable} |")
    lines += ["", "## 确认后写进 `synonyms.json`", "", "```json",
              '{ "提醒": ["通知"], "追更": ["更新"] }', "```", ""]
    review_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "seeds": len(candidates),
        "pairs": sum(len(info["neighbors"]) for info in candidates.values()),
        "in_corpus": sum(
            1 for info in candidates.values() for n in info["neighbors"] if n["in_corpus"]
        ),
        "candidates": str(candidates_path),
        "review": str(review_path),
    }


def load_approved() -> dict[str, list[str]]:
    """读取人工确认过的映射表；不存在/损坏都当空表。"""
    path = config.INDEX_DIR / "synonyms.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _log.warning("同义词表读取失败（%s）：%s", type(exc).__name__, exc)
        return {}
    return {
        str(key): [str(v) for v in values]
        for key, values in data.items()
        if isinstance(values, list)
    }


_TABLE: dict[str, list[str]] | None = None


def table() -> dict[str, list[str]]:
    """带缓存的映射表（进程内只读一次）。"""
    global _TABLE
    if _TABLE is None:
        _TABLE = load_approved()
    return _TABLE


def invalidate() -> None:
    """表被人工改过之后调用（下次读盘）。"""
    global _TABLE
    _TABLE = None


def expand(query: str, tokens: list[str] | None = None) -> list[str]:
    """把查询里的「用户说法」扩成「语料用词」，返回**额外要加的词**。

    只加进字面路：语义路加词等于改问题（容易跑偏），字面路加词只是多几个精确匹配机会。
    """
    if not config.SYNONYM_EXPAND:
        return []
    mapping = table()
    if not mapping:
        return []
    from . import tokenizer

    source = tokens if tokens is not None else tokenizer.tokens(query or "")
    extra: list[str] = []
    for token in source:
        for term in mapping.get(token, []):
            if term and term not in source and term not in extra:
                extra.append(term)
    return extra[: config.SYNONYM_EXPAND_TERMS]
