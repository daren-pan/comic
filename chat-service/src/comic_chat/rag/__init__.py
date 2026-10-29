"""RAG 内核：加载 → 切分 → 向量化 → 入库 → 检索 → 拼 prompt → 生成。

一条完整的 RAG 链路有七步，本包里每一步**对应一个文件**，可以逐个读下去：

| 步骤 | 对应模块 | 你该看懂什么 |
|---|---|---|
| ① 加载 | `documents.py` | 不同形态的数据源怎么统一成 `Document` |
| ② 切分 | `documents.py`（FAQ 部分） | 切分粒度由数据形态决定，不是拍脑袋设 `chunk_size` |
| ③ 向量化 | `embeddings.py` | 文本 → 512/1024 个数；换模型为什么必须重建索引 |
| ④ 存储 | `index.py` | Chroma 落盘在哪、集合名为什么带配置指纹 |
| ⑤ 检索 | `chain.py` | 相似度分数怎么读、`k` 取几 |
| ⑥ 增强 | `chain.py` | 检索到的原文怎么拼进 prompt |
| ⑦ 生成 | `chain.py` | LCEL 管道 `prompt → llm → parser` |

## 为什么拆成 `search()` 和 `ask()` 两个函数

只调检索、不调生成，是**排查 RAG 问题的唯一正确入口**：

- `search` 命中的不是该命中的 → 问题在「切分 / 向量化 / 检索参数」，换模型没用
- `search` 命中对了但答得歪 → 问题在「prompt 组装 / 生成模型」

这个二分法能省掉大量「换个模型试试」的无效尝试。

## 和 api-service 的关系

本包**不依赖 api-service**（依赖方向单向：`comic-chat → comic-core`）。
数据库连接直接建 `MySQLStorage()`，参数走 `COMIC_MYSQL_*` 环境变量。

详细的踩坑记录见 `NOTES.md`，用法见 `README.md`。
"""
from __future__ import annotations

__all__ = ["build_index", "ask", "search", "describe"]
