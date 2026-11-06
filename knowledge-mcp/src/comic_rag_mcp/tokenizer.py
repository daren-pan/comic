"""分词器：把一句话切成词项（BM25 / 标题加权共用）。

## 为什么单独一层

同一个项目里，分词会被两个地方用：**词面加权**（`retriever` 的 heading/body boost）和
**BM25 召回**。两边必须用同一个切法，否则「加权说命中、BM25 说没命中」自相矛盾。

## 两种后端

| 后端 | 切法 | 依赖 | 谁适合 |
|---|---|---|---|
| `jieba` | 词典 + DAG + 最大概率路径 + HMM 未登录词 | `pip install jieba`（约 20MB） | 领域术语能进用户词典，词项干净、数量少 |
| `bigram` | 英文/数字整词 + 中文两字滑窗 | **零依赖**（只用标准库） | 兜底；不需要词典，但词项多、含跨词边界的碎片 |

选择由 `COMIC_KB_TOKENIZER` 决定：

- `auto`（默认）：装了 jieba 就用 jieba，否则用 bigram；
- `jieba`：强制 jieba，**装不上直接报错**（避免"以为换成了 jieba，其实还在用 bigram"）；
- `bigram`：强制 bigram（回退 / 对照实验）。

## ⚠️ 换分词器 = 换打分刻度

BM25 的分数是「每个词的稀有度 × 词频 × 长度折扣」求和，分词一变：
加数个数、词频口径、文档长度基准、IDF 分布**全部改变**。
所以换后端之后必须**重标阈值**、重跑评估集（`EVAL.md`），否则会出现
「代码改了、效果说不清」——和换 embedding 模型是同一类问题。

## 用户词典

`terms.txt` 放项目专有词（判重 / 图床 / 管理台 …）。jieba 默认词典不知道这些词，
不加载用户词典时它们会被切碎，反而比 bigram 更差。
"""
from __future__ import annotations

import os
import re
import warnings
from functools import lru_cache
from pathlib import Path

from . import config

_ENV = "COMIC_KB_TOKENIZER"
_VALID = ("auto", "jieba", "bigram", "mixed")

#: 用户词典：一行一个词（可带 词频 词性，jieba 格式）。
TERMS_FILE = Path(__file__).resolve().parent / "terms.txt"

_CN_RE = re.compile(r"[\u4e00-\u9fff]+")
_EN_RE = re.compile(r"[a-z0-9_]+")

#: 英文/数字标识符：字母开头，允许下划线、点、连字符连接（`require_admin`、`X-Service-Token`、
#: `mysql_schema.sql`）。**这正是 bigram 与 jieba 各自搞砸的那一类**：前者当整词、后者拆碎。
_IDENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]*")
_PART_SPLIT = re.compile(r"[._\-]+")


def chosen() -> str:
    """`COMIC_KB_TOKENIZER` 的值（非法值按 `auto` 处理，不抛错）。"""
    value = (os.environ.get(_ENV, "") or "auto").strip().lower()
    return value if value in _VALID else "auto"


@lru_cache(maxsize=1)
def _jieba_module():
    """加载 jieba 并挂用户词典；不可用时返回 `None`。

    ⚠️ **必须懒加载**：`import jieba` 会建前缀词典（约 1 秒、几十 MB 内存）。
    放在模块导入期会拖慢 MCP 进程启动，而检索可能一整天都不发生。
    """
    try:
        # jieba 0.42 的正则用了非 raw 字符串，Python 3.13 会打两条 SyntaxWarning；
        # 压掉它们，避免每次初始化都在 MCP 日志里刷无关警告。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import jieba
    except Exception:  # noqa: BLE001 —— 缺包 / 词典损坏都按"不可用"处理
        return None

    # 缓存目录改到项目内：受限会话（DSH 沙箱）里系统临时目录不可写，
    # jieba 默认把 `jieba.cache` 写到那里，写失败会反复重建前缀词典。
    cache_dir = config.INDEX_DIR.parent / "tmp"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        jieba.dt.cache_file = str(cache_dir / "jieba.cache")
    except Exception:  # noqa: BLE001 —— 缓存不可写只是慢一点，不影响正确性
        pass

    if TERMS_FILE.is_file():
        # 自己解析而不是 `jieba.load_userdict(path)`：后者对不同版本的注释/空行容错不一致，
        # 而且它不告诉你哪一行坏了。这里显式解析，坏行直接跳过，不会污染词典。
        for line in TERMS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            word = parts[0]
            freq = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            tag = parts[2] if len(parts) > 2 else None
            try:
                jieba.add_word(word, freq=freq, tag=tag)
            except Exception:  # noqa: BLE001 —— 单个坏词不影响整部词典
                continue
    return jieba


def available() -> bool:
    """当前是否真的会走词典分词（`jieba` / `mixed` 都需要 jieba）。"""
    return backend() in {"jieba", "mixed"}


def backend() -> str:
    """实际生效的后端名（`jieba` / `bigram` / `mixed`）。

    `jieba` / `mixed` 模式下缺包会**抛错**：显式要求了却不能提供，静默降级会让人对着
    "换了分词器效果没变"排查半天。
    """
    mode = chosen()
    if mode == "bigram":
        return "bigram"
    has_jieba = _jieba_module() is not None
    if not has_jieba and mode in {"jieba", "mixed"}:
        raise RuntimeError(
            f"COMIC_KB_TOKENIZER={mode} 但没装 jieba。请运行："
            f"crawler-service/.venv/Scripts/python.exe -m pip install jieba"
            f"（或把该环境变量设为 bigram 回退）"
        )
    if mode == "mixed":
        return "mixed"
    if mode == "jieba":
        return "jieba"
    # auto：装了 jieba 就走 mixed —— 它是 jieba 的超集（中文切法相同、英文标识符更好），
    # 没有理由再回到纯 jieba。bigram 只作为零依赖兜底。
    return "mixed" if has_jieba else "bigram"


def bigram_tokens(text: str) -> list[str]:
    """英文/数字整词 + 中文两字滑窗；长度 < 2 的碎片丢弃。

    这就是项目原来的做法（`retriever._lexical_tokens`），现在搬到这里统一管理。
    """
    lowered = (text or "").lower()
    tokens = _EN_RE.findall(lowered)
    for run in _CN_RE.findall(lowered):
        if len(run) <= 2:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return [t for t in tokens if len(t) >= 2]


def jieba_tokens(text: str) -> list[str]:
    """词典分词（精确模式），过滤空白与单字符。

    用 `lcut` 而不是 `lcut_for_search`：后者会把长词再拆细成子词，
    召回高但噪音大 —— BM25 自己就靠词频和 IDF 平衡，不需要再叠一层。
    """
    module = _jieba_module()
    if module is None:  # 理论上 backend() 已拦过，防御性处理
        return bigram_tokens(text)
    return [t.strip().lower() for t in module.lcut(text or "") if len(t.strip()) >= 2]


def mixed_tokens(text: str) -> list[str]:
    """**中英分流**：标识符整体保留（+ 部件展开），中文段交给 jieba。

    | 输入 | 输出 |
    |---|---|
    | `X-Service-Token 怎么配` | `x-service-token`, `service`, `token`, `怎么` |
    | `require_admin 是哪个装饰器` | `require_admin`, `require`, `admin`, `哪个`, `装饰` |

    ## 为什么"整体 + 部件"都留

    - **整体**（`require_admin`）：用户原样粘贴标识符时，全库罕见 → IDF 极高 → 精确命中排第一；
    - **部件**（`require` / `admin`）：用户只记得一半、或文档写作 `admin` 时，召回不至于丢失。

    只留整体会漏召回，只留部件会丢精度 —— 这是 bigram 与 jieba 各自的单一取舍，
    分流后两个都能拿到。

    ⚠️ 文档侧与查询侧**必须用同一个后端**，否则词对不上、分数全错。
    """
    module = _jieba_module()
    if module is None:  # 理论上 backend() 已拦过，防御性处理
        return bigram_tokens(text)

    def cut_chinese(segment: str) -> list[str]:
        return [
            t.strip().lower() for t in module.lcut(segment) if len(t.strip()) >= 2
        ]

    out: list[str] = []
    pos = 0
    for match in _IDENT_RE.finditer(text or ""):
        whole = match.group(0).rstrip("._-")     # 句末标点别带进词里
        if len(whole) < 2:                        # 单个字母没有检索价值
            continue
        start = match.start()
        if start > pos:
            out.extend(cut_chinese(text[pos:start]))
        lowered = whole.lower()
        out.append(lowered)
        # 部件展开：`comic_jwt_secret` → comic / jwt / secret
        out.extend(
            part
            for part in _PART_SPLIT.split(lowered)
            if len(part) >= 2 and part != lowered
        )
        pos = start + len(whole)
    if pos < len(text or ""):
        out.extend(cut_chinese(text[pos:]))
    return out


def tokens(text: str) -> list[str]:
    """按当前后端切词（**保留重复**，词频信息不能丢 —— BM25 要用 tf）。"""
    current = backend()
    if current == "mixed":
        return mixed_tokens(text)
    if current == "jieba":
        return jieba_tokens(text)
    return bigram_tokens(text)


def unique_tokens(text: str) -> list[str]:
    """去重后的词项（给"命中比例"这类加权用：同一词重复出现不重复计分）。"""
    return list(dict.fromkeys(tokens(text)))


def describe() -> dict:
    """自检信息（`doctor` / `knowledge_stats` 展示用）。"""
    return {
        "chosen": chosen(),
        "backend": backend(),
        "userDict": str(TERMS_FILE) if TERMS_FILE.is_file() else "",
    }
