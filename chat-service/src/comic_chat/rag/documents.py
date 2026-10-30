"""RAG 第一阶段「加载」：把两种形态的数据源统一成 LangChain `Document`。

## 两种数据源，两种处理方式

| 数据源 | 形态 | 处理 | 为什么不这样处理会出问题 |
|---|---|---|---|
| `knowledge/faq.md` | 一个文件里 10 个小节 | **按 `##` 切开**，每节一个 Document | 整份塞进一条 Document 时，检索只能定位到「文件」粒度 —— 明明问的是「忘记密码」，却把整份 FAQ 都召回，prompt 里 90% 是无关内容，模型容易答串 |
| `comic` 表 54 部作品 | 每条 100 字左右 | **不切**，一条作品一个 Document | 正文本来就短，再切就把「作者 + 状态 + 简介」劈成两半，检索到半截反而看不懂 |

**「切分粒度要跟着数据形态走」是 RAG 里最容易被忽略、影响又最大的一步。**
一个常见的错误做法是给所有文本套同一个 `RecursiveCharacterTextSplitter(chunk_size=500)`
—— 对长文章合理，对 FAQ 会把一个小节从中间截断，对短简介则完全没必要。

## 两种文本：检索用一份，给模型读另一份

每条 Document 存两份文字，这是 v2 的核心改动（见 `README.md` 的「检索设计」）：

| 字段 | 内容 | 用途 |
|---|---|---|
| `page_content` | FAQ：标题 + 首句<br>漫画：书名 + 作者 + 标签 + 简介 | **只拿它算向量**（越聚焦越好） |
| `metadata["display"]` | 完整原文 | **只拿它拼 prompt**（一个字不能少） |

为什么不合成一份：向量是整段文字的平均值。用户问句往往只有 4~6 字，拿去跟 150 字的
完整正文比，相似度被稀释到阈值以下 —— 实测「要不要钱」0.489，差 0.011 被误杀，
回答退化成「站内暂时没有」。分离后 0.56，稳过阈值。

**模型读到的内容和以前完全一样**，变的只是「拿去比对的那段文字」。修改 `page_content`
的拼法后记得把 `settings.DOC_FORMAT_VERSION` 加一，否则旧向量会被继续复用。

## 为什么 metadata 要精挑细选

`Document.metadata` 会随检索结果一起进入 prompt，也会出现在接口响应里。所以这里
**只放能公开、且对回答有用的字段**：

- ✅ `kind`（faq / comic）：检索时可以按类型过滤，也是给模型看的来源标记
- ✅ `comic_id` / `title`：让模型能说「在第 12 部作品里」，前端也能拼链接
- ❌ `source` / `source_comic_id` / `detail_url`：**采集来源信息，绝不下发** ——
  否则用户问一句「这漫画哪来的」，模型照着 metadata 就答出去了
"""
from __future__ import annotations

from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter
from zhconv import convert as zh_convert

from comic_core.storage.mysql import MySQLStorage

from . import settings

#: 存储句柄（进程级单例）。
#: ⚠️ 这里直接建 `MySQLStorage()` 而**不是** `from core.db import db` —— `core/` 是
#: api-service 的模块，跨服务引用不了。连接参数本来就全走 `COMIC_MYSQL_*` 环境变量
#: （见 `comic_core/storage/mysql/_util.py` 的 `_DSN`），compose 已经注入，所以本服务
#: 独立连接完全等价。构造时不建连接（懒连），环境变量缺失也不会在导入期炸。
db = MySQLStorage()

#: 一次取多少部作品。现在只有 54 部，一次拿完；数据涨到上万时应改成分页循环 +
#: 增量更新（只对 `sync_time` 变化的作品重新向量化），否则每次重建都是全量调用 embedding API。
_PAGE_SIZE = 1000


def _first_line(text: str) -> str:
    """取第一个非空行 —— 检索文本里代表「正文首句」。

    空行要跳过：FAQ 每个 `##` 标题后面都跟一个空行，直接 `splitlines()[0]` 会拿到空串，
    检索文本就退化成「只有标题」，白丢失细节词（见 `load_faq_documents` 的说明）。
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def load_faq_documents() -> list[Document]:
    """FAQ → 按 `##` 切开的一堆 Document（每节一条）。

    `MarkdownHeaderTextSplitter` 与 `RecursiveCharacterTextSplitter` 的区别值得记：
    前者按**语义结构**（标题层级）切，切点永远在小节边界上；后者按**字符数**切，
    切点可能落在句子中间。知识库是 markdown 时，优先用前者。

    ⚠️ 每条 Document 存**两份文本**（详见 `README.md` 的「检索设计」）：
    - `page_content` = 标题 + 正文首句 —— 只有它会被算成向量
    - `metadata["display"]` = 完整正文 —— 只有它会被拼进 prompt

    为什么不能只留一份「完整正文」（v1 的做法）：向量是整段的平均值，用户问句往往
    只有 4~6 字（「要不要钱」），拿去跟 150 字的正文比，相似度被稀释到阈值以下 ——
    实测 0.489，差 0.011 被误杀，回答退化成「站内暂时没有」。改短后 0.56，稳过阈值。

    为什么不是只留标题：实测「收藏按钮在哪」只留标题时 0.61、带首句 0.73 ——
    标题里没有「按钮」二字，首句里有。**标题管「问的是什么」，首句管「细节词」**。
    """
    if not settings.FAQ_FILE.is_file():
        raise FileNotFoundError(f"FAQ 知识库不存在：{settings.FAQ_FILE}")

    text = settings.FAQ_FILE.read_text(encoding="utf-8")
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2")],
        # 标题**只进 metadata**、不留在正文里（`strip_headers=True`，也是默认值）。
        # 为什么：拼 prompt 时我们本来就会用 metadata 的 title 打一个 `[FAQ] 标题` 标签，
        # 正文里再留一次就是重复（`[FAQ] 忘记密码怎么办` 下面又写 `## 忘记密码怎么办`）,
        # 白占 token，还会让检索预览看起来像重复了两遍。
        strip_headers=True,
    )

    docs: list[Document] = []
    for doc in splitter.split_text(text):
        h2 = doc.metadata.get("h2", "").strip()
        # 文件头那段「写法约定 / 改完要重建索引」的说明也会被切出来（它只属于 h1，
        # 没有 h2）—— 那是给维护者看的，不能让模型拿它回答用户，直接丢弃。
        if not h2:
            continue

        body = doc.page_content.strip()
        # 检索文本：标题 + 首句。首句通常就是核心答案（「本站完全免费…」「打开漫画详情页…」），
        # 既补上了标题缺的细节词，又不会把语义拉散。
        doc.page_content = f"{h2}\n{_first_line(body)}"
        doc.metadata.update(
            {
                "kind": "faq",
                "title": h2,
                # 完整正文：拼 prompt 时用（`chain._format_context`），**不进向量**
                "display": body,
            }
        )
        docs.append(doc)
    return docs


@dataclass(frozen=True)
class ComicFact:
    """一部作品的**结构化事实**（只放能公开的检索字段，不含采集来源）。

    为什么单独抽出来：它有两个消费者，各自需要不同的形态 ——

    | 消费者 | 用它的什么 |
    |---|---|
    | `load_comic_documents()` | 拼成 `Document` 进向量库（语义检索） |
    | `structured.match()` | 直接拿字段做字面匹配（精确检索） |

    两者共用同一份缓存，避免「每次检索读两遍 DB」。缓存与向量索引**同生命周期**：
    都由 `index.build_index()` 刷新 —— 这样不会出现「索引里有 54 部、结构化却看到 55 部」
    那种错位（多出来的那部没有向量，检索到也用不了）。

    `*_cn` 字段是 `zhconv` 转过的简体：站内混着《創世的大河》《電鋸人》这类繁体标题，
    而用户几乎只用简体提问，不统一就匹配不上。
    """

    comic_id: int
    title: str                    # 原文 —— 展示与跳转用，不能改
    status: str                   # 原文 —— 和原来 metadata 的取值保持一致
    title_cn: str
    author_cn: str
    tags_cn: tuple[str, ...]
    status_cn: str
    chapter_count: int
    latest_cn: str
    description_cn: str


#: 进程内的结构化事实缓存。`None` = 还没读过。
_facts_cache: tuple[ComicFact, ...] | None = None


def _to_simplified(value: object) -> str:
    """转简体。站内作品来自多个源站，标题和简介常混着繁体（实测 54 部里就有
    《創世的大河》《邂逅雨中貉》），而用户几乎只用简体提问：不转的话，
    「创世的大河」检索不到「創世的大河」。语义模型能扛住一部分，字面匹配完全无能为力。
    """
    return zh_convert(str(value or ""), "zh-cn")


def comic_facts(refresh: bool = False) -> tuple[ComicFact, ...]:
    """读全部作品的结构化事实（进程内缓存，`refresh=True` 强制重读）。

    ⚠️ 只在 `index.build_index()` 里传 `refresh=True`。检索路径永远用缓存 —— 数据变了
    但没重建索引时，用旧缓存反而是**对的**：新作品还没有向量，结构化若先看到它，
    就会出现「能匹配到却检索不出内容」的怪现象。
    """
    global _facts_cache
    if _facts_cache is not None and not refresh:
        return _facts_cache

    rows, _total = db.list_comics(page=1, page_size=_PAGE_SIZE)
    if not rows:
        _facts_cache = ()
        return _facts_cache

    ids = [int(r["id"]) for r in rows]
    tags_map = db.get_comic_tags_bulk(ids)   # 一次性批量取标签，避免 N+1

    facts: list[ComicFact] = []
    for r in rows:
        cid = int(r["id"])
        tags = tags_map.get(cid) or []
        facts.append(
            ComicFact(
                comic_id=cid,
                title=str(r["title"]),
                status=str(r.get("status") or ""),
                title_cn=_to_simplified(r["title"]),
                author_cn=_to_simplified(r.get("author")) or "未知",
                tags_cn=tuple(_to_simplified(t) for t in tags),
                status_cn=_to_simplified(r.get("status")) or "未知",
                chapter_count=int(r.get("chapter_count") or 0),
                latest_cn=_to_simplified(r.get("latest_chapter_title")) or "无",
                description_cn=(_to_simplified(r.get("description"))).strip() or "暂无简介",
            )
        )

    _facts_cache = tuple(facts)
    return _facts_cache


def fact_to_document(f: ComicFact) -> Document:
    """结构化事实 → 一条 `Document`（检索文本进向量，完整正文进 metadata）。

    `page_content` 用「键：值」的短行格式而不是一段散文，原因是：**embedding 模型和
    对话模型都更容易从结构化短行里取准信息**（问「作者是谁」时，`作者：尾田荣一郎`
    比「这部作品由尾田荣一郎创作……」更容易被精确引用）。
    """
    # 完整正文（7 行）——给模型读。用户问「更新到几话」「多少章」全靠后三行，
    # 所以展示文本一个字都不能少。
    full_lines = [
        f"《{f.title_cn}》",
        f"作者：{f.author_cn}",
        f"状态：{f.status_cn}",
        f"标签：{'、'.join(f.tags_cn) if f.tags_cn else '无'}",
        f"章节数：{f.chapter_count}",
        f"最新：{f.latest_cn}",
        f"简介：{f.description_cn}",
    ]

    # 检索文本（4 行）——只拿它算向量。
    # 去掉的三行（状态 / 章节数 / 最新话）几乎没有区分度：每部作品都有章节数和最新话，
    # 「最新：第29话」这种字面对「找哪部作品」毫无帮助，却会稀释书名和简介的语义。
    # 实测（2026-10-30）去掉后章节类查询只从 0.79 掉到 0.75 —— 书名本身占主语义。
    #
    # ⚠️ 简介**必须完整保留**：试过截断到 60 字，「有个漫画讲高中生找电台主播」
    # 立刻从第 1 名掉到第 2 名 —— 情节线索正好在被切掉的那半句里。
    #
    # ⚠️ **不放 `comic.category`**：该字段是采集侧早期存的原始分类串（`'爱情, 校园'`
    # 这种多值字符串），已废弃，权威标签来源是 `comic_tag` 关联的 `tag` 表。
    # 两边都放会让同一部作品出现两套互相矛盾的题材（旧值没跟着标签更新）。
    search_lines = [
        f"《{f.title_cn}》",
        f"作者：{f.author_cn}",
        f"标签：{'、'.join(f.tags_cn) if f.tags_cn else '无'}",
        f"简介：{f.description_cn}",
    ]

    return Document(
        page_content="\n".join(search_lines),
        metadata={
            "kind": "comic",
            "comic_id": f.comic_id,
            # metadata 里的标题保留**原文**：它要用于界面展示和跳转，
            # 不该因为我们做检索优化就改变用户看到的书名。
            "title": f.title,
            "status": f.status,
            # 完整正文：拼 prompt 时用，**不进向量**
            "display": "\n".join(full_lines),
        },
    )


def load_comic_documents() -> list[Document]:
    """`comic` 表 → 一条作品一个 Document（走 `comic_facts()` 的缓存，不重复读库）。

    字段白名单见模块注释 —— `source` 一类的采集侧信息**不出现在这里**。
    """
    return [fact_to_document(f) for f in comic_facts()]


def load_all() -> list[Document]:
    """两个数据源合并（建索引用）。"""
    return load_faq_documents() + load_comic_documents()
