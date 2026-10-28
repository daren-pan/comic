"""RAG 实验室（学习用沙盒，不是生产客服）。

## 这个包想教会你什么

一条完整的 RAG 链路有七步，本包里每一步**对应一个文件**，可以逐个文件读下去：

| 步骤 | 对应模块 | 你该看懂什么 |
|---|---|---|
| ① 加载 | `documents.py` | 不同形态的数据源怎么统一成 `Document` |
| ② 切分 | `documents.py`（FAQ 部分） | 切分粒度由数据形态决定，不是拍脑袋设 `chunk_size` |
| ③ 向量化 | `embeddings.py` | 文本 → 1024 个数；换模型为什么必须重建索引 |
| ④ 存储 | `index.py` | Chroma 落盘在哪、集合名为什么带配置指纹 |
| ⑤ 检索 | `chain.py` | 相似度分数怎么读、`k` 取几 |
| ⑥ 增强 | `chain.py` | 检索到的原文怎么拼进 prompt |
| ⑦ 生成 | `chain.py` | LCEL 管道 `prompt → llm → parser` |

## 怎么跑

```bash
# 建索引（不需要任何 key，默认走 hash 占位向量）
python tools/rag_lab.py index

# 看检索命中了什么（不需要 key —— 只做检索，不调模型）
python tools/rag_lab.py search "图片加载不出来怎么办"

# 完整问答（需要 COMIC_LLM_API_KEY）
python tools/rag_lab.py ask "图片加载不出来怎么办"

# 当前配置自检
python tools/rag_lab.py doctor
```

## 为什么提供 `search` 子命令

只调检索、不调生成，是**排查 RAG 问题的唯一正确入口**：答案不对时，先看 `search`
命中的是不是该命中的那几条。

- 命中错了 → 问题在「切分 / 向量化 / 检索参数」，跟模型无关，换模型没用
- 命中对了但答得不好 → 问题在「prompt 组装 / 生成模型」

这个二分法能省掉大量「换个模型试试」的无效尝试。
"""
from __future__ import annotations

__all__ = ["build_index", "ask", "search", "describe"]
