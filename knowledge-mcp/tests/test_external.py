"""外部文档源（Markdown / Word / Excel）单测。

重点验证三件事：
1. Word 真的被转成了带标题层级的 Markdown（否则切分退化成整篇一块）；
2. Excel 是「一行一个 chunk」且**表头拼进了每一行**（否则单看「张三 | 3500」没有意义）；
3. 两种二进制格式都标 `read_mode="chunk"`（没有行号可回读，不能走 `lines`）。
"""
from __future__ import annotations

import contextlib
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from comic_rag_mcp import config, external
from comic_rag_mcp.corpus import load_corpus


@contextlib.contextmanager
def _tmpdir():
    """临时目录，**自己管创建与清理**。

    ⚠️ 不用 `tempfile.TemporaryDirectory()` / `mkdtemp()`：受限 Windows 会话（DSH 沙箱）里
    这两者踩两个坑 —— ① 退出时 `chmod` 复核报 WinError 5，断言全过却标记 error；
    ② `mkdtemp` 建出来的目录（0o700）里**不允许再建子目录**，`mkdir()` 直接拒绝访问。
    改用自己命名 + `makedirs`，与项目里 `up api` 等脚本的做法一致。
    """
    base = Path(
        os.environ.get("COMIC_TEST_TMP")
        or (config.ROOT / "crawler-service" / "data" / "tmp")
    )
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"kbtest-{os.getpid()}-{len(list(base.iterdir()))}"
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _make_docx(path: Path) -> None:
    from docx import Document

    document = Document()
    document.add_heading("员工手册", level=1)
    document.add_paragraph("本手册适用于全体员工，请仔细阅读。")
    document.add_heading("考勤制度", level=2)
    document.add_paragraph("上班时间为每天九点，迟到按规则扣款。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "姓名"
    table.cell(0, 1).text = "工号"
    table.cell(1, 0).text = "张三"
    table.cell(1, 1).text = "A001"
    document.save(str(path))


def _make_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "员工"
    sheet.append(["姓名", "工号", "部门"])
    sheet.append(["张三", "A001", "研发"])
    sheet.append([None, None, None])  # 整行空 → 必须被跳过
    sheet.append(["李四", "A002", "财务"])
    workbook.save(str(path))


class ExternalDocTest(unittest.TestCase):
    def test_docx_becomes_markdown_with_heading_tree(self) -> None:
        with _tmpdir() as root:
            
            docs = root / "kb"
            docs.mkdir()
            _make_docx(docs / "手册.docx")

            documents, files, skipped = external.load_external(root, docs)

            self.assertFalse(skipped)
            self.assertIn("kb/手册.docx", files)
            self.assertTrue(documents)
            self.assertEqual({d.metadata["kind"] for d in documents}, {"ext_word"})
            self.assertEqual({d.metadata["module"] for d in documents}, {"external"})
            self.assertTrue(all(d.metadata["read_mode"] == "chunk" for d in documents))
            # 标题层级真的被识别出来了（否则会退化成「整篇一个块」）
            self.assertTrue(any("考勤制度" in d.metadata["heading_path"] for d in documents))
            # 表格被转成 Markdown 并进了正文
            joined = "\n".join(d.page_content for d in documents)
            self.assertIn("| 姓名 | 工号 |", joined)
            self.assertIn("张三", joined)

    def test_xlsx_one_chunk_per_row_with_header_repeated(self) -> None:
        with _tmpdir() as root:
            
            docs = root / "kb"
            docs.mkdir()
            _make_xlsx(docs / "台账.xlsx")

            documents, files, skipped = external.load_external(root, docs)

            self.assertFalse(skipped)
            self.assertIn("kb/台账.xlsx", files)
            # 表头不算数据行，空行被跳过 → 只剩张三、李四两行
            self.assertEqual(len(documents), 2)
            rows = sorted(d.metadata["row"] for d in documents)
            self.assertEqual(rows, [2, 4])
            contents = "\n".join(d.page_content for d in documents)
            self.assertIn("姓名：张三", contents)
            self.assertIn("部门：研发", contents)
            self.assertIn("姓名：李四", contents)
            self.assertNotIn("姓名：None", contents)
            self.assertTrue(all(d.metadata["kind"] == "ext_excel" for d in documents))
            self.assertTrue(all(d.metadata["read_mode"] == "chunk" for d in documents))
            self.assertEqual({d.metadata["sheet"] for d in documents}, {"员工"})

    def test_markdown_uses_line_read_mode(self) -> None:
        with _tmpdir() as root:
            
            docs = root / "kb"
            docs.mkdir()
            (docs / "规范.md").write_text("# 规范\n\n## 命名\n\n类名用大驼峰。\n", encoding="utf-8")

            documents, files, _ = external.load_external(root, docs)

            self.assertIn("kb/规范.md", files)
            self.assertTrue(documents)
            self.assertEqual({d.metadata["kind"] for d in documents}, {"ext_md"})
            # 真实文件存在 → 能按行号回读整节
            self.assertTrue(all(d.metadata["read_mode"] == "lines" for d in documents))

    def test_missing_dir_and_unsupported_files_are_silent(self) -> None:
        with _tmpdir() as root:
            
            documents, files, skipped = external.load_external(root, root / "not-exist")
            self.assertEqual((documents, files, skipped), ([], {}, []))

            docs = root / "kb"
            docs.mkdir()
            (docs / "说明.txt").write_text("txt 不在阶段一范围内", encoding="utf-8")
            documents, files, skipped = external.load_external(root, docs)
            self.assertEqual((documents, files, skipped), ([], {}, []))

    def test_office_lock_files_are_skipped(self) -> None:
        with _tmpdir() as root:
            
            docs = root / "kb"
            docs.mkdir()
            _make_xlsx(docs / "~$台账.xlsx")

            documents, files, _ = external.load_external(root, docs)

            self.assertEqual(documents, [])
            self.assertEqual(files, {})

    def test_load_corpus_picks_up_external_dir_from_env(self) -> None:
        with _tmpdir() as root:
            
            docs = root / "kb"
            docs.mkdir()
            _make_xlsx(docs / "台账.xlsx")
            (root / "README.md").write_text("# 根\n\n## 一\n\n正文内容。\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {"COMIC_KB_DOCS_DIR": str(docs)}):
                corpus = load_corpus(root)

            kinds = {d.metadata["kind"] for d in corpus.documents}
            self.assertIn("ext_excel", kinds)
            self.assertIn("root_doc", kinds)
            self.assertIn("kb/台账.xlsx", corpus.files)

    def test_chunker_version_is_bumped_with_new_source(self) -> None:
        """新增数据源改变了 chunk 契约，必须让集合指纹变化（否则旧索引混新读法）。"""
        self.assertGreaterEqual(config.CHUNKER_VERSION, 3)


if __name__ == "__main__":
    unittest.main()
