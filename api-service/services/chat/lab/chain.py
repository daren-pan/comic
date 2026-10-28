"""RAG 第五~七阶段：检索 → 增强（拼 prompt）→ 生成。

## 为什么拆成 `search()` 和 `ask()` 两个函数

`search()` 只做检索、不碰模型，是排查 RAG 问题的**唯一正确入口**：

| 现象 | 问题在哪 | 换模型有用吗 |
|---|---|---|
| `search` 命中的不是该命中的 | 切分 / 向量化 / `k` 值 | ❌ 完全没用 |
| `search` 命中对了，但答案答歪 | prompt 组装 / 生成模型 | ✅ 可能有用 |

大多数人遇到「答得不对」的第一反应是换个更贵的模型 —— 但十次里有七次问题出在检索那一段。
把这两步拆开，能立刻省掉这种无效尝试。

## 检索分数怎么读

`similarity_search_with_relevance_scores()` 返回 **0~1 的相关度，越大越像**
（Chroma 内部把余弦距离换算成 `1 - distance/2`，所以余弦距离 0 → 1.0，距离 2 → 0.0）。

⚠️ 别和 `similarity_search_with_score()` 搞混 —— 那个返回的是**距离，越小越像**。
两者方向相反，用错会把最不相关的结果当成最佳匹配。

经验阈值（`text-embedding-v4` 这类模型）：

| 分数 | 含义 |
|---|---|
| > 0.75 | 基本可以确信是同一件事 |
| 0.55 ~ 0.75 | 相关，但可能只是主题沾边 |
| < 0.55 | 大概率无关，塞进 prompt 只会干扰模型 |

hash 占位后端算出来的分数**没有这个含义**（它是字面重合度），所以响应里会带
`backend` 字段：看到 `hash` 就别按上面的阈值判断。
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from . import settings
from .index import get_store

#: 系统提示词。三条硬约束缺一不可 ——
#: ① 只依据资料回答：否则模型会拿训练数据里的「常识」编造站内不存在的功能；
#: ② 资料没有就说没有：编一个不存在的漫画名比说「不知道」伤害大得多；
#: ③ 不聊站外话题：这个站是漫画站，不加限制等于给所有人一个免费 ChatGPT。
_SYSTEM_TEMPLATE = """你是「聚漫画」网站的客服助手「小聚」。请严格按下面的规则回答：

1. 只依据【参考资料】里的内容回答。资料里没有的信息，直接说「站内暂时没有这方面的信息」，
   并建议用户把漫画名和章节号反馈给管理员 —— **不要提「转人工」「联系客服」「点某个按钮」**，
   界面上没有这些入口，说了用户找不到。
2. 绝不编造漫画名称、章节号、按钮名称或功能。资料里没有的作品，就是**没有收录**。
3. 用简体中文回答，控制在 3 句话以内；需要列举时最多 3 条，用「-」开头。
4. 不要提及「参考资料」「知识库」「向量」「embedding」这类内部概念，也不要说「根据资料显示」。
5. 与漫画、本站功能无关的问题（闲聊、写代码、时政、成人内容），礼貌拒绝并把话题引回漫画。

【参考资料】
{context}"""


def _format_context(docs: list[tuple[Document, float]]) -> str:
    """把检索结果拼成给模型读的上下文。

    ⚠️ 每条都带一个**来源标记**（`[FAQ]` / `[漫画#12]`），这有两个作用：
    ① 模型能分辨「这是通用说明」还是「这是某部作品的数据」，回答时不会混在一起；
    ② 调试时能一眼看出模型引用的是哪条 —— 答错了马上定位到是检索的问题还是生成的问题。

    这里**只放正文**，不放 `metadata` 里的其它字段（尤其不能放采集来源，见 `documents.py`）。
    """
    if not docs:
        return "（没有检索到任何相关资料）"

    blocks: list[str] = []
    for doc, _score in docs:
        kind = doc.metadata.get("kind", "")
        if kind == "faq":
            label = f"[FAQ] {doc.metadata.get('title', '')}"
        elif kind == "comic":
            label = f"[漫画#{doc.metadata.get('comic_id')}]"
        else:
            label = "[资料]"
        blocks.append(f"{label}\n{doc.page_content.strip()}")
    return "\n\n".join(blocks)


def _hit(doc: Document, score: float) -> dict:
    """单条检索结果 → 接口/CLI 展示用的精简结构。

    `preview` 只截前 80 字：完整正文可能有几百字，界面上看的是「命中了哪一条」，
    不是「这条的全文」（要看全文去点开）。截断也能避免接口响应过大。
    """
    text = doc.page_content.strip().replace("\n", " ")
    return {
        "kind": doc.metadata.get("kind", ""),
        "title": doc.metadata.get("title", ""),
        "comicId": doc.metadata.get("comic_id"),
        "score": round(float(score), 4),
        "preview": text[:80] + ("…" if len(text) > 80 else ""),
    }


def _default_min_score() -> float | None:
    """默认相似度阈值。**这个值是实测标定出来的，不是拍脑袋定的。**

    `hash` 后端**不做过滤**：它算的是字面重合度，分数没有 0~1 的语义含义，拿语义阈值去卡
    只会误伤。

    语义后端用 **0.5**。标定依据（2026-10-28，bge-small-zh-v1.5，本库 64 条实测）：

    | 提问 | 正确项分数 | 无关项分数 |
    |---|---|---|
    | 图裂了怎么办 | 0.522（图片加载不出来） | 0.392 ~ 0.431 |
    | 忘了密码怎么找回 | 0.730 / 0.707 | 0.455 ~ 0.510 |
    | 会员要多少钱 | 0.531 | 0.413 ~ 0.419 |
    | 上次看到哪了 | 0.551 | 0.464 ~ 0.484 |
    | **有没有海贼王**（站里没有） | — | 0.412 ~ 0.450 |

    0.5 正好卡在「噪音之上、正确项之下」。**最后一行是最关键的用例**：站内根本没有的作品，
    阈值会把它全部挡掉，上下文变成「没有检索到任何相关资料」，模型于是老实回答「暂无收录」，
    而不是抓着一条 0.45 的无关漫画简介硬编。

    ⚠️ 换 embedding 模型后**必须重新标定**：不同模型的分数分布不一样（云端模型通常分得更开，
    同义句能到 0.8+）。0.5 对 bge-small-zh 是合适的，对别的模型只是起点。
    """
    return None if settings.embedding_backend() == "hash" else 0.5


def _retrieve(
    question: str, k: int | None, kind: str | None, min_score: float | None
) -> list[tuple[Document, float]]:
    """向量检索 + 阈值过滤（`search()` 和 `ask()` 共用，避免两处各查一遍库）。

    要过滤时先多取几倍候选（`k * 3`）再筛：Chroma 的 metadata 过滤和我们的分数过滤都发生在
    「取回 k 条之后」，只查 `k` 条会被筛到只剩一两条，达不到「给模型 4 段参考」的目的。
    """
    store = get_store()
    where = {"kind": kind} if kind else None
    top_k = k or settings.TOP_K
    fetch_k = top_k * 3 if min_score is not None else top_k

    pairs = store.similarity_search_with_relevance_scores(
        question, k=fetch_k, filter=where
    )
    if min_score is not None:
        pairs = [(d, s) for d, s in pairs if s >= min_score]
    return pairs[:top_k]


def search(
    question: str, k: int | None = None, kind: str | None = None, min_score: float | None = -1.0
) -> dict:
    """只做检索（不调生成模型）—— 排查问题的入口。

    `kind` 可以限定数据源（`faq` / `comic`），演示的是 Chroma 的 **metadata 过滤**：
    过滤发生在向量检索**之后**（先按相似度取候选，再按 metadata 筛），所以 `k` 太小时
    可能筛完一条不剩。要按类型分别取，就把 `k` 调大一点。

    `min_score` 传 -1 表示「用后端默认值」（见 `_default_min_score()`）；
    传 `None` 表示明确不过滤 —— 排查时想看全部候选（包括低分噪音）就传 `None`。
    """
    started = time.perf_counter()
    threshold = _default_min_score() if min_score == -1.0 else min_score
    pairs = _retrieve(question, k, kind, threshold)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    return {
        "question": question,
        "backend": settings.embedding_backend(),
        "k": k or settings.TOP_K,
        "minScore": threshold,
        "hits": [_hit(d, s) for d, s in pairs],
        "elapsedMs": elapsed_ms,
        "warning": (
            "当前用的是 hash 占位向量（不是语义模型），命中结果只反映字面重合度，不能代表真实效果"
            if settings.embedding_backend() == "hash"
            else None
        ),
    }


def ask(question: str, k: int | None = None, kind: str | None = None, with_context: bool = True) -> dict:
    """完整问答：检索 → 拼 prompt → 调模型 → 解析。

    链路用 **LCEL**（LangChain Expression Language）写：

    ```python
    chain = prompt | llm | StrOutputParser()
    answer = chain.invoke({"context": ..., "question": ...})
    ```

    `|` 不是语法糖，是真的把三段「可运行对象」串成一条管道：前一段的输出自动成为后一段
    的输入。想加多轮对话时，只在 `from_messages` 里插一个
    `MessagesPlaceholder("history")`，再 `invoke({"history": [...], ...})` 即可 ——
    管道本身一行都不用改。这是 LCEL 相对旧版 `LLMChain` 最实用的地方。
    """
    if not settings.llm_ready():
        raise RuntimeError(
            "对话模型没有配置：请设置环境变量 COMIC_LLM_API_KEY（DeepSeek 的 key），"
            "再重试。只想看检索效果的话用 search 子命令，它不需要 key。"
        )

    started = time.perf_counter()
    retrieve_started = time.perf_counter()
    pairs = _retrieve(question, k, kind, _default_min_score())
    retrieve_ms = int((time.perf_counter() - retrieve_started) * 1000)
    context = _format_context(pairs)

    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        temperature=settings.LLM_TEMPERATURE,
        timeout=30,
        max_retries=1,
        # OpenCode Go 网关**强制**要这两个头：缺 session 头直接 400 `MissingSessionID`，
        # 用通用 SDK 的 UA 会被判为可疑流量。换别的厂商时这两个头会被忽略，不碍事。
        # 一次 ask 生成一个 session id（一次提问算一次会话）。
        default_headers={
            settings.LLM_SESSION_HEADER: str(uuid.uuid4()),
            "User-Agent": settings.LLM_USER_AGENT,
        },
    )
    prompt = ChatPromptTemplate.from_messages(
        [("system", _SYSTEM_TEMPLATE), ("human", "{question}")]
    )
    chain = prompt | llm | StrOutputParser()

    llm_started = time.perf_counter()
    answer = chain.invoke({"context": context, "question": question}).strip()
    llm_ms = int((time.perf_counter() - llm_started) * 1000)

    total_ms = int((time.perf_counter() - started) * 1000)
    result = {
        "answer": answer,
        "hits": [_hit(d, s) for d, s in pairs],
        "backend": settings.embedding_backend(),
        "model": settings.LLM_MODEL,
        "elapsedMs": {"retrieve": retrieve_ms, "llm": llm_ms, "total": total_ms},
        "warning": (
            "当前用的是 hash 占位向量（不是语义模型），检索结果只反映字面重合度，答案质量不能代表真实效果"
            if settings.embedding_backend() == "hash"
            else None
        ),
        "askedAt": datetime.now().isoformat(timespec="seconds"),
    }
    if with_context:
        # 把最终发给模型的上下文原样返回 —— 学习时最该看的就是这一段：
        # 「模型到底看到了什么」决定了它会怎么答。
        result["context"] = context
    return result
