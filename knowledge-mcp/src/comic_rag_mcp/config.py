"""knowledge-mcp 的运行期配置（纯常量 + 纯函数，无副作用）。

## 这层为什么独立

MCP 服务和 `chat-service` 共用 embedding / Chroma 技术栈，但**不能共用索引**：

- chat 的 `comic_kb_*` 是 FAQ + 漫画作品；
- 本服务的 `project_kb_*` 是项目文档 / schema / OpenAPI。

所以集合名、索引目录、切分版本都在这里单独定义。embedding 后端仍复用
`comic_chat.rag.settings` 的选择逻辑（local bge / openai / hash），避免两套模型配置。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

#: 仓库根：默认从本文件位置推导（`knowledge-mcp/src/comic_rag_mcp/config.py` → 上三级）。
#: 打包/容器态必须用 `COMIC_RAG_ROOT` 显式指定。
_DEFAULT_ROOT = Path(__file__).resolve().parents[3]
ROOT = Path(os.environ.get("COMIC_RAG_ROOT", "").strip() or _DEFAULT_ROOT).resolve()

#: 本知识库的 Chroma 目录（与 chat 的 `rag_lab` 分开）。
INDEX_DIR = Path(
    os.environ.get("COMIC_RAG_INDEX_DIR", "").strip()
    or (ROOT / "crawler-service" / "data" / "project_rag")
).resolve()
MANIFEST_FILE = INDEX_DIR / "manifest.json"

#: 集合名前缀；最终名字带 embedding + 切分版本指纹。
COLLECTION_PREFIX = "project_kb"

#: `message` 表的独立索引：**与 docs 分开**，避免消息增量影响文档全量重建。
MESSAGE_MANIFEST_FILE = INDEX_DIR / "message_manifest.json"
MESSAGE_COLLECTION_PREFIX = "project_kb_message"
#: 消息文本模板/清洗规则版本；改模板或清洗规则必须 +1。
MESSAGE_INDEX_VERSION = 1
#: 单条消息进向量库的最大字符数；正文太长只保留前段，完整内容仍可在库里查。
MESSAGE_MAX_CHARS = int(os.environ.get("COMIC_RAG_MESSAGE_MAX_CHARS", "1200"))
#: 消息检索最低余弦相似度；消息短、同义表达多，阈值比文档低一些。
MESSAGE_MIN_SCORE = float(os.environ.get("COMIC_RAG_MESSAGE_MIN_SCORE", "0.30"))
#: 内部只读接口默认地址（MCP indexer 用服务令牌访问，不直连 MySQL）。
MESSAGE_API_URL = (
    os.environ.get("COMIC_KNOWLEDGE_MESSAGE_URL", "").strip()
    or "http://127.0.0.1:8000/api/internal/knowledge/messages"
)
MESSAGE_TIMEOUT_SECONDS = float(os.environ.get("COMIC_KNOWLEDGE_MESSAGE_TIMEOUT", "10"))

#: 切分/读取契约版本。**改 chunk 内容、元数据或 read 语义必须 +1**。
#:
#: v2（2026-11-03）：
#:   - Markdown chunk 增加 `read_mode="lines"`；
#:   - `read_knowledge` 回读 section 自身，不再回溯到可能只有引子的 H2。
#: v3（2026-11-06）：新增外部文档源（Markdown / Word / Excel）：
#:   - 新 kind：`ext_md` / `ext_word` / `ext_excel`，module 统一 `external`；
#:   - Word / Excel 的 chunk 标 `read_mode="chunk"`（原始文件不是纯文本、没有行号可回读）；
#:   - 集合名随指纹变化，旧集合保留，重建后自动生效。
#: 它进集合名指纹，保证不会拿旧索引配新读法。
CHUNKER_VERSION = 3

#: chunk 目标 / 硬上限（中文字符，保守近似 token；最终还会用 tokenizer 复核）。
TARGET_CHARS = int(os.environ.get("COMIC_RAG_TARGET_CHARS", "400"))
MAX_CHARS = int(os.environ.get("COMIC_RAG_MAX_CHARS", "500"))
MIN_CHARS = int(os.environ.get("COMIC_RAG_MIN_CHARS", "120"))

#: bge-small-zh-v1.5 的 max_position_embeddings = 512；留 32 token 给 heading/特殊 token。
MAX_TOKENS = int(os.environ.get("COMIC_RAG_MAX_TOKENS", "480"))

#: 长段落被迫切开时的重叠字符数；只在 `_hard_split` 里用，不适用于代码/表格。
OVERLAP_CHARS = int(os.environ.get("COMIC_RAG_OVERLAP_CHARS", "50"))

#: 检索默认值与阈值（阈值只作用在向量结果上；后续可用评测调）。
TOP_K = int(os.environ.get("COMIC_RAG_TOP_K", "5"))
MIN_SCORE = float(os.environ.get("COMIC_RAG_MIN_SCORE", "0.45"))

# ---- 词面检索（BM25，阶段二 P2.1：只建索引，尚未接入 search）----
#
# ⚠️ 这三个是**打分刻度**参数，不是普通开关：
#   · k1 控制词频饱和（越大越"词出现得多就涨分"）；
#   · b  控制长度归一（0=不惩罚长文，1=完全按长度摊平）；
#   · TOP_K 是候选条数，P2.2 融合时取 `top_k × 4` 量级。
# 换分词器（jieba ↔ bigram）后分数分布会整体变化，**必须重新标定并重跑评估集**。
LEXICAL_TOP_K = int(os.environ.get("COMIC_KB_LEXICAL_TOP_K", "20"))
LEXICAL_K1 = float(os.environ.get("COMIC_KB_LEXICAL_K1", "1.5"))
LEXICAL_B = float(os.environ.get("COMIC_KB_LEXICAL_B", "0.75"))

#: 双路总开关（`0` 时 `search()` 完全回到纯向量行为，用于回退与对照）。
HYBRID_ENABLED = os.environ.get("COMIC_KB_HYBRID", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

#: RRF 的平滑常数（论文默认 60）。它几乎不影响排序，只影响分数的绝对量级；
#: **不要靠调它来"提分"** —— 融合只排先后，不产生"相关性判断"。
RRF_K = int(os.environ.get("COMIC_KB_RRF_K", "60"))

#: `read_knowledge` 返回父小节时的最大字符数，防止一次把整篇 37KB 文档塞给 Agent。
READ_MAX_CHARS = int(os.environ.get("COMIC_RAG_READ_MAX_CHARS", "6000"))

#: 已知历史稿：文件头自己写了“不是现状”的文档。默认不检索，除非调用方显式要求。
STATUS_OVERRIDES = {
    "docs/architecture.md": "historical",
    # guazi 只有 fixtures、没有适配器；收进来只会让“新增源站”类问题混淆。
    "crawler-service/src/comic_crawler/sources/guazi/README.md": "historical",
}

#: 扫描时整目录跳过的名字（路径任一段命中即跳过）。
EXCLUDE_DIR_PARTS = {
    ".git",
    ".python",
    ".venv",
    "node_modules",
    "__pycache__",
    "logs",
    "backup",
    "build",
    "dist",
    "data",
    "fastembed_cache",
    ".workbuddy",
    ".agent-shared",
    ".idea",
    ".vscode",
}

#: 明确跳过的文件（相对仓库根，POSIX 分隔符）。
EXCLUDE_FILES = {
    "crawler-service/src/comic_crawler/sources/guazi/README.md",
}

#: 明确跳过的目录前缀（相对仓库根）。`docs/tasks/` 是需求任务档案 / 模板，
#: 不是稳定的项目知识；留着会把“管理台任务记录在哪个表”这类问题带偏。
EXCLUDE_PREFIXES = ("docs/tasks/",)
#: 评测答案（逐条列出全部黄金问题）不进语料 —— 它会把问题原句带进索引，形成自污染。
EXCLUDE_SUFFIXES = ("/docs/EVAL.md",)

#: Markdown 之外的结构化知识源。
SQL_SCHEMA_FILE = "comic-core/sql/mysql_schema.sql"
OPENAPI_FILE = "api-service/openapi.json"

# ---- 外部文档（阶段一：只有 Markdown / Word / Excel）----
#
# 与「仓库自带的工程文档」分开：那批是**代码仓库的说明书**，这批是**用户自己的资料**
# （手册、规范、台账）。两者共用同一个集合，但用 `kind` / `module` 区分，检索时可以过滤。
#
# 目录默认放在**运行时数据目录**（不进 git）：`crawler-service/data/kb_docs/`。
# 用 `COMIC_KB_DOCS_DIR` 可以指到任意绝对路径（比如 `D:/手册`）。
KB_DOCS_DIRNAME = ("crawler-service", "data", "kb_docs")

#: 阶段一支持的扩展名。**加格式先加解析器，再往这里加**（PDF / HTML 留到后续阶段）。
EXTERNAL_SUFFIXES = (".md", ".docx", ".xlsx")

#: 扩展名 → (`kind`, `module`)。`kind` 进检索过滤，`module` 统一标 `external`，
#: 这样 `module=external` 能一次拿到全部外部资料，`kind=...` 又能只看某一种格式。
EXTERNAL_KIND = {
    ".md": "ext_md",
    ".docx": "ext_word",
    ".xlsx": "ext_excel",
}
EXTERNAL_MODULE = "external"

#: Excel 单表最多读多少行。超过就截断并在 `skipped` 里记一笔 —— 防止一张几万行的
#: 台账把索引撑爆（一行一个 chunk，2 万行就是 2 万个向量）。
XLSX_MAX_ROWS = int(os.environ.get("COMIC_KB_XLSX_MAX_ROWS", "2000"))
#: Excel 单元格最大字符数；超长截断（合并单元格 / 长备注会把 chunk 撑大）。
XLSX_MAX_CELL_CHARS = int(os.environ.get("COMIC_KB_XLSX_CELL_CHARS", "300"))
#: Excel 最多读多少列；超出的列直接丢弃（宽表对检索没有意义，只会稀释语义）。
XLSX_MAX_COLS = int(os.environ.get("COMIC_KB_XLSX_MAX_COLS", "30"))
#: Word 表格单元格最大字符数（表格要转成 Markdown 行，太长的单元格会把块撑爆）。
DOCX_MAX_CELL_CHARS = int(os.environ.get("COMIC_KB_DOCX_CELL_CHARS", "200"))


def kb_docs_dir(root: Path) -> Path:
    """外部文档目录：`COMIC_KB_DOCS_DIR` 优先（相对路径按仓库根解析），否则用默认位置。

    做成函数而不是模块级常量：`corpus.load_corpus(root)` 支持传入任意根目录（单测用
    临时目录），目录解析必须跟着这个 root 走，不能钉死在 `config.ROOT` 上。
    """
    env = os.environ.get("COMIC_KB_DOCS_DIR", "").strip()
    if env:
        path = Path(env)
        return (path if path.is_absolute() else root / path).resolve()
    return (root.joinpath(*KB_DOCS_DIRNAME)).resolve()


def relpath(path: Path) -> str:
    """绝对路径 → 仓库内相对路径（POSIX 分隔符）。"""
    return path.resolve().relative_to(ROOT).as_posix()


def status_of(rel: str) -> str:
    """文档状态：`current` / `historical`。"""
    return STATUS_OVERRIDES.get(rel, "current")


def collection_name() -> str:
    """当前 embedding + 切分配置对应的 Chroma 集合名。

    与 chat 的 `comic_kb_*` 用同一套「配置指纹」思路：换模型 / 换切分规则自动落到
    新集合，旧索引保留，不会把不同语义空间的向量混在一起。
    """
    from comic_chat.rag import settings

    fingerprint = (
        f"{settings.embedding_backend()}:{settings.embedding_model_name()}"
        f":{settings.embedding_dim()}:chunk{CHUNKER_VERSION}"
    )
    suffix = hashlib.md5(fingerprint.encode("utf-8")).hexdigest()[:8]
    return f"{COLLECTION_PREFIX}_{suffix}"


def embedding_info() -> dict:
    """给 `doctor` / `stats` 用的 embedding 摘要。"""
    from comic_chat.rag import settings

    return {
        "backend": settings.embedding_backend(),
        "model": settings.embedding_model_name(),
        "dim": settings.embedding_dim(),
    }


def message_collection_name() -> str:
    """message 数据源的独立 Chroma 集合名（与 docs 的 `project_kb_*` 分开）。"""
    from comic_chat.rag import settings

    fingerprint = (
        f"{settings.embedding_backend()}:{settings.embedding_model_name()}"
        f":{settings.embedding_dim()}:message{MESSAGE_INDEX_VERSION}"
    )
    suffix = hashlib.md5(fingerprint.encode("utf-8")).hexdigest()[:8]
    return f"{MESSAGE_COLLECTION_PREFIX}_{suffix}"
