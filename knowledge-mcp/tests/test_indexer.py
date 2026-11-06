"""索引新鲜度 / 就绪检查单测。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from comic_rag_mcp import config
from comic_rag_mcp.corpus import load_corpus
from comic_rag_mcp.indexer import check_stale


def _manifest_for(corpus) -> dict:
    return {
        "version": 2,
        "built_at": "2026-11-03T00:00:00",
        "collection": config.collection_name(),
        "embedding": config.embedding_info(),
        "chunker_version": config.CHUNKER_VERSION,
        "files": corpus.files,
        "counts": {
            "files": len(corpus.files),
            "documents": len(corpus.documents),
            "vectors": len(corpus.documents),
        },
    }


class StaleTest(unittest.TestCase):
    def test_fresh_then_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# 根\n\n## 一\n\n正文。\n", encoding="utf-8")
            corpus = load_corpus(root)
            manifest = _manifest_for(corpus)

            report = check_stale(corpus=corpus, manifest=manifest)
            self.assertFalse(report["stale"], report)
            self.assertEqual(report["changed_files"], [])

            (root / "README.md").write_text("# 根\n\n## 一\n\n改过的正文。\n", encoding="utf-8")
            changed_corpus = load_corpus(root)
            report = check_stale(corpus=changed_corpus, manifest=manifest)
            self.assertTrue(report["stale"])
            self.assertIn("files-changed", report["reasons"])
            self.assertIn("README.md", report["changed_files"])

    def test_added_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# 根\n\n正文。\n", encoding="utf-8")
            corpus = load_corpus(root)
            manifest = _manifest_for(corpus)

            (root / "docs").mkdir()
            (root / "docs" / "a.md").write_text("# A\n\n正文。\n", encoding="utf-8")
            report = check_stale(corpus=load_corpus(root), manifest=manifest)
            self.assertIn("files-added", report["reasons"])
            self.assertIn("docs/a.md", report["new_files"])

            (root / "README.md").unlink()
            report = check_stale(corpus=load_corpus(root), manifest=manifest)
            self.assertIn("files-removed", report["reasons"])
            self.assertIn("README.md", report["missing_files"])

    def test_version_or_collection_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# 根\n\n正文。\n", encoding="utf-8")
            corpus = load_corpus(root)
            manifest = _manifest_for(corpus)
            manifest["chunker_version"] = 1
            report = check_stale(corpus=corpus, manifest=manifest)
            self.assertTrue(report["stale"])
            self.assertIn("chunker-version-changed", report["reasons"])

            manifest = _manifest_for(corpus)
            manifest["collection"] = "project_kb_old"
            report = check_stale(corpus=corpus, manifest=manifest)
            self.assertIn("collection-changed", report["reasons"])


if __name__ == "__main__":
    unittest.main()
