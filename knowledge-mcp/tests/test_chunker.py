"""切分器单测：标题树、代码块、表格、长小节。"""
from __future__ import annotations

import unittest

from comic_rag_mcp import chunker


class ChunkerTest(unittest.TestCase):
    def test_parse_sections_heading_path(self) -> None:
        text = """# 标题

前言。

## 第一节

内容一。

### 子节

内容二。

## 第二节

内容三。
"""
        sections = {s.heading: s for s in chunker.parse_sections(text, "标题")}
        self.assertEqual(sections["第一节"].level, 2)
        self.assertEqual(sections["子节"].heading_path, ["标题", "第一节", "子节"])
        self.assertEqual(sections["第二节"].level, 2)
        self.assertIn("内容一", sections["第一节"].body)
        self.assertNotIn("内容二", sections["第一节"].body)

    def test_heading_inside_fence_is_not_a_heading(self) -> None:
        text = """# 标题

## 命令

```bash
# 这是 shell 注释，不是 Markdown 标题
echo hi
```

## 下一节

正文。
"""
        headings = [s.heading for s in chunker.parse_sections(text, "标题")]
        self.assertIn("命令", headings)
        self.assertIn("下一节", headings)
        self.assertNotIn("这是 shell 注释，不是 Markdown 标题", headings)

    def test_code_block_kept_whole(self) -> None:
        text = "# 标题\n\n## 示例\n\n```python\n" + "\n".join(f"x{i} = {i}" for i in range(80)) + "\n```\n"
        docs = chunker.chunk_markdown(
            text,
            rel_path="a.md",
            title="标题",
            kind="module_readme",
            module="test",
            status="current",
        )
        self.assertTrue(docs)
        joined = "\n".join(d.page_content for d in docs)
        self.assertIn("```python", joined)
        self.assertIn("x79 = 79", joined)
        self.assertEqual(joined.count("```"), 2)

    def test_small_chunks_have_heading_path_and_lines(self) -> None:
        text = "# 标题\n\n## 第一节\n\n" + "内容。" * 200 + "\n"
        docs = chunker.chunk_markdown(
            text,
            rel_path="a.md",
            title="标题",
            kind="module_readme",
            module="test",
            status="current",
        )
        self.assertGreater(len(docs), 1)
        for doc in docs:
            self.assertIn("标题 / 第一节", doc.page_content)
            self.assertGreater(doc.metadata["parent_end"], 0)
            self.assertTrue(doc.metadata["doc_id"].startswith("a.md#"))

    def test_table_split_repeats_header(self) -> None:
        rows = "\n".join(f"| {i} | value-{i} |" for i in range(2, 80))
        table = "| id | value |\n|---|---|\n" + rows
        text = "# 标题\n\n## 表\n\n" + table + "\n"
        docs = chunker.chunk_markdown(
            text,
            rel_path="a.md",
            title="标题",
            kind="module_readme",
            module="test",
            status="current",
        )
        self.assertGreater(len(docs), 1)
        for doc in docs:
            self.assertIn("| id | value |", doc.page_content)
            self.assertIn("|---|---|", doc.page_content)


if __name__ == "__main__":
    unittest.main()
