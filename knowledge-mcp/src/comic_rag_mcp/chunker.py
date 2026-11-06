"""Markdown 语义切分：按标题树切 chunk，代码块/表格不切坏。

这是 knowledge-mcp 最核心、也最容易被低估的一层。设计取舍见 `README.md` 的
「切分方案」一节，这里只强调三条硬约束：

1. **bge-small-zh-v1.5 的 max_position_embeddings = 512**。中文 1 字约 1 token，
   所以 1200 字的 chunk 后半段会被 tokenizer 静默截断；目标 300~400 字、硬上限 500 字。
2. **代码块 / 表格是原子块**。切点只能落在块与块之间；表格超长时按行切并重复表头。
3. **child 检索、parent 回读**。chunk 里存 `parent_start` / `parent_end`，
   `read_knowledge` 按行号回读整个 H2/H3 小节，避免“只给模型一句孤立的话”。

本模块不依赖 Chroma / embedding，可单独单测。
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from langchain_core.documents import Document

from . import config

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TABLE_RE = re.compile(r"^\s*\|")
_SENTENCE_RE = re.compile(r"(?<=[。！？；;.!?])\s*")


@dataclass
class Section:
    """一个标题节点（含正文到下一个标题之前）。行号均为 1-based、闭区间。"""

    level: int
    heading: str
    heading_path: list[str]
    start_line: int
    end_line: int
    body: str
    parent: "Section | None" = None
    children: list["Section"] = field(default_factory=list)


def _slug(text: str, limit: int = 48) -> str:
    """标题 → 可读短 slug（中文保留；其他字符折叠成 -）。"""
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", text).strip("-")
    return (slug or "section")[:limit]


@lru_cache(maxsize=1)
def _tokenizer():
    """尝试加载 bge 的 tokenizer；找不到就返回 None（回退到字符数）。

    只从本地模型缓存读，**不触发下载**。路径优先 `FASTEMBED_CACHE_PATH`。
    """
    cache = os.environ.get("FASTEMBED_CACHE_PATH", "").strip()
    if not cache:
        cache = str(config.ROOT / "crawler-service" / "data" / "fastembed_cache")
    tokenizer_files = sorted(
        Path(cache).glob("models--Qdrant--bge-small-zh-v1.5/snapshots/*/tokenizer.json")
    )
    if not tokenizer_files:
        return None
    try:
        from tokenizers import Tokenizer

        return Tokenizer.from_file(str(tokenizer_files[-1]))
    except Exception:  # noqa: BLE001 —— tokenizer 只是辅助校验，失败就回退
        return None


def count_tokens(text: str) -> int:
    """token 数；tokenizer 不可用时用字符数（中文场景偏保守）。"""
    tokenizer = _tokenizer()
    if tokenizer is None:
        return len(text)
    return len(tokenizer.encode(text).ids)


def parse_sections(text: str, title: str) -> list[Section]:
    """把 Markdown 解析成扁平 section 列表（含层级 / 行号 / 父子关系）。

    标题识别会跳过 fenced code block 里的 `# 注释`，否则代码里的 shell 注释会被误判成标题。
    """
    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, int, str]] = []  # (0-based line, level, title)
    in_fence = False
    fence_mark = ""

    for i, line in enumerate(lines):
        fence = _FENCE_RE.match(line)
        if fence:
            mark = fence.group(1)
            if not in_fence:
                in_fence, fence_mark = True, mark
            elif mark == fence_mark:
                in_fence, fence_mark = False, ""
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match:
            headings.append((i, len(match.group(1)), match.group(2).strip()))

    if not headings:
        body = "".join(lines).strip()
        return [
            Section(
                level=0,
                heading=title,
                heading_path=[title],
                start_line=1,
                end_line=max(1, len(lines)),
                body=body,
            )
        ]

    sections: list[Section] = []
    stack: list[Section] = []

    # 第一个标题之前的内容（前言）单独成节；没内容就不建。
    first_line = headings[0][0]
    preamble = "".join(lines[:first_line]).strip()
    if preamble:
        preamble_section = Section(
            level=0,
            heading=title,
            heading_path=[title],
            start_line=1,
            end_line=first_line,
            body=preamble,
        )
        sections.append(preamble_section)
        stack.append(preamble_section)

    for idx, (line_no, level, heading) in enumerate(headings):
        next_line = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        while stack and stack[-1].level >= level:
            stack.pop()
        parent = stack[-1] if stack else None
        path = [s.heading for s in stack if s.level > 0] + [heading]
        section = Section(
            level=level,
            heading=heading,
            heading_path=path,
            start_line=line_no + 1,
            end_line=max(line_no + 1, next_line),
            body="".join(lines[line_no + 1 : next_line]).strip(),
            parent=parent,
        )
        if parent is not None:
            parent.children.append(section)
        sections.append(section)
        stack.append(section)

    return sections


def _split_fenced_blocks(text: str) -> list[str]:
    """把正文拆成「代码块 / 表格 / 普通段落」三类原子块。"""
    lines = text.splitlines()
    blocks: list[str] = []
    buf: list[str] = []
    in_fence = False
    fence_mark = ""

    def flush() -> None:
        if buf:
            block = "\n".join(buf).strip("\n")
            if block.strip():
                blocks.append(block)
            buf.clear()

    for line in lines:
        fence = _FENCE_RE.match(line)
        if fence:
            mark = fence.group(1)
            if not in_fence:
                flush()
                in_fence, fence_mark = True, mark
                buf.append(line)
            else:
                buf.append(line)
                if mark == fence_mark:
                    in_fence, fence_mark = False, ""
                    flush()
            continue

        if in_fence:
            buf.append(line)
            continue

        if _TABLE_RE.match(line):
            if buf and not all(_TABLE_RE.match(x) for x in buf):
                flush()
            buf.append(line)
            continue

        # 表格结束（没有空行分隔）时先落块，别把表格和后面的段落粘在一起。
        if buf and all(_TABLE_RE.match(x) for x in buf):
            flush()

        if not line.strip():
            flush()
            continue

        buf.append(line)

    flush()
    return blocks


def _split_table(block: str, max_chars: int) -> list[str]:
    """超大表格按行切，重复表头（前两行：表头 + 分隔行）。"""
    rows = block.splitlines()
    if len(rows) <= 3:
        return [block]
    header = rows[:2]
    body = rows[2:]
    chunks: list[str] = []
    current = list(header)
    for row in body:
        candidate = "\n".join(current + [row])
        if len(candidate) > max_chars and len(current) > len(header):
            chunks.append("\n".join(current))
            current = list(header)
        current.append(row)
    if len(current) > len(header):
        chunks.append("\n".join(current))
    return chunks or [block]


def _hard_split(text: str, max_chars: int) -> list[str]:
    """最后兜底：按句子 / 字符切，带 50 字重叠（仅普通文本）。"""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            window = text[start:end]
            cut = max(
                window.rfind("。"),
                window.rfind("！"),
                window.rfind("？"),
                window.rfind("；"),
                window.rfind("\n"),
            )
            if cut >= max_chars // 2:
                end = start + cut + 1
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - config.OVERLAP_CHARS, start + 1)
    return [p for p in pieces if p]


def _split_block(block: str, max_chars: int) -> list[str]:
    """单个原子块超长时的处理：表格按行、代码块整体保留、文本按行/句/字符。"""
    if len(block) <= max_chars:
        return [block]

    if block.lstrip().startswith("|"):
        return _split_table(block, max_chars)

    # 代码块：宁可整块超限，也不从中间劈开（半截代码比长代码更糟）。
    if _FENCE_RE.match(block.splitlines()[0]):
        return [block]

    pieces: list[str] = []
    current: list[str] = []
    for line in block.splitlines():
        candidate = "\n".join(current + [line])
        if len(candidate) > max_chars and current:
            pieces.append("\n".join(current))
            current = []
        if len(line) > max_chars:
            if current:
                pieces.append("\n".join(current))
                current = []
            pieces.extend(_hard_split(line, max_chars))
            continue
        current.append(line)
    if current:
        pieces.append("\n".join(current))
    return pieces or [block]


def split_body(body: str, max_chars: int | None = None) -> list[str]:
    """把一个小节正文切成若干 <= max_chars 的 chunk 正文。"""
    max_chars = max_chars or config.MAX_CHARS
    body = body.strip()
    if not body:
        return []
    if len(body) <= max_chars and count_tokens(body) <= config.MAX_TOKENS:
        return [body]

    blocks = _split_fenced_blocks(body)
    pieces: list[str] = []
    for block in blocks:
        pieces.extend(_split_block(block, max_chars))

    # 按块打包，避免每个段落都成为独立 chunk。
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for piece in pieces:
        extra = len(piece) + (2 if current else 0)
        if current and current_len + extra > max_chars:
            chunks.append("\n\n".join(current).strip())
            current, current_len = [], 0
        current.append(piece)
        current_len += extra
        if current_len > max_chars:
            chunks.append("\n\n".join(current).strip())
            current, current_len = [], 0
    if current:
        chunks.append("\n\n".join(current).strip())

    # token 复核：超过 480 token 的 chunk 再兜底切一次（不带重叠，避免重复）。
    # ⚠️ 纯代码块不切：半截代码比“长代码被模型截断”更难用。
    result: list[str] = []
    for chunk in chunks:
        if count_tokens(chunk) <= config.MAX_TOKENS:
            result.append(chunk)
        elif _FENCE_RE.match(chunk.lstrip().splitlines()[0]):
            result.append(chunk)
        else:
            result.extend(_hard_split(chunk, max(160, max_chars // 2)))
    return [c for c in result if c.strip()]


def _read_parent(section: Section) -> Section:
    """`read_knowledge` 回读的范围：**section 自身**。

    ⚠️ 不要回溯到 H2：H2 可能只有一句引子，真正的表格/步骤在 H3 里；
    回读 H2 会得到“只有标题没有正文”，模型只能回答“资料里没有”。
    section 的 `end_line` 已经包含它下面的全部内容，本身就是正确的父范围。
    """
    return section


def chunk_markdown(
    text: str,
    *,
    rel_path: str,
    title: str,
    kind: str,
    module: str,
    status: str,
    read_mode: str = "lines",
) -> list[Document]:
    """一篇 Markdown → LangChain `Document` 列表（带完整元数据）。

    `read_mode` 决定 `read_knowledge` 怎么回读：

    - `"lines"`（默认）：按 `parent_start/parent_end` 回读原文件行号 —— 适用于真实存在的
      纯文本文件（`.md` / `.sql`）。
    - `"chunk"`：直接返回库里这条 chunk 的正文 —— 适用于**没有行号可回读**的源，
      比如 Word / Excel 解析出来的中间 Markdown（它在磁盘上并不存在）。
    """
    documents: list[Document] = []
    for section in parse_sections(text, title):
        if not section.body and section.children:
            continue
        if not section.body:
            continue
        # 父节只有一句引子、主要内容都在子节时，不为引子单独造 chunk。
        if section.children and len(section.body.strip()) < config.MIN_CHARS:
            continue

        heading_path = " / ".join(section.heading_path)
        parts = split_body(section.body)
        parent = _read_parent(section)
        parent_path = " / ".join(parent.heading_path)

        for part_no, part in enumerate(parts):
            page_content = f"{heading_path}\n{part}".strip()
            digest = hashlib.sha1(
                f"{rel_path}:{heading_path}:{section.start_line}".encode("utf-8")
            ).hexdigest()[:8]
            doc_id = f"{rel_path}#{_slug(heading_path)}-{digest}-{part_no}"
            meta = {
                "doc_id": doc_id,
                "path": rel_path,
                "title": title,
                "heading": section.heading,
                "heading_path": heading_path,
                "kind": kind,
                "module": module,
                "status": status,
                "start_line": int(section.start_line),
                "end_line": int(section.end_line),
                "parent_heading_path": parent_path,
                "parent_start": int(parent.start_line),
                "parent_end": int(parent.end_line),
                # Markdown 必须按行号回读父小节；缺这个标记会退化成“只返回当前 child”，
                # 长小节后半段的事实（比如文件表）就会丢。
                # Word / Excel 解析出来的中间 Markdown 在磁盘上不存在，只能按 chunk 回读。
                "read_mode": read_mode,
                "part": int(part_no),
                "chunker_version": config.CHUNKER_VERSION,
                "token_count": int(count_tokens(page_content)),
                "content_hash": hashlib.sha1(page_content.encode("utf-8")).hexdigest()[:12],
            }
            documents.append(
                Document(id=doc_id, page_content=page_content, metadata=meta)
            )
    return documents
