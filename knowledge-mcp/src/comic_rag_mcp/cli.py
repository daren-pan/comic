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

    payload = build_index(corpus, incremental=not getattr(args, "full", False))
    changes = payload.get("changes") or {}
    tail = ""
    if payload.get("mode") == "incremental":
        tail = (
            f"  增量：新增 {changes.get('added', 0)} / 更新 {changes.get('updated', 0)} / "
            f"删除 {changes.get('deleted', 0)} / 跳过 {changes.get('skipped', 0)}"
        )
    print(
        f"[index] ✅ {payload['counts']['documents']} chunk / "
        f"{payload['counts']['vectors']} 向量 → {payload['collection']} "
        f"（{payload['elapsed_ms']}ms，{payload.get('mode', 'full')}）{tail}"
    )
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from .retriever import MODE_LABELS, mode_label, normalize_mode, search

    mode = normalize_mode(args.mode)
    payload = search(
        args.query,
        top_k=args.top_k,
        kind=args.kind,
        module=args.module,
        include_historical=args.historical,
        mode=mode,
    )
    if not args.explain:
        _print_json(payload)
        return 0

    hits = payload.get("hits") or []
    cands = payload.get("candidates") or {}
    source_names = {"vector": "语义", "lexical": "字面"}
    print(
        f"查询：{payload.get('query')}   "
        f"模式：{mode_label(mode)}（{mode}）   "
        f"候选：语义 {cands.get('vector', 0)} / 字面 {cands.get('lexical', 0)}   "
        f"耗时：{payload.get('elapsed_ms')}ms"
    )
    print(
        f"{'#':>2}  {'score':>7}  {'语义':>6}  {'字面':>7}  {'RRF':>7}  "
        f"{'来源':<12}  {'命中词':<20}  路径 / 小节"
    )
    for index, hit in enumerate(hits, 1):
        lexical_score = hit.get("lexical_score")
        rrf = hit.get("rrf")
        sources = ",".join(source_names.get(s, s) for s in (hit.get("sources") or []))
        print(
            f"{index:>2}  {hit.get('score', 0):>7.4f}  {hit.get('vector_score', 0):>6.3f}  "
            f"{(lexical_score if lexical_score is not None else 0):>7.3f}  "
            f"{(rrf if rrf is not None else 0):>7.4f}  "
            f"{sources:<12}  "
            f"{','.join(hit.get('matched_terms') or [])[:20]:<20}  "
            f"{hit.get('path')} [{hit.get('heading', '')[:24]}]"
        )
    if not hits:
        print("（没有命中）")
    print(
        "\n提示：score 的含义随模式变化（"
        f"{MODE_LABELS['vector']}=余弦、{MODE_LABELS['lexical']}=BM25、"
        f"{MODE_LABELS['hybrid']}=RRF 分），比对时看『语义』列。"
    )
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
    """评测只看两件事：**答案进没进前 5 / 前 10**。

    不看 Top-1 / MRR / nDCG —— 本项目的用法是把 top-k 一起交给生成侧，
    "排第一"没有实际价值，反而会诱导去调一堆没有泛化性的排序技巧。
    """
    from .eval_cases import CASES
    from .metrics import rank_of_first_hit
    from .retriever import mode_label, normalize_mode, search

    mode = normalize_mode(args.mode)
    depth = max(int(args.top_k), 10)
    total = len(CASES)

    if not args.json:
        print(
            f"检索评测：{total} 条   取前 {depth} 条   模式={mode_label(mode)}（{mode}）"
            f"   分词={tokenizer.backend()}"
        )

    rows: list[dict] = []
    hit5 = hit10 = 0
    for index, case in enumerate(CASES, 1):
        result = search(case["query"], top_k=depth, mode=mode)
        hits = result.get("hits") or []
        paths = [hit["path"] for hit in hits]
        rank5 = rank_of_first_hit(paths, case["expect"], 5)
        rank10 = rank_of_first_hit(paths, case["expect"], 10)
        hit5 += 1 if rank5 else 0
        hit10 += 1 if rank10 else 0
        rows.append(
            {
                "query": case["query"],
                "expect": list(case["expect"]),
                "paths": paths,
                "in5": bool(rank5),
                "in10": bool(rank10),
                "rank": rank5 or rank10,
            }
        )
        if args.json:
            continue

        mark = "✅" if rank5 else ("🟡" if rank10 else "❌")
        if args.detail:
            print(f"\n{mark} {index:02d}. {case['query']}")
            print(
                f"     前5={'是' if rank5 else '否'}  前10={'是' if rank10 else '否'}"
                f"   名次={rank5 or rank10 or '—'}"
            )
            for position, hit in enumerate(hits, 1):
                ok = "✓" if hit["path"] in case["expect"] else " "
                print(
                    f"       {position}.{ok} {hit.get('score', 0):<8} "
                    f"{hit.get('path')} [{hit.get('heading', '')[:26]}] "
                    f"{','.join(hit.get('sources') or [])}"
                )
        else:
            print(f"{mark} {index:02d}. {case['query']}   名次={rank5 or rank10 or '—'}")
        if not rank10:
            print(f"     期望：{case['expect']}")
            print(f"     实际：{paths}")

    if args.json:
        _print_json({"mode": mode, "recall@5": hit5, "recall@10": hit10, "cases": rows})
    else:
        print("\n" + "─" * 62)
        print(f"Recall@5  = {hit5}/{total} = {hit5 / total:.1%}")
        print(f"Recall@10 = {hit10}/{total} = {hit10 / total:.1%}")
    return 0 if hit5 / total >= args.min_recall else 1


def cmd_ask(args: argparse.Namespace) -> int:
    """把检索结果渲染成人能直接看的样子（一条问题一段）。

    与 `search` 的区别：`search` 给 JSON / 分数表（排查用），`ask` 给"答案"
    （路径 + 小节 + 摘要），多个问题一次问完。
    """
    from .retriever import search

    for query in args.questions:
        payload = search(query, top_k=args.top_k, mode=args.mode)
        hits = payload.get("hits") or []
        print(
            f"\n问：{query}    [{payload.get('mode')} · {tokenizer.backend()} · "
            f"{payload.get('elapsed_ms')}ms]"
        )
        if not hits:
            print("  （知识库里没有匹配内容）")
            continue
        for position, hit in enumerate(hits, 1):
            lexical_score = hit.get("lexical_score")
            print(f" {position}. {hit.get('path')} › {hit.get('heading')}")
            print(
                f"    向量 {hit.get('vector_score', 0):.3f} · "
                f"词面 {(lexical_score if lexical_score is not None else 0):.2f} · "
                f"来源 {','.join(hit.get('sources') or []) or '—'}"
            )
            snippet = (hit.get("snippet") or "").replace("\n", " ").strip()
            if snippet:
                print(f"    {snippet[:120]}…" if len(snippet) > 120 else f"    {snippet}")
    return 0


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
    index.add_argument(
        "--full", action="store_true",
        help="强制全量重建（默认只重算改动过的文件；切分/embedding 变了会自动全量）",
    )
    index.set_defaults(func=cmd_index)

    search = sub.add_parser("search", help="检索（JSON 输出）")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--kind", default=None)
    search.add_argument("--module", default=None)
    search.add_argument("--historical", action="store_true", help="包含历史稿")
    search.add_argument(
        "--mode", default=None, metavar="模式",
        help="检索模式：混合检索（默认）/ 语义检索 / 字面检索；也接受 hybrid/vector/lexical",
    )
    search.add_argument("--explain", action="store_true",
                        help="人类可读表格：每条的分数构成、来源、命中词")
    search.set_defaults(func=cmd_search)

    ask = sub.add_parser("ask", help="直接问（人看的答案：路径 / 小节 / 摘要）")
    ask.add_argument("questions", nargs="+", help="一个或多个问题")
    ask.add_argument("--top-k", type=int, default=3)
    ask.add_argument(
        "--mode", default=None, metavar="模式",
        help="检索模式：混合检索（默认）/ 语义检索 / 字面检索",
    )
    ask.set_defaults(func=cmd_ask)

    read = sub.add_parser("read", help="按 doc_id 回读（JSON 输出）")
    read.add_argument("doc_id")
    read.set_defaults(func=cmd_read)

    stats = sub.add_parser("stats", help="索引摘要（JSON 输出）")
    stats.add_argument("--detail", action="store_true", help="附带完整 manifest")
    stats.set_defaults(func=cmd_stats)

    evaluate = sub.add_parser("eval", help="跑检索评测（Recall / MRR / nDCG）")
    evaluate.add_argument("--top-k", type=int, default=5)
    evaluate.add_argument("--min-recall", type=float, default=0.8,
                          help="Recall 低于它就以非 0 退出（接 CI 用）")
    evaluate.add_argument(
        "--mode", default=None, metavar="模式",
        help="检索模式，用于 A/B 对比：混合检索 / 语义检索 / 字面检索",
    )
    evaluate.add_argument("--detail", action="store_true",
                          help="逐题列出全部命中与名次，人工核对用")
    evaluate.add_argument("--json", action="store_true", help="只输出 JSON（存基线 / 接脚本）")
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
    try:
        return int(args.func(args))
    except ValueError as exc:
        # 参数层面的错误（模式名、doc_id、query 为空）不该甩 traceback。
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
