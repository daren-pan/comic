"""外部文档源（阶段一：Markdown / Word / Excel）→ 统一的 LangChain `Document`。

## 它和 `corpus.load_corpus()` 里那批工程文档有什么不同

| | 工程文档（本仓库） | 外部文档（本模块） |
|---|---|---|
| 内容 | README / NOTES / docs / schema / OpenAPI | 用户自己的手册、规范、台账 |
| 位置 | 仓库内、跟着代码走 | 运行时目录 `crawler-service/data/kb_docs/`（不进 git） |
| kind | `module_readme` / `design_doc` / `schema` … | `ext_md` / `ext_word` / `ext_excel` |
| module | 各模块名 | 统一 `external` |

两者进**同一个 Chroma 集合**：检索面只有一个，用 `kind` / `module` 过滤即可区分来源。

## 三种格式各自的处理方式

| 格式 | 做法 | `read_mode` |
|---|---|---|
| `.md` | 直接交给 `chunker.chunk_markdown` 按标题树切 | `lines`（能按行号回读原文件） |
| `.docx` | **先转成 Markdown**（标题样式 → `#`、表格 → Markdown 表），再走同一套切分 | `chunk`（中间 Markdown 在磁盘上不存在，没有行号可回读） |
| `.xlsx` | **一行一个 chunk**，每行把表头拼回去 | `chunk` |

## 为什么 Word 要先转 Markdown

切分策略只有一套（标题树 + 代码块/表格原子化）。把 Word 归一成 Markdown，就能**直接复用**
这套经过实测的切分与长度控制，而不是为 docx 再写一套分块逻辑 —— 两套逻辑意味着两套 bug。

## 为什么 Excel 要一行一个 chunk

一行就是一条独立事实（一个员工、一条配置、一个物料）。把整张表当一个 chunk 会：
① 超出 512 token 被模型静默截断；② 检索命中"表"而不是"那一行"，答案里给不出具体值。
**表头必须拼进每一行**：单看"张三 | 3500"不知道 3500 是什么，拼成"姓名：张三；工资：3500"才有意义。

## 已知限制（阶段一）

- Word / Excel **不做 section 级回读**：`read_knowledge` 返回命中的那条 chunk 本身，
  而不是整节原文（原始文件不是纯文本，没有行号）。要整节得看原文件。
- 只支持 `.md` / `.docx` / `.xlsx`；PDF / HTML / PPT 留给后续阶段。
- 不做增量：沿用全局「全量重建」，manifest 里记 sha1，用于判断索引是否过期。
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path

from . import chunker, config

#: Word 标题样式的名字在不同语言包下不一样：`Heading 1` / `标题 1` / `Heading1` 都要认。
_HEADING_STYLE_RE = re.compile(r"^(?:heading|标题)\s*([1-6])$", re.IGNORECASE)
_TITLE_STYLES = {"title", "标题"}
_SUBTITLE_STYLES = {"subtitle", "副标题"}
_LIST_STYLE_PREFIXES = ("list", "列表", "项目符号")


def _slug(text: str, limit: int = 40) -> str:
    """标题 / 工作表名 → 短 slug（中文保留，其它字符折叠成 -）。"""
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", text).strip("-")
    return (slug or "item")[:limit]


def _rel_of(path: Path, root: Path) -> str:
    """文件 → 记录用的路径。仓库内给相对路径，仓库外给绝对路径（允许 `COMIC_KB_DOCS_DIR`
    指到任意目录，不能因为不在仓库里就丢掉这批文档）。"""
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _file_meta(path: Path, chunks: int) -> dict:
    """manifest 里记的文件指纹（sha1 判断是否改过，与工程文档共用同一套过期检测）。"""
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    stat = path.stat()
    return {
        "sha1": h.hexdigest(),
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "chunks": chunks,
        "bytes": stat.st_size,
        "source": "external",
    }


def iter_external_files(docs_dir: Path) -> list[Path]:
    """递归发现外部文档；跳过隐藏项和 Office 的临时锁文件（`~$xxx.docx`）。"""
    if not docs_dir.is_dir():
        return []
    result: list[Path] = []
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in config.EXTERNAL_SUFFIXES:
            continue
        if path.name.startswith(("~$", ".")):
            continue
        if any(part.startswith(".") for part in path.relative_to(docs_dir).parts):
            continue
        result.append(path)
    return result


def _emit(doc_id: str, page_content: str, metadata: dict) -> list:
    """正文 → 若干 `Document`（超长按 `chunker.split_body` 切，元数据逐条补全）。"""
    from langchain_core.documents import Document

    parts = chunker.split_body(page_content) or [page_content]
    documents = []
    for part_no, text in enumerate(parts):
        meta = dict(metadata)
        meta["doc_id"] = f"{doc_id}-{part_no}"
        meta["part"] = int(part_no)
        meta["chunker_version"] = config.CHUNKER_VERSION
        meta["token_count"] = int(chunker.count_tokens(text))
        meta["content_hash"] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        documents.append(
            Document(id=meta["doc_id"], page_content=text, metadata=meta)
        )
    return documents


# ---------------- Word ----------------

def _heading_level(style_name: str) -> int | None:
    """样式名 → 标题级别；不是标题返回 None。"""
    name = (style_name or "").strip()
    match = _HEADING_STYLE_RE.match(name)
    if match:
        return int(match.group(1))
    lowered = name.lower()
    if lowered in _TITLE_STYLES:
        return 1
    if lowered in _SUBTITLE_STYLES:
        return 2
    return None


def _paragraph_to_md(paragraph) -> str:
    """段落 → Markdown 行（标题补 `#`，列表补 `-`）。"""
    text = (paragraph.text or "").strip()
    if not text:
        return ""
    style_name = getattr(getattr(paragraph, "style", None), "name", "") or ""
    level = _heading_level(style_name)
    if level is not None:
        return f"{'#' * level} {text}"
    if style_name.strip().lower().startswith(_LIST_STYLE_PREFIXES):
        return f"- {text}"
    return text


def _cell_text(cell) -> str:
    """单元格文字：多段拼一行；转义竖线（Markdown 表格的列分隔符）。"""
    pieces = [p.text.strip() for p in cell.paragraphs if (p.text or "").strip()]
    text = " / ".join(pieces).replace("|", "\\|").replace("\n", " ")
    if len(text) > config.DOCX_MAX_CELL_CHARS:
        text = text[: config.DOCX_MAX_CELL_CHARS].rstrip() + "…"
    return text


def _table_to_md(table) -> str:
    """Word 表格 → Markdown 表格。首行当表头，列宽按最大列数补齐。"""
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [_cell_text(cell) for cell in row.cells]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header, body = rows[0], rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * width) + "|",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def docx_to_markdown(path: Path) -> str:
    """`.docx` → Markdown 文本（按正文顺序处理段落与表格）。

    ⚠️ 必须按 `body` 的子元素顺序遍历：`doc.paragraphs` / `doc.tables` 是两个独立列表，
    分开遍历会把所有表格挪到文末，破坏"这段文字说明的是上面那张表"的上下文。
    """
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(str(path))
    lines: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = _paragraph_to_md(Paragraph(child, document))
            if text:
                lines.append(text)
        elif child.tag == qn("w:tbl"):
            table_md = _table_to_md(Table(child, document))
            if table_md:
                lines.append("")
                lines.append(table_md)
                lines.append("")
    # 压缩连续空行，避免无意义的段落分隔干扰切分。
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text


def load_docx(path: Path, root: Path, kind: str) -> list:
    rel = _rel_of(path, root)
    text = docx_to_markdown(path)
    if not text.strip():
        raise ValueError("Word 文档没有可提取的文字（可能是纯图片文档）")
    title = next(
        (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")),
        path.stem,
    )
    return chunker.chunk_markdown(
        text,
        rel_path=rel,
        title=title,
        kind=kind,
        module=config.EXTERNAL_MODULE,
        status="current",
        read_mode="chunk",
    )


# ---------------- Excel ----------------

def _cell_value(value) -> str:
    """单元格 → 短字符串（日期转 ISO、浮点去多余零、超长截断）。"""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        text = value.isoformat()
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value).strip()
    if len(text) > config.XLSX_MAX_CELL_CHARS:
        text = text[: config.XLSX_MAX_CELL_CHARS].rstrip() + "…"
    return text


def _row_text(header: list[str], values: list[str]) -> str:
    """一行数据 → `表头：值` 的组合文本（空值跳过，全空返回空串）。"""
    pairs = [
        f"{head}：{value}"
        for head, value in zip(header, values)
        if value and head
    ]
    return "\n".join(pairs)


def load_xlsx(path: Path, root: Path, kind: str) -> list:
    """`.xlsx` → 一行一个 `Document`；表头拼进每一行，空行跳过。"""
    from openpyxl import load_workbook

    rel = _rel_of(path, root)
    workbook = load_workbook(str(path), read_only=True, data_only=True)
    documents: list = []
    try:
        for sheet in workbook.worksheets:
            header: list[str] | None = None
            used_rows = 0
            for row_no, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                values = [_cell_value(v) for v in row[: config.XLSX_MAX_COLS]]
                if not any(values):
                    continue  # 整行空 → 跳过（Excel 里常有大量空白行）
                if header is None:
                    # 第一行非空内容当表头；没有表头文字就用 列N 兜底。
                    header = [value or f"列{index + 1}" for index, value in enumerate(values)]
                    continue
                used_rows += 1
                if used_rows > config.XLSX_MAX_ROWS:
                    break
                body = _row_text(header, values)
                if not body:
                    continue
                heading = f"{sheet.title} 第 {row_no} 行"
                page_content = (
                    f"{path.stem} / {sheet.title} / 第 {row_no} 行\n{body}"
                )
                doc_id = f"{rel}#{_slug(sheet.title)}-r{row_no}"
                documents.extend(
                    _emit(
                        doc_id,
                        page_content,
                        {
                            "path": rel,
                            "title": path.stem,
                            "heading": heading,
                            "heading_path": f"{path.stem} / {sheet.title}",
                            "kind": kind,
                            "module": config.EXTERNAL_MODULE,
                            "status": "current",
                            "start_line": row_no,
                            "end_line": row_no,
                            "parent_heading_path": f"{path.stem} / {sheet.title}",
                            "parent_start": row_no,
                            "parent_end": row_no,
                            # 原文件是二进制表格，没有行号可回读 → 只回这条 chunk
                            "read_mode": "chunk",
                            "sheet": sheet.title,
                            "row": int(row_no),
                            "format": "xlsx",
                        },
                    )
                )
    finally:
        workbook.close()
    return documents


# ---------------- Markdown ----------------

def load_md(path: Path, root: Path, kind: str) -> list:
    """外部 `.md`：和工程文档同一套切分；文件真实存在，所以能按行号回读。"""
    rel = _rel_of(path, root)
    text = path.read_text(encoding="utf-8", errors="replace")
    title = next(
        (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("# ")),
        path.stem,
    )
    return chunker.chunk_markdown(
        text,
        rel_path=rel,
        title=title,
        kind=kind,
        module=config.EXTERNAL_MODULE,
        status="current",
        read_mode="lines",
    )


_LOADERS = {".md": load_md, ".docx": load_docx, ".xlsx": load_xlsx}


def load_external(root: Path, docs_dir: Path | None = None) -> tuple[list, dict, list]:
    """加载外部文档目录，返回 `(documents, files, skipped)`。

    目录不存在时**静默返回空**（不是错误）：阶段一允许"还没放资料"。
    单篇失败只记 `skipped`，不影响其它文档 —— 与 `load_corpus` 的容错策略一致。
    """
    root = Path(root).resolve()
    docs_dir = Path(docs_dir).resolve() if docs_dir else config.kb_docs_dir(root)

    documents: list = []
    files: dict[str, dict] = {}
    skipped: list[dict] = []

    for path in iter_external_files(docs_dir):
        rel = _rel_of(path, root)
        suffix = path.suffix.lower()
        loader = _LOADERS.get(suffix)
        if loader is None:  # 理论上不会发生（iter 已按后缀过滤），防御性处理
            skipped.append({"path": rel, "reason": f"不支持的格式：{suffix}"})
            continue
        kind = config.EXTERNAL_KIND.get(suffix, "ext_md")
        try:
            docs = loader(path, root, kind)
        except Exception as exc:  # noqa: BLE001 —— 单篇坏文件不应拖垮整库
            skipped.append({"path": rel, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        if not docs:
            skipped.append({"path": rel, "reason": "没有可索引的内容"})
            continue
        documents.extend(docs)
        files[rel] = _file_meta(path, len(docs))

    return documents, files, skipped
