"""语料发现与结构化知识源单测。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from comic_rag_mcp.corpus import load_corpus


class CorpusTest(unittest.TestCase):
    def test_discovery_excludes_noise_and_loads_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# 根\n\n## 一\n\n正文。\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "auth.md").write_text("# 认证\n\n## 角色\n\n三档。\n", encoding="utf-8")
            (root / "node_modules" / "pkg").mkdir(parents=True)
            (root / "node_modules" / "pkg" / "README.md").write_text("# 噪音\n", encoding="utf-8")
            (root / ".venv").mkdir()
            (root / ".venv" / "README.md").write_text("# 环境\n", encoding="utf-8")

            (root / "comic-core" / "sql").mkdir(parents=True)
            (root / "comic-core" / "sql" / "mysql_schema.sql").write_text(
                "CREATE TABLE IF NOT EXISTS comic (\n"
                "  id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',\n"
                "  title VARCHAR(255) NOT NULL COMMENT '标题'\n"
                ") ENGINE=InnoDB COMMENT='作品表';\n",
                encoding="utf-8",
            )
            (root / "api-service").mkdir()
            (root / "api-service" / "openapi.json").write_text(
                json.dumps(
                    {
                        "paths": {
                            "/api/health": {
                                "get": {
                                    "summary": "健康检查",
                                    "responses": {"200": {"description": "OK"}},
                                }
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            corpus = load_corpus(root)
            rels = set(corpus.files)
            self.assertIn("README.md", rels)
            self.assertIn("docs/auth.md", rels)
            self.assertNotIn("node_modules/pkg/README.md", rels)
            self.assertNotIn(".venv/README.md", rels)
            self.assertIn("comic-core/sql/mysql_schema.sql", rels)
            self.assertIn("api-service/openapi.json", rels)
            self.assertFalse(corpus.skipped)

            kinds = {d.metadata["kind"] for d in corpus.documents}
            self.assertIn("schema", kinds)
            self.assertIn("api", kinds)
            schema = [d for d in corpus.documents if d.metadata["kind"] == "schema"]
            self.assertTrue(any(d.metadata.get("table") == "comic" for d in schema))
            self.assertTrue(any(d.metadata.get("table") == "" for d in schema))  # 表清单
            api = [d for d in corpus.documents if d.metadata["kind"] == "api"]
            self.assertTrue(any(d.metadata.get("api_path") == "/api/health" for d in api))

    def test_historical_status_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "architecture.md").write_text("# 架构\n\n## 一\n\n历史稿。\n", encoding="utf-8")
            corpus = load_corpus(root)
            self.assertEqual(corpus.documents[0].metadata["status"], "historical")


if __name__ == "__main__":
    unittest.main()
