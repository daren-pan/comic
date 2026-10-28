"""RAG 第一阶段「加载」：把两种形态的数据源统一成 LangChain `Document`。

## 两种数据源，两种处理方式

| 数据源 | 形态 | 处理 | 为什么不这样处理会出问题 |
|---|---|---|---|
| `knowledge/faq.md` | 一个文件里 10 个小节 | **按 `##` 切开**，每节一个 Document | 整份塞进一条 Document 时，检索只能定位到「文件」粒度 —— 明明问的是「忘记密码」，却把整份 FAQ 都召回，prompt 里 90% 是无关内容，模型容易答串 |
| `comic` 表 54 部作品 | 每条 100 字左右 | **不切**，一条作品一个 Document | 正文本来就短，再切就把「作者 + 状态 + 简介」劈成两半，检索到半截反而看不懂 |

**「切分粒度要跟着数据形态走」是 RAG 里最容易被忽略、影响又最大的一步。**
一个常见的错误做法是给所有文本套同一个 `RecursiveCharacterTextSplitter(chunk_size=500)`
—— 对长文章合理，对 FAQ 会把一个小节从中间截断，对短简介则完全没必要。

## 为什么 metadata 要精挑细选

`Document.metadata` 会随检索结果一起进入 prompt，也会出现在接口响应里。所以这里
**只放能公开、且对回答有用的字段**：

- ✅ `kind`（faq / comic）：检索时可以按类型过滤，也是给模型看的来源标记
- ✅ `comic_id` / `title`：让模型能说「在第 12 部作品里」，前端也能拼链接
- ❌ `source` / `source_comic_id` / `detail_url`：**采集来源信息，绝不下发** ——
  否则用户问一句「这漫画哪来的」，模型照着 metadata 就答出去了
"""
from __future__ import annotations

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter
from zhconv import convert as zh_convert

from core.db import db

from . import settings

#: 一次取多少部作品。现在只有 54 部，一次拿完；数据涨到上万时应改成分页循环 +
#: 增量更新（只对 `sync_time` 变化的作品重新向量化），否则每次重建都是全量调用 embedding API。
_PAGE_SIZE = 1000


def load_faq_documents() -> list[Document]:
    """FAQ → 按 `##` 切开的一堆 Document（每节一条）。

    `MarkdownHeaderTextSplitter` 与 `RecursiveCharacterTextSplitter` 的区别值得记：
    前者按**语义结构**（标题层级）切，切点永远在小节边界上；后者按**字符数**切，
    切点可能落在句子中间。知识库是 markdown 时，优先用前者。

    切出来的每个 Document 的 metadata 里会带上 `h1` / `h2` 标题 —— 所以模型看到的
    上下文里天然带着「图片加载不出来怎么办」这个小标题，回答更不容易跑偏。
    """
    if not settings.FAQ_FILE.is_file():
        raise FileNotFoundError(f"FAQ 知识库不存在：{settings.FAQ_FILE}")

    text = settings.FAQ_FILE.read_text(encoding="utf-8")
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2")],
        # 标题**只进 metadata**、不留在正文里（`strip_headers=True`，也是默认值）。
        # 为什么：拼 prompt 时我们本来就会用 metadata 的 title 打一个 `[FAQ] 标题` 标签，
        # 正文里再留一次就是重复（`[FAQ] 忘记密码怎么办` 下面又写 `## 忘记密码怎么办`），
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
        doc.metadata.update({"kind": "faq", "title": h2})
        docs.append(doc)
    return docs


def load_comic_documents() -> list[Document]:
    """`comic` 表 → 一条作品一个 Document。

    `page_content` 用「键：值」的短行格式而不是一段散文，原因是：**embedding 模型和
    对话模型都更容易从结构化短行里取准信息**（问「作者是谁」时，`作者：尾田荣一郎`
    比「这部作品由尾田荣一郎创作……」更容易被精确引用）。

    字段白名单见模块注释 —— `source` 一类的采集侧信息**不出现在这里**。
    """
    rows, _total = db.list_comics(page=1, page_size=_PAGE_SIZE)
    if not rows:
        return []

    ids = [int(r["id"]) for r in rows]
    tags_map = db.get_comic_tags_bulk(ids)   # 一次性批量取标签，避免 N+1

    docs: list[Document] = []
    for r in rows:
        cid = int(r["id"])
        tags = tags_map.get(cid) or []

        # 站内作品来自多个源站，标题和简介里常混着繁体 —— 实测 54 部里就有
        # 《創世的大河》《邂逅雨中貉》。而用户几乎只用简体提问：不转的话，
        # 「创世的大河」检索不到「創世的大河」。语义模型能扛住一部分这种情况，
        # 但 hash 后端完全搜不到，所以统一转简体（`zhconv` 项目里本来就有，
        # 采集端的跨源去重也在用它）。
        def _s(value: object) -> str:
            return zh_convert(str(value or ""), "zh-cn")

        lines = [
            f"《{_s(r['title'])}》",
            f"作者：{_s(r.get('author')) or '未知'}",
            f"状态：{_s(r.get('status')) or '未知'}",
            f"题材：{_s(r.get('category')) or '未分类'}",
            f"标签：{'、'.join(_s(t) for t in tags) if tags else '无'}",
            f"章节数：{r.get('chapter_count') or 0}",
            f"最新：{_s(r.get('latest_chapter_title')) or '无'}",
            f"简介：{_s(r.get('description')).strip() or '暂无简介'}",
        ]
        docs.append(
            Document(
                page_content="\n".join(lines),
                metadata={
                    "kind": "comic",
                    "comic_id": cid,
                    # metadata 里的标题保留**原文**：它要用于界面展示和跳转，
                    # 不该因为我们做检索优化就改变用户看到的书名。
                    "title": str(r["title"]),
                    "status": str(r.get("status") or ""),
                },
            )
        )
    return docs


def load_all() -> list[Document]:
    """两个数据源合并（建索引用）。"""
    return load_faq_documents() + load_comic_documents()
