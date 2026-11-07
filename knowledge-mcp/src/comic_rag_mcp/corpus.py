"""知识库语料加载：Markdown / MySQL schema / OpenAPI → 统一 `Document`。

## 为什么只收“人写过的文档”

第一版不索引全部代码。代码的强项是精确符号查找（ripgrep / AST），向量检索更适合
README / NOTES / docs / 表注释 / 接口摘要这类**已经用自然语言解释过**的内容。

## 四类语料

| 类型 | 来源 | 切法 |
|---|---|---|
| Markdown | 根 README/AGENTS、docs、各模块 README/NOTES、源站 README | `chunker.chunk_markdown` 按标题树切 |
| SQL schema | `comic-core/sql/mysql_schema.sql` | 一张表一个 chunk，字段注释进正文 |
| OpenAPI | `api-service/openapi.json` | 一个端点一个 chunk |
| 外部文档 | `crawler-service/data/kb_docs/`（可 `COMIC_KB_DOCS_DIR` 覆盖） | 见 `external.py`：Word 转 Markdown 后按标题树切、Excel 一行一个 chunk |

所有 `Document` 都带 `path / heading_path / kind / module / status / start_line /
parent_start / parent_end`，供 `read_knowledge` 精确回源。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import chunker, config, external

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_CREATE_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?\s*\(", re.IGNORECASE)
_TABLE_COMMENT_RE = re.compile(r"COMMENT\s*=\s*'((?:[^'\\]|\\.)*)'", re.IGNORECASE)
_COLUMN_RE = re.compile(r"^\s*`?([A-Za-z_][\w]*)`?\s+([A-Za-z]+(?:\([^)]*\))?[^,]*?)(?:,)?\s*$")
_COMMENT_RE = re.compile(r"COMMENT\s+'((?:[^'\\]|\\.)*)'", re.IGNORECASE)
_NON_COLUMN = {
    "KEY",
    "UNIQUE",
    "CONSTRAINT",
    "PRIMARY",
    "INDEX",
    "FOREIGN",
    "CHECK",
    "FULLTEXT",
    "SPATIAL",
}


@dataclass
class CorpusResult:
    documents: list = field(default_factory=list)
    files: dict[str, dict] = field(default_factory=dict)
    skipped: list[dict] = field(default_factory=list)


def _sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _is_excluded(rel: str) -> bool:
    if rel in config.EXCLUDE_FILES:
        return True
    if any(rel.startswith(prefix) for prefix in config.EXCLUDE_PREFIXES):
        return True
    if any(rel.endswith(suffix) for suffix in config.EXCLUDE_SUFFIXES):
        return True
    parts = set(Path(rel).parts)
    return bool(parts & config.EXCLUDE_DIR_PARTS)


def iter_markdown_files(root: Path) -> list[Path]:
    """发现所有候选 Markdown；排除 node_modules / venv / 数据目录等。"""
    root = root.resolve()
    candidates: set[Path] = set()
    for name in ("README.md", "AGENTS.md"):
        path = root / name
        if path.is_file():
            candidates.add(path)
    for pattern in ("README.md", "NOTES.md"):
        candidates.update(root.rglob(pattern))
    candidates.update((root / "docs").rglob("*.md"))
    # 模块职责文档：`<module>/docs/*.md`（各模块的 README 仍在模块根，由上面的 rglob 收走）
    candidates.update(root.glob("*/docs/*.md"))

    result: list[Path] = []
    for path in sorted(candidates):
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if _is_excluded(rel):
            continue
        if path.is_file():
            result.append(path)
    return result


def classify(rel: str) -> tuple[str, str]:
    """相对路径 → (`kind`, `module`)。"""
    parts = Path(rel).parts
    if rel in {"README.md", "AGENTS.md"}:
        return "root_doc", "project"
    if rel.startswith("docs/"):
        if rel == "docs/deploy.md":
            return "deploy_doc", "deploy"
        if rel == "docs/auth.md":
            return "design_doc", "api"
        if rel == "docs/architecture.md":
            return "design_doc", "project"
        return "design_doc", "docs"
    if "sources" in parts and rel.endswith("/README.md"):
        return "source_readme", "crawler"
    # 模块 `docs/` 下的职责文档：一份文件一个职责，kind 按文件名区分
    if "/docs/" in rel:
        module_kind = {
            "README.md": "module_readme",
            "NOTES.md": "module_notes",
            "ARCHITECTURE.md": "module_design",
            "OPERATIONS.md": "module_ops",
            "CONFIG.md": "module_config",
            "EVAL.md": "module_eval",
            "BENCH.md": "module_eval",
        }.get(rel.rsplit("/", 1)[-1])
        if module_kind:
            return module_kind, _module_of(parts)
    if rel.endswith("/NOTES.md"):
        return "module_notes", _module_of(parts)
    if rel.endswith("/README.md"):
        if parts and parts[0] == "deploy":
            return "deploy_doc", "deploy"
        return "module_readme", _module_of(parts)
    return "design_doc", "docs"


def _module_of(parts: tuple[str, ...]) -> str:
    if not parts:
        return "project"
    first = parts[0]
    mapping = {
        "comic-core": "core",
        "crawler-service": "crawler",
        "api-service": "api",
        "comic-scheduler": "scheduler",
        "chat-service": "chat",
        "comic-web": "web",
        "comic-front": "front",
        "deploy": "deploy",
        "scripts": "scripts",
        "tools": "tools",
        "docs": "docs",
        "knowledge-mcp": "knowledge",
    }
    return mapping.get(first, first)


def _title_of(text: str, fallback: str) -> str:
    match = _H1_RE.search(text)
    if match:
        return match.group(1).strip()
    return fallback


def _files_meta(path: Path, rel: str, chunks: int) -> dict:
    stat = path.stat()
    return {
        "sha1": _file_sha1(path),
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "chunks": chunks,
        "bytes": stat.st_size,
    }


def load_markdown(path: Path, root: Path) -> tuple[list, dict]:
    rel = path.resolve().relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    kind, module = classify(rel)
    docs = chunker.chunk_markdown(
        text,
        rel_path=rel,
        title=_title_of(text, path.stem),
        kind=kind,
        module=module,
        status=config.status_of(rel),
    )
    return docs, _files_meta(path, rel, len(docs))


def _find_matching_paren(text: str, open_idx: int) -> int:
    """从 `(` 开始找匹配的 `)`；SQL 类型里的 VARCHAR(255) / DECIMAL(10,2) 不算结束。"""
    depth = 0
    quote = ""
    for i in range(open_idx, len(text)):
        ch = text[i]
        if quote:
            if ch == quote and text[i - 1] != "\\":
                quote = ""
            continue
        if ch in {"'", '"'}:
            quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


def _line_no(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _sql_column_lines(block: str) -> list[str]:
    """从一个 CREATE TABLE 块里抽字段定义（跳过 KEY / CONSTRAINT 等）。"""
    lines: list[str] = []
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        first = line.split(None, 1)[0].upper().strip("`")
        if first in _NON_COLUMN:
            continue
        match = _COLUMN_RE.match(line)
        if not match:
            continue
        name, rest = match.group(1), match.group(2).strip()
        comment = _COMMENT_RE.search(rest)
        col_type = rest.split("COMMENT", 1)[0].strip().rstrip(",")
        note = comment.group(1) if comment else ""
        lines.append(f"- `{name}` {col_type}" + (f"：{note}" if note else ""))
    return lines


def _emit(
    *,
    doc_id: str,
    page_content: str,
    metadata: dict,
) -> list:
    from langchain_core.documents import Document

    chunks = chunker.split_body(page_content)
    result = []
    for part, text in enumerate(chunks or [page_content]):
        meta = dict(metadata)
        meta["doc_id"] = f"{doc_id}-{part}"
        meta["part"] = part
        meta["content_hash"] = _sha1_text(text)[:12]
        meta["token_count"] = int(chunker.count_tokens(text))
        meta["chunker_version"] = config.CHUNKER_VERSION
        result.append(
            Document(id=meta["doc_id"], page_content=text, metadata=meta)
        )
    return result


def load_sql(path: Path, root: Path) -> tuple[list, dict]:
    rel = path.resolve().relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    docs: list = []
    overview: list[str] = []

    for match in _CREATE_TABLE_RE.finditer(text):
        table = match.group(1)
        open_idx = text.find("(", match.start())
        close_idx = _find_matching_paren(text, open_idx)
        block = text[open_idx + 1 : close_idx]
        start_line = _line_no(text, match.start())
        end_line = _line_no(text, close_idx)
        table_comment_match = _TABLE_COMMENT_RE.search(text, close_idx, min(len(text), close_idx + 500))
        table_comment = table_comment_match.group(1) if table_comment_match else ""
        columns = _sql_column_lines(block)
        body = "\n".join(
            [
                f"表名：{table}",
                f"表注释：{table_comment or '（无）'}",
                "字段：",
                *columns,
            ]
        )
        page_content = f"数据库表 / {table}\n{body}"
        doc_id = f"{rel}#table-{table}"
        docs.extend(
            _emit(
                doc_id=doc_id,
                page_content=page_content,
                metadata={
                    "doc_id": doc_id,
                    "path": rel,
                    "title": f"数据表 {table}",
                    "heading": table,
                    "heading_path": f"数据库表 / {table}",
                    "kind": "schema",
                    "module": "core",
                    "status": "current",
                    "start_line": start_line,
                    "end_line": end_line,
                    "parent_heading_path": f"数据库表 / {table}",
                    "parent_start": start_line,
                    "parent_end": end_line,
                    "read_mode": "lines",
                    "table": table,
                },
            )
        )
        overview.append(f"- `{table}`：{table_comment or '（无注释）'}")

    if overview:
        overview_text = "数据库表清单\n" + "\n".join(overview)
        doc_id = f"{rel}#overview"
        docs.extend(
            _emit(
                doc_id=doc_id,
                page_content=overview_text,
                metadata={
                    "doc_id": doc_id,
                    "path": rel,
                    "title": "数据库表清单",
                    "heading": "表清单",
                    "heading_path": "数据库表 / 表清单",
                    "kind": "schema",
                    "module": "core",
                    "status": "current",
                    "start_line": 1,
                    "end_line": len(text.splitlines()),
                    "parent_heading_path": "数据库表 / 表清单",
                    "parent_start": 1,
                    "parent_end": len(text.splitlines()),
                    "read_mode": "lines",
                    "table": "",
                },
            )
        )

    return docs, _files_meta(path, rel, len(docs))


def _schema_label(schema: dict) -> str:
    if not isinstance(schema, dict):
        return ""
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    if "type" in schema:
        return str(schema["type"])
    return ""


def _param_lines(operation: dict) -> list[str]:
    lines: list[str] = []
    for param in operation.get("parameters") or []:
        if not isinstance(param, dict):
            continue
        name = param.get("name", "")
        where = param.get("in", "")
        required = "必填" if param.get("required") else "可选"
        schema = param.get("schema") or {}
        desc = param.get("description", "")
        lines.append(
            f"- `{name}`（{where}，{required}，{_schema_label(schema)}）"
            + (f"：{desc}" if desc else "")
        )
    return lines


def _request_body_lines(operation: dict) -> list[str]:
    body = operation.get("requestBody") or {}
    content = body.get("content") or {}
    if not content:
        return []
    lines = ["请求体："]
    for media, spec in content.items():
        schema = (spec or {}).get("schema") or {}
        lines.append(f"- `{media}`：{_schema_label(schema) or '任意'}")
    return lines


def _response_lines(operation: dict) -> list[str]:
    lines: list[str] = []
    for code, resp in (operation.get("responses") or {}).items():
        if not isinstance(resp, dict):
            continue
        desc = resp.get("description", "")
        content = resp.get("content") or {}
        label = ""
        if content:
            first = next(iter(content.values())) or {}
            label = _schema_label((first or {}).get("schema") or {})
        lines.append(f"- `{code}` {desc}" + (f"（{label}）" if label else ""))
    return lines


def load_openapi(path: Path, root: Path) -> tuple[list, dict]:
    rel = path.resolve().relative_to(root).as_posix()
    data = json.loads(path.read_text(encoding="utf-8"))
    docs: list = []
    methods = {"get", "post", "put", "patch", "delete"}

    for api_path, item in (data.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() not in methods or not isinstance(operation, dict):
                continue
            summary = operation.get("summary") or ""
            description = operation.get("description") or ""
            lines = [
                f"{method.upper()} {api_path}",
                summary,
                description,
                "参数：",
                *(_param_lines(operation) or ["- 无"]),
                *_request_body_lines(operation),
                "响应：",
                *(_response_lines(operation) or ["- 未声明"]),
            ]
            page_content = "\n".join(line for line in lines if line != "")
            doc_id = f"{rel}#{method.upper()}-{api_path}"
            docs.extend(
                _emit(
                    doc_id=doc_id,
                    page_content=page_content,
                    metadata={
                        "doc_id": doc_id,
                        "path": rel,
                        "title": f"{method.upper()} {api_path}",
                        "heading": summary or f"{method.upper()} {api_path}",
                        "heading_path": f"API / {api_path}",
                        "kind": "api",
                        "module": "api",
                        "status": "current",
                        "start_line": 0,
                        "end_line": 0,
                        "parent_heading_path": f"API / {api_path}",
                        "parent_start": 0,
                        "parent_end": 0,
                        "read_mode": "chunk",
                        "method": method.upper(),
                        "api_path": api_path,
                    },
                )
            )

    return docs, _files_meta(path, rel, len(docs))


def load_corpus(root: Path | None = None) -> CorpusResult:
    """加载全部语料；单篇失败只记录 skipped，不影响其它文档。"""
    root = (root or config.ROOT).resolve()
    result = CorpusResult()

    for path in iter_markdown_files(root):
        rel = path.resolve().relative_to(root).as_posix()
        try:
            docs, meta = load_markdown(path, root)
        except Exception as exc:  # noqa: BLE001 —— 单篇坏文档不应拖垮整库
            result.skipped.append({"path": rel, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        if docs:
            result.documents.extend(docs)
            result.files[rel] = meta

    for rel_path, loader in (
        (config.SQL_SCHEMA_FILE, load_sql),
        (config.OPENAPI_FILE, load_openapi),
    ):
        path = root / rel_path
        if not path.is_file():
            result.skipped.append({"path": rel_path, "reason": "文件不存在"})
            continue
        try:
            docs, meta = loader(path, root)
        except Exception as exc:  # noqa: BLE001
            result.skipped.append({"path": rel_path, "reason": f"{type(exc).__name__}: {exc}"})
            continue
        if docs:
            result.documents.extend(docs)
            result.files[rel_path] = meta

    # 外部文档（Markdown / Word / Excel）：目录默认在运行时数据区，不存在就静默跳过。
    ext_docs, ext_files, ext_skipped = external.load_external(root)
    result.documents.extend(ext_docs)
    result.files.update(ext_files)
    result.skipped.extend(ext_skipped)

    return result
