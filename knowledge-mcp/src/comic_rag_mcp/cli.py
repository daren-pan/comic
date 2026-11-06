"""knowledge-mcp 命令行：doctor / index / search / stats。

MCP server 是给 Agent 用的；这个 CLI 是给人排查索引用的。两者共用同一套
retriever / indexer，不维护第二份逻辑。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from . import config, lexical, tokenizer


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_doctor(_args: argparse.Namespace) -> int:
    from .corpus import load_corpus
    from .indexer import read_manifest

    corpus = load_corpus()
    kinds = Counter(d.metadata.get("kind", "?") for d in corpus.documents)
    modules = Counter(d.metadata.get("module", "?") for d in corpus.documents)
    historical = sum(1 for d in corpus.documents if d.metadata.get("status") == "historical")
    manifest = read_manifest()

    print("comic-knowledge · 配置自检")
    print(f"  仓库根       {config.ROOT}")
    print(f"  索引目录     {config.INDEX_DIR}")
    print(f"  集合名       {config.collection_name()}")
    info = config.embedding_info()
    print(f"  embedding    {info['backend']} / {info['model']} / {info['dim']} 维")
    print(f"  切分         target={config.TARGET_CHARS} max={config.MAX_CHARS} "
          f"max_tokens={config.MAX_TOKENS} version={config.CHUNKER_VERSION}")
    tok = tokenizer.describe()
    print(f"  分词         {tok['backend']}（COMIC_KB_TOKENIZER={tok['chosen']}）"
          + (f" 用户词典={tok['userDict']}" if tok["userDict"] else " 无用户词典"))
    try:
        lex = lexical.stats()
        print(f"  词面索引     BM25 {lex['documents']} 篇 / {lex['terms']} 个词 / "
              f"avgdl={lex['avgdl']}（k1={lex['k1']} b={lex['b']}）")
    except Exception as exc:   # noqa: BLE001 —— 索引没建时不该让自检崩掉
        print(f"  词面索引     （不可用：{type(exc).__name__}: {exc}）")
    print(f"  语料         {len(corpus.files)} 个文件 / {len(corpus.documents)} 个 chunk "
          f"（historical {historical}）")
    print(f"  类型         {dict(kinds)}")
    print(f"  模块         {dict(modules)}")
    if manifest:
        counts = manifest.get("counts", {})
        print(f"  已建索引     {counts.get('documents', '?')} chunk / {counts.get('vectors', '?')} 向量 "
              f"@ {manifest.get('built_at', '?')}")
    else:
        print("  已建索引     （无 manifest，先跑 index）")
    if corpus.skipped:
        print(f"  跳过         {corpus.skipped}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from .corpus import load_corpus
    from .indexer import build_index, check_stale

    corpus = load_corpus()
    print(f"[index] 扫描 {len(corpus.files)} 个文件，切出 {len(corpus.documents)} 个 chunk")
    for item in corpus.skipped:
        print(f"[index] 跳过 {item['path']}：{item['reason']}")
    if not corpus.documents:
        print("[index] 没有可索引的文档", file=sys.stderr)
        return 1

    if args.check:
        report = check_stale(corpus=corpus)
        _print_json(report)
        if report["stale"]:
            print("[index] ⚠ 索引已过期，运行 bash scripts/dev.sh knowledge-index 重建")
            return 1
        print("[index] ✅ 索引与当前文档一致")
        return 0

    payload = build_index(corpus)
    print(
        f"[index] ✅ {payload['counts']['documents']} chunk / "
        f"{payload['counts']['vectors']} 向量 → {payload['collection']} "
        f"（{payload['elapsed_ms']}ms）"
    )
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from .retriever import search

    payload = search(
        args.query,
        top_k=args.top_k,
        kind=args.kind,
        module=args.module,
        include_historical=args.historical,
        mode=args.mode,
    )
    _print_json(payload)
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    from .retriever import read

    _print_json(read(args.doc_id))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from .retriever import stats

    _print_json(stats(detail=args.detail))
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from .eval_cases import CASES
    from .retriever import search

    passed = 0
    print(f"检索评测：{len(CASES)} 条，top_k={args.top_k}")
    for index, case in enumerate(CASES, 1):
        result = search(case['query'], top_k=args.top_k, mode=args.mode)
        hits = result.get("hits") or []
        paths = [hit["path"] for hit in hits]
        ok = any(path in case["expect"] for path in paths)
        passed += 1 if ok else 0
        mark = "✅" if ok else "❌"
        best = hits[0] if hits else {}
        print(
            f"{mark} {index:02d}. {case['query']}  "
            f"→ {best.get('path', '（无命中）')} "
            f"[{best.get('heading', '')}] {best.get('score', 0)}"
        )
        if not ok:
            print(f"     期望：{case['expect']}")
            print(f"     实际：{paths}")
    recall = passed / len(CASES) if CASES else 0.0
    print(f"\nRecall@{args.top_k}: {passed}/{len(CASES)} = {recall:.1%}")
    return 0 if recall >= args.min_recall else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="comic-knowledge-cli",
        description="项目知识库：配置自检 / 建索引 / 检索 / 统计",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="检查语料、embedding、索引状态")
    doctor.set_defaults(func=cmd_doctor)

    index = sub.add_parser("index", help="全量重建项目知识库")
    index.add_argument("--check", action="store_true", help="只检查是否过期，不重建")
    index.set_defaults(func=cmd_index)

    search = sub.add_parser("search", help="检索（JSON 输出）")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--kind", default=None)
    search.add_argument("--module", default=None)
    search.add_argument("--historical", action="store_true", help="包含历史稿")
    search.add_argument("--mode", choices=["hybrid", "vector", "lexical"], default=None,
                        help="检索模式：hybrid（默认）/ vector / lexical")
    search.set_defaults(func=cmd_search)

    read = sub.add_parser("read", help="按 doc_id 回读（JSON 输出）")
    read.add_argument("doc_id")
    read.set_defaults(func=cmd_read)

    stats = sub.add_parser("stats", help="索引摘要（JSON 输出）")
    stats.add_argument("--detail", action="store_true", help="附带完整 manifest")
    stats.set_defaults(func=cmd_stats)

    evaluate = sub.add_parser("eval", help="跑检索评测（Recall@k）")
    evaluate.add_argument("--top-k", type=int, default=5)
    evaluate.add_argument("--min-recall", type=float, default=0.8)
    evaluate.add_argument("--mode", choices=["hybrid", "vector", "lexical"], default=None,
                          help="检索模式，用于 A/B 对比")
    evaluate.set_defaults(func=cmd_eval)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认可能是 GBK；统一 UTF-8，避免中文路径/标题打印崩。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Chroma 的 Rust 绑定直接读系统临时目录；必须在任何 chromadb 导入之前。
    from comic_chat.runtime_env import prepare

    prepare()

    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
