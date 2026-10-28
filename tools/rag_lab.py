#!/usr/bin/env python
"""RAG 实验室命令行 —— 不启动服务就能把整条链路跑一遍。

用法（在仓库根目录）：

    python tools/rag_lab.py doctor              # 配置自检（当前用真模型还是占位向量）
    python tools/rag_lab.py index               # 重建索引（不需要 key）
    python tools/rag_lab.py search "问题"        # 只检索，看命中与分数（不需要 key）
    python tools/rag_lab.py ask "问题"           # 完整问答（需要 COMIC_LLM_API_KEY）

常用参数：

    --topk 6            检索取几条（默认 4）
    --kind faq          只检索 FAQ（或 comic 只检索作品）
    --json              输出原始 JSON（方便接 jq / 存文件对比）
    --no-context        ask 时不打印拼好的上下文

## 为什么 search 是最该常用的命令

`ask` 答得不对时，先用 `search` 看命中了什么：

- 命中的不是该命中的 → 问题在切分/向量化/检索参数，换模型没用
- 命中对了但答歪了 → 问题在 prompt 或生成模型

这个二分法能省掉大量「换个模型试试」的无效尝试。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# 项目约定：api-service 是「应用目录」不是可导入包（见其 pyproject.toml 注释），
# 所以这里手动把目录塞进 sys.path，之后才能 `import services...`。
sys.path.insert(0, str(REPO_ROOT / "api-service"))

# Windows 控制台默认可能是 GBK，画分数条用的方块字符不在 GBK 里 —— 统一切 UTF-8，
# 编码失败时用占位符而不是直接抛 UnicodeEncodeError 中断整个命令。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:  # pragma: no cover - 老终端不支持 reconfigure
    pass


def _bar(score: float, width: int = 10) -> str:
    """把 0~1 的分数画成方块条 —— 一眼看出「这条到底有多像」。"""
    score = max(0.0, min(1.0, score))
    filled = round(score * width)
    return "█" * filled + "░" * (width - filled)


_BACKEND_LABEL = {
    "hash": "hash 占位向量（非语义，仅验证链路）",
    "local": "本地语义模型（离线，效果接近线上）",
    "openai": "云端语义模型",
}


def _print_hits(result: dict) -> None:
    backend = result["backend"]
    print(f"\n检索：{result['question']}")
    print(f"后端：{backend} —— {_BACKEND_LABEL.get(backend, backend)}")
    if result.get("minScore") is not None:
        print(f"阈值：{result['minScore']}（低于此分数的候选已丢弃）")
    print(f"命中：{len(result['hits'])} 条 / {result['elapsedMs']}ms\n")

    for hit in result["hits"]:
        label = hit["kind"].upper()
        title = hit["title"] or (f"漫画#{hit['comicId']}" if hit["comicId"] else "")
        print(f"  {hit['score']:.3f}  {_bar(hit['score'])}  [{label}] {title}")
        print(f"         {hit['preview']}")
        print()


def cmd_doctor(args: argparse.Namespace) -> int:
    from services.chat.lab import settings

    info = settings.describe()
    print("RAG 实验室 · 配置自检\n")
    embed = info["embedding"]
    llm = info["llm"]
    print(f"  向量后端   {embed['backend']}  ({embed['model']}, {embed['dim']} 维)")
    print(f"  向量 key   {'已配置' if embed['hasKey'] else '未配置'}")
    print(f"  对话模型   {llm['model']}  ({llm['baseUrl']})")
    print(f"  对话 key   {'已配置' if llm['hasKey'] else '未配置 → ask 不可用，search 可用'}")
    print(f"  索引目录   {info['chromaDir']}")
    print(f"  集合名     {info['collection']}")
    print(f"  默认 topK  {info['topK']}")

    if embed["backend"] == "local":
        print(
            "\n  当前用本地语义模型 bge-small-zh（离线、免费）。效果够看「语义检索强在哪」，\n"
            "     但不如云端 text-embedding-v4；正式上线时配 COMIC_EMBED_API_KEY 再重建索引即可。"
        )
    elif embed["backend"] == "hash":
        print(
            "\n  ⚠️ 只有 hash 占位后端可用（未装 fastembed 且没有 embedding key），\n"
            "     检索结果只反映字面重合度，不能代表真实效果。\n"
            "     装 fastembed（pip install fastembed）或配 COMIC_EMBED_API_KEY 后重新 index 即可。"
        )
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from services.chat.lab.index import build_index

    print("开始重建索引…")
    stats = build_index()
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    print(
        f"\n完成：{stats['documents']} 个文档 "
        f"(FAQ {stats['faq']} + 漫画 {stats['comics']}) "
        f"→ {stats['vectors']} 条向量，耗时 {stats['elapsedMs']}ms"
    )
    print(f"集合：{stats['collection']}    后端：{stats['backend']} ({stats['embeddingModel']})")
    print(f"落盘：{stats['storedAt']}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from services.chat.lab.chain import search

    result = search(args.question, k=args.topk, kind=args.kind)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    _print_hits(result)
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from services.chat.lab.chain import ask

    try:
        result = ask(args.question, k=args.topk, kind=args.kind)
    except RuntimeError as exc:
        print(f"\n[无法问答] {exc}\n", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    _print_hits({"question": args.question, **{k: result[k] for k in ("backend", "hits")},
                 "elapsedMs": result["elapsedMs"]["retrieve"]})
    print("─" * 60)
    print(f"回答（{result['model']}）：\n")
    print(result["answer"])
    print(
        f"\n耗时：检索 {result['elapsedMs']['retrieve']}ms / "
        f"生成 {result['elapsedMs']['llm']}ms / 合计 {result['elapsedMs']['total']}ms"
    )
    if args.no_context is False and "context" in result:
        print("\n" + "─" * 60)
        print("实际发给模型的参考资料（context）：\n")
        print(result["context"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rag_lab", description="RAG 实验室：索引 / 检索 / 问答 / 自检"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="配置自检")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("index", help="重建索引")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("search", help="只检索，不调生成模型")
    p.add_argument("question", help="用户问题")
    p.add_argument("--topk", type=int, default=None, help="取几条（默认 4）")
    p.add_argument("--kind", choices=["faq", "comic"], default=None, help="限定数据源类型")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("ask", help="完整问答（需要对话模型 key）")
    p.add_argument("question", help="用户问题")
    p.add_argument("--topk", type=int, default=None, help="取几条（默认 4）")
    p.add_argument("--kind", choices=["faq", "comic"], default=None, help="限定数据源类型")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--no-context", action="store_true", help="不打印拼好的上下文")
    p.set_defaults(func=cmd_ask)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
