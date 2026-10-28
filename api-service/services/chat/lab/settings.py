"""RAG 实验室的配置读取（**纯常量 + 纯函数，无副作用**）。

## 为什么参数都从环境变量读，且带默认值

实验室是「拿来就跑」的东西：不该为了跑一次 demo 去改 `.env` 或代码。所以这里全部
「有默认值 + 只在缺 key 时才提示」。生产化的客服模块（`services/chat/` 后续的主链路）
会换成 `app_setting` 表存运行期开关，这里的做法只适用于 lab。

## 为什么 embedding 默认指向通义，而不是 DeepSeek

**DeepSeek 没有 embedding 接口**（`/embeddings` 端点不存在，调用会 400）—— 这是实测结论，
不是猜测。所以向量化必须另找一家：默认阿里百炼的 `text-embedding-v4`，它走 OpenAI 兼容
协议，能和对话模型共用同一个 `langchain_openai` 客户端。

## 没有 key 时怎么办：降级成 `hash` 后端

`EMBED_API_KEY` 为空 → 自动用本地字符 n-gram 哈希伪向量（见 `embeddings.py`）。
目的是**让整条链路先跑通**（加载 → 切分 → 入库 → 检索 → 拼 prompt），拿到 key 后
只需补环境变量、重建一次索引，代码一行不改。

⚠️ hash 后端产出的**不是语义向量**，是「字面重合度」向量 —— 检索结果不能代表真实效果。
这一点在 `embeddings.py` 的模块注释里写清楚了，运行时也会在输出里打印警告。
"""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path

from comic_core.paths import DATA_ROOT

#: 本模块所在目录（`api-service/services/chat/lab/`）
LAB_DIR = Path(__file__).resolve().parent

# 本地配置文件：`lab/.env`（已在 .gitignore 里，不会提交）。用它填 key，免得每次 export。
# `override=False` —— 已有的环境变量优先，部署时仍走真正的环境变量，这里只做本地补位。
try:
    from dotenv import load_dotenv

    load_dotenv(LAB_DIR / ".env", override=False)
except ImportError:  # python-dotenv 没装时静默跳过，纯环境变量也能跑
    pass

#: 非结构化知识源（按 `##` 切分，见 `index.py`）
FAQ_FILE = LAB_DIR / "knowledge" / "faq.md"

#: 向量库落盘目录。
#: ⚠️ 必须落在 `DATA_ROOT` 下 —— 它正是容器里 bind 到宿主的那块目录（`/data`），
#: 否则容器一重启索引就没了（Chroma 不落盘 = 纯内存，进程结束数据消失）。
CHROMA_DIR = DATA_ROOT / "rag_lab"

#: Chroma 集合名。**换 embedding 模型必须换集合名或重建** —— 不同模型的向量不在同一个
#: 空间里，混着查会得到毫无意义的结果（维度甚至可能对不上，直接报错）。
COLLECTION = "comic_kb"

# ---- 对话模型（生成答案）----
# ⚠️ `base_url` **不要带 `/chat/completions`**：OpenAI 兼容客户端会自己拼这一段。
# 写成完整端点会变成 `.../v1/chat/completions/chat/completions` → 404。
LLM_BASE_URL = os.environ.get(
    "COMIC_LLM_BASE_URL", "https://opencode.ai/zen/go/v1"
).strip()
LLM_API_KEY = os.environ.get("COMIC_LLM_API_KEY", "").strip()
#: ⚠️ `deepseek-chat` / `deepseek-reasoner` 已于 2026-07-24 退役。
#: 这里用的是 OpenCode Go 网关上的模型 ID（对应 DeepSeek V4.1 Flash）。
LLM_MODEL = os.environ.get("COMIC_LLM_MODEL", "deepseek-v4.1-flash").strip()
LLM_TEMPERATURE = float(os.environ.get("COMIC_LLM_TEMPERATURE", "0.3"))

#: OpenCode Go 网关**强制**要求这两个请求头（缺了直接 400 `MissingSessionID`）：
#:   · `x-opencode-session`：每次会话一个稳定 ID，网关据此做路由与 prompt 缓存；
#:   · `User-Agent`：必须自报身份，不能用 `openai-python` 这类通用 SDK 名
#:     （官方明确写了会监控滥用）。
#: 换成别的厂商（DeepSeek 官方 / 通义）时，多带这两个头也不会报错，会被忽略。
LLM_SESSION_HEADER = "x-opencode-session"
LLM_USER_AGENT = os.environ.get("COMIC_LLM_USER_AGENT", "comic-rag-lab/1.0").strip()

# ---- 向量模型（检索用）----
EMBED_BASE_URL = os.environ.get(
    "COMIC_EMBED_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
).strip()
EMBED_API_KEY = os.environ.get("COMIC_EMBED_API_KEY", "").strip()
EMBED_MODEL = os.environ.get("COMIC_EMBED_MODEL", "text-embedding-v4").strip()

#: 向量维度（**仅 `openai` 后端使用**）。换模型时要跟着改（`text-embedding-v4` 支持 1024/768/… 多档，默认取 1024）。
#: 本地后端用自己的模型维度（见 `LOCAL_DIM`），不受这个值影响。
EMBED_DIM = int(os.environ.get("COMIC_EMBED_DIM", "1024"))

#: 本地语义模型（`local` 后端，离线、免费、不需要 key）。
#: `bge-small-zh-v1.5` 是中文小模型里的性价比首选：512 维、约 90MB、CPU 上几十毫秒一条。
#: 效果不及 `text-embedding-v4`，但**远好于 hash 占位**，足够看清「语义检索到底强在哪」。
LOCAL_MODEL = os.environ.get("COMIC_EMBED_LOCAL_MODEL", "BAAI/bge-small-zh-v1.5").strip()
LOCAL_DIM = 512

#: 检索默认取几条。4 是经验值：3 条常常不够（一个问题的答案分散在两节 FAQ 里），
#: 8 条以上开始稀释 prompt、拉低答案质量。
TOP_K = int(os.environ.get("COMIC_CHAT_TOP_K", "4"))


@lru_cache(maxsize=1)
def local_available() -> bool:
    """本地语义模型是否可用（装了 `fastembed` 才可用）。

    用函数而不是模块级常量：`import fastembed` 会连带加载 onnxruntime（几百毫秒），
    放在模块导入期会拖慢 api 启动 —— 而这个能力只在真正建/查索引时才需要。
    """
    try:
        import fastembed  # noqa: F401
    except Exception:
        return False
    return True


def embedding_backend() -> str:
    """当前会走哪个 embedding 后端。

    优先级：`openai`（配了 key，效果最好）→ `local`（本地模型，真语义、离线）
    → `hash`（都没有时的占位，只验证链路）。

    注意 `local` 排在 `hash` 前面：只要装了 fastembed，就默认用真语义模型而不是占位向量 ——
    「有真货就别用假货」比「按配置开关切换」更符合直觉，也避免忘了配环境变量时
    看到一堆假的检索结果。
    """
    if EMBED_API_KEY:
        return "openai"
    if local_available():
        return "local"
    return "hash"


def embedding_dim() -> int:
    """当前后端的向量维度（集合名指纹与自检展示都要用）。"""
    backend = embedding_backend()
    if backend == "openai":
        return EMBED_DIM
    if backend == "local":
        return LOCAL_DIM
    return EMBED_DIM


def embedding_model_name() -> str:
    """当前后端的模型标识（展示用）。"""
    backend = embedding_backend()
    if backend == "openai":
        return EMBED_MODEL
    if backend == "local":
        return LOCAL_MODEL
    return "hash-ngram"


def collection_name() -> str:
    """当前配置对应的 Chroma 集合名（`comic_kb_<配置指纹>`）。

    ⚠️ **集合名必须跟着 embedding 配置走**，不能固定成 `comic_kb`：换了模型还往同一个
    集合里写，维度不同的直接报错；维度碰巧相同的更糟 —— 查询向量和库里向量不在同一个
    语义空间，**检索结果是噪声，而且不报错**。

    所以名字由 `后端 + 模型 + 维度` 算一个短哈希。改任何一项，自动落到新集合，旧索引
    原样保留（想清理就删目录）。这是「换模型必须重建索引」这条规则的工程化兜底：
    **与其写文档提醒人别忘，不如让忘了也不出错。**
    """
    fingerprint = f"{embedding_backend()}:{embedding_model_name()}:{embedding_dim()}"
    suffix = hashlib.md5(fingerprint.encode("utf-8")).hexdigest()[:6]
    return f"{COLLECTION}_{suffix}"


def llm_ready() -> bool:
    """对话模型是否可用（没有 key 时 `chain.ask()` 会抛可读的中文错误）。"""
    return bool(LLM_API_KEY)


def describe() -> dict:
    """打印/返回当前配置摘要 —— CLI 的 `doctor` 子命令与接口的自检用。

    `apiKey` 只给布尔值，**不回显任何片段**：这个 dict 会进 HTTP 响应。
    """
    backend = embedding_backend()
    return {
        "embedding": {
            "backend": backend,
            "model": embedding_model_name(),
            "baseUrl": EMBED_BASE_URL if backend == "openai" else "",
            "hasKey": bool(EMBED_API_KEY),
            "dim": embedding_dim(),
        },
        "llm": {
            "model": LLM_MODEL,
            "baseUrl": LLM_BASE_URL,
            "hasKey": llm_ready(),
        },
        "chromaDir": str(CHROMA_DIR),
        "collection": collection_name(),
        "topK": TOP_K,
    }
