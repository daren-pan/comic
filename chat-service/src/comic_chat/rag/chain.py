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
from functools import lru_cache
from datetime import datetime

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from . import settings, structured
from .documents import fact_to_document
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


#: 多轮改写提示词。**不枚举句式** —— 只描述目标，模型自己判断「那取消呢」该改成什么。
#: 实测覆盖（2026-10-30）：
#:   那取消呢          → 如何取消收藏漫画？
#:   那封面呢          → 封面加载不出来怎么办
#:   没绑定邮箱呢      → 忘记密码且没有绑定邮箱时怎么找回密码
#:   手机上也行吗      → 怎么在手机上收藏漫画？
#:   怎么收藏漫画（无历史）→ 原样返回
_REWRITE_TEMPLATE = """根据对话历史，把用户最后一句改写成一个独立、完整、可检索的问题。
只输出改写后的问题，不要任何解释或引号。如果最后一句本身已经完整，原样返回。

历史：
{history}

最后一句：{question}"""


def _format_context(docs: list[tuple[Document, float]]) -> str:
    """把检索结果拼成给模型读的上下文。

    ⚠️ 每条都带一个**来源标记**（`[FAQ]` / `[漫画#12]`），这有两个作用：
    ① 模型能分辨「这是通用说明」还是「这是某部作品的数据」，回答时不会混在一起；
    ② 调试时能一眼看出模型引用的是哪条 —— 答错了马上定位到是检索的问题还是生成的问题。

    ⚠️ **优先取 `metadata["display"]`**（完整原文），而不是 `page_content`：
    后者已经是「标题 + 首句」的检索专用短文本（见 `documents.py`），拿它回答会把
    后半段结论丢掉（比如「没绑定邮箱的账号需要找管理员重置」就在第二句）。
    `or doc.page_content` 是兜底 —— 旧格式的索引、或别处传进来的 Document 没有 display。

    这里**只放正文**，不放 `metadata` 里的其它字段（尤其不能放采集来源）。
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
        body = (doc.metadata.get("display") or doc.page_content).strip()
        blocks.append(f"{label}\n{body}")
    return "\n\n".join(blocks)


def _hit(doc: Document, score: float) -> dict:
    """单条检索结果 → 接口/CLI 展示用的精简结构。

    `preview` 只截前 80 字：完整正文可能有几百字，界面上看的是「命中了哪一条」，
    不是「这条的全文」（要看全文去点开）。截断也能避免接口响应过大。

    ⚠️ 同样要取 `metadata["display"]`：`page_content` 现在只有「标题 + 首句」约 40 字，
    拿它做预览的话，界面上的「参考」摘要会凭空缩水一半。
    """
    text = (doc.metadata.get("display") or doc.page_content).strip().replace("\n", " ")
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
    """**双路召回** + 阈值过滤（`search()` 和 `ask()` 共用）。

    | 路 | 做法 | 擅长 |
    |---|---|---|
    | ① 结构化（`structured.match`） | 书名/作者/标签做反向包含 | 「有没有科幻的」这类**集合筛选**、用户报确切书名/作者名 |
    | ② 向量（Chroma） | 语义最近邻 | 「图裂了」「登不上去」这类**口语和错字** |

    两路是互补而非替代：结构化对 FAQ 完全无能（用户问法千变万化），向量对「查字段」
    完全无能（「科幻」是抽象标签，相似度算不出来）。缺哪条都会有一类问题答不好。

    合并规则：
    - **结构化优先**：用户报了确切书名时不该被向量打个 0.79 排在别的作品后面，
      所以按分数直接混排（结构化的 1.00/0.95/0.85 天然高于向量常态区间）。
    - **按 comic_id 去重**：同一部作品两路都命中时只留分数高的那条。
    - **结构化不过阈值**：它的分数是固定档位、没有「不够像」的中间态，命中即可信。
      阈值只作用在向量结果上。

    `kind="faq"` 时跳过结构化 —— 那一路只产出漫画，没有意义。

    要过滤时先多取几倍候选（`k * 3`）再筛：Chroma 的 metadata 过滤和分数过滤都发生在
    「取回 k 条之后」，只查 `k` 条会被筛到只剩一两条，达不到「给模型 4 段参考」的目的。
    """
    top_k = k or settings.TOP_K

    structured_pairs: list[tuple[Document, float]] = []
    if kind != "faq":
        structured_pairs = [
            (fact_to_document(fact), score)
            for fact, score, _reason in structured.match(question)
        ]

    store = get_store()
    where = {"kind": kind} if kind else None
    fetch_k = top_k * 3 if min_score is not None else top_k
    vector_pairs = store.similarity_search_with_relevance_scores(
        question, k=fetch_k, filter=where
    )
    if min_score is not None:
        vector_pairs = [(d, s) for d, s in vector_pairs if s >= min_score]

    # 合并去重：结构化的条目先占位，向量结果只补它没覆盖到的作品。
    merged: list[tuple[Document, float]] = []
    seen: set[object] = set()
    for doc, score in structured_pairs + vector_pairs:
        key = doc.metadata.get("comic_id") or doc.metadata.get("title")
        if key in seen:
            continue
        seen.add(key)
        merged.append((doc, score))
        if len(merged) >= top_k:
            break
    return merged


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


@lru_cache(maxsize=4)
def _build_llm(
    temperature: float = settings.LLM_TEMPERATURE, disable_thinking: bool = False
):
    """建对话模型客户端（生成与改写共用，温度和思考模式不同）。

    ⚠️ **必须缓存**，不能每次提问都新建：新建一个 ChatOpenAI 就是一套新的 httpx 客户端，
    要重新做 TCP + TLS 握手。

    ⚠️ **改写要关掉 thinking**：DeepSeek V4 默认开思考模式，对「把追问改写成独立问题」
    这种纯格式转换是纯浪费。实测（2026-10-30）：

    | thinking | 改写耗时 |
    |---|---|
    | 开（默认） | **4729ms** |
    | 关 | **1680ms** |

    生成侧保持默认（要质量），只有改写这一个调用关掉。

    ⚠️ `default_headers` 不是可选项：OpenCode Go 网关缺 `x-opencode-session` 会直接
    400 `MissingSessionID`，用通用 SDK 的 UA 会被判为可疑流量。换别的厂商时这两个头
    会被忽略，不影响。
    """
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.LLM_MODEL,
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        temperature=temperature,
        timeout=30,
        max_retries=1,
        # 关掉"思考"：传 Body 里那个 thinking 字段（OpenAI 兼容层不认这个参数，得走 extra_body）
        extra_body={"thinking": {"type": "disabled"}} if disable_thinking else None,
        default_headers={
            settings.LLM_SESSION_HEADER: str(uuid.uuid4()),
            "User-Agent": settings.LLM_USER_AGENT,
        },
    )


def _history_pairs(history) -> list[tuple[str, str]]:
    """把前端传来的历史统一成 `[(role, content)]`。

    同时接受 `{"role": ..., "content": ...}` 字典列表（HTTP 来的）和
    `(role, content)` 元组列表（内部调用更方便）。顺手丢掉空内容 —— 空消息会让
    模型把上下文理解成"用户发了一条空白消息"。
    """
    out: list[tuple[str, str]] = []
    for turn in history or []:
        if isinstance(turn, dict):
            role, text = turn.get("role", "user"), turn.get("content", "")
        else:
            role, text = turn[0], turn[1]
        text = str(text or "").strip()
        if text:
            out.append(("user" if str(role) == "user" else "bot", text))
    return out


def _history_as_text(history: list[tuple[str, str]]) -> str:
    """历史压成「用户：… / 客服：…」纯文本（改写提示词用）。"""
    return "\n".join(f"{'用户' if r == 'user' else '客服'}：{t}" for r, t in history)


def _history_as_messages(history: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """历史转成 LangChain 消息元组 —— `MessagesPlaceholder` 吃这个格式。"""
    return [("human" if r == "user" else "ai", t) for r, t in history]


def _rewrite(llm, question: str, history: list[tuple[str, str]]) -> str:
    """把追问改写成独立问题。

    失败时**返回原问题**，不抛错：改写只是"锦上添花"，它挂了不该让整轮问答失败
    （退化成单轮行为，用户会收到「站内暂无」，比一个 500 好）。
    """
    try:
        raw = llm.invoke(
            _REWRITE_TEMPLATE.format(
                history=_history_as_text(history), question=question
            )
        ).content
        text = str(raw).strip().strip('"').strip("“”").splitlines()
        cleaned = text[0].strip() if text else ""
        return cleaned or question
    except Exception:   # noqa: BLE001
        return question


def ask(
    question: str,
    k: int | None = None,
    kind: str | None = None,
    with_context: bool = True,
    history=None,
) -> dict:
    """完整问答：检索 →（查不到才改写重查）→ 拼 prompt → 调模型 → 解析。

    ## 多轮怎么工作

    传了 `history` **不等于每次都改写**。改写只在「检索查不到」时触发：

    ```
    ① 先用原问题检索
         ├─ 命中  → 直接生成                     （1 次模型调用）
         └─ 0 条 + 有历史 → 改写 → 重查 → 生成    （2 次模型调用）
    ```

    为什么用「查没查到」而不是「像不像追问」来判断（2026-10-30 实测）：

    | 提问 | 原问题直接检索 | 结论 |
    |---|---|---|
    | 那取消呢 | 0 条 | 需要改写 |
    | 我们之前讨论过的那个会员要多少钱 | **0 条** | 显式指代也会失败（多余的字稀释语义） |
    | 刚才说的那个收藏怎么取消 | 4 条 | 句里有足够关键词，**不用改写** |

    也就是说：**能不能查到取决于句子里有没有关键词，跟句式无关。** 所以不猜句式，
    只问事实 —— 词表判断法在这种句子面前必然漏判。

    ## 两个"问题"各司其职

    - `q_for_search`（可能是改写结果）→ 只用于检索，要求「准确」
    - `question`（原句）→ 用于生成，要求「自然」：用户问「那取消呢」，回答就该像在接话，
      而不是一份《如何取消收藏》的标准说明书

    链路用 **LCEL** 写：`prompt | llm | StrOutputParser()`。加多轮只是在
    `from_messages` 里插一个 `MessagesPlaceholder("history")`，管道本身一行不用改。
    """
    if not settings.llm_ready():
        raise RuntimeError(
            "对话模型没有配置：请设置环境变量 COMIC_LLM_API_KEY（DeepSeek 的 key），"
            "再重试。只想看检索效果的话用 search 子命令，它不需要 key。"
        )

    turns = _history_pairs(history)
    started = time.perf_counter()

    # ① 先用原问题检索（5ms 量级，不花钱，所以"先查一次看看"几乎零成本）
    retrieve_started = time.perf_counter()
    pairs = _retrieve(question, k, kind, _default_min_score())
    retrieve_ms = int((time.perf_counter() - retrieve_started) * 1000)

    llm = _build_llm()
    rewritten: str | None = None
    rewrite_ms = 0

    # ② 查不到 + 有上文 → 改写后重查。改写用 temperature=0（要确定性，不要发挥）
    if not pairs and turns:
        rewrite_started = time.perf_counter()
        candidate = _rewrite(_build_llm(0.0, True), question, turns)
        rewrite_ms = int((time.perf_counter() - rewrite_started) * 1000)
        if candidate and candidate != question:
            rewritten = candidate
            retrieve_started = time.perf_counter()
            pairs = _retrieve(candidate, k, kind, _default_min_score())
            retrieve_ms += int((time.perf_counter() - retrieve_started) * 1000)

    context = _format_context(pairs)

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_TEMPLATE),
        # 空列表也合法（单轮时就是空），所以不用为"有没有历史"写两个分支
        MessagesPlaceholder("history"),
        ("human", "{question}"),
    ])
    chain = prompt | llm | StrOutputParser()

    llm_started = time.perf_counter()
    answer = chain.invoke({
        "context": context,
        "question": question,
        "history": _history_as_messages(turns),
    }).strip()
    llm_ms = int((time.perf_counter() - llm_started) * 1000)

    total_ms = int((time.perf_counter() - started) * 1000)
    result = {
        "answer": answer,
        "hits": [_hit(d, s) for d, s in pairs],
        # 改写结果回传：没有它你根本不知道多轮有没有生效（排查/调参全靠这个字段）
        "rewritten": rewritten,
        "backend": settings.embedding_backend(),
        "model": settings.LLM_MODEL,
        "elapsedMs": {
            "retrieve": retrieve_ms,
            "rewrite": rewrite_ms,
            "llm": llm_ms,
            "total": total_ms,
        },
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
