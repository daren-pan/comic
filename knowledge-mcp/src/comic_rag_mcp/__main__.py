"""`python -m comic_rag_mcp`：stdio MCP 入口。

⚠️ `runtime_env.prepare()` 必须在导入 `.server` 之前执行：server → retriever →
indexer → `langchain_chroma` 会加载 Chroma 的 Rust 绑定，它直接读系统临时目录。
"""
from __future__ import annotations


def main() -> None:
    from comic_chat.runtime_env import prepare

    prepare()

    from .server import mcp

    mcp.run()


if __name__ == "__main__":
    main()
