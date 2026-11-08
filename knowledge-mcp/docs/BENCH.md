# MCP 调/不调 · 延迟与准确率小基准

> **只放性能与准确率基准**：不同取数方式的对比。检索质量（召回率）见 [EVAL.md](EVAL.md)，
> 设计见 [ARCHITECTURE.md](ARCHITECTURE.md)，跑测命令见 [OPERATIONS.md](OPERATIONS.md)。

> ⚠️ **数据时效**：本页采于 2026-11-07，当时检索参数是 RRF `k=60` + 等权、BM25 `1.5/0.75`。
> 2026-11-08 改成 `k=3` + `0.75/0.25`、BM25 `1.8/0.9` 后，检索质量已明显提升
> （混合 Top-1 65% → 90%，见 [EVAL.md](EVAL.md)），所以下面的**绝对得分可能偏低**；
> 这里保留的是「调 MCP vs 不调 MCP」的**相对结论**。

**问题**：简单问题、复杂问题下，调 MCP 和不调 MCP，到底差多少？

> ⚠️ 上一版把 `direct`（无检索、无文件工具、模型凭记忆答）当成“不调 MCP”，
> 这是不对的。真实的不调 MCP Agent 会用 `grep/read` 读文件。本版新增
> `file_agent` 作为公平基线。

## 四种模式

| 模式 | 链路 | 说明 |
|---|---|---|
| `direct` | 模型直接答 | 下限基线，**不是真实 Agent** |
| `file_agent` | 词面检索文件 → 读命中窗口 → 模型答 | 模拟不调 MCP、用 grep/read 的 Agent |
| `mcp_single` | MCP 检索 → 一次模型生成 | 理想的一次性 RAG |
| `mcp_agent` | 模型先决定检索词 → MCP 检索 → 再生成 | Agent + MCP 的真实结构 |

## 测试设置

- 模型：`deepseek-v4.1-flash`（`thinking=disabled`，降低方差）
- 题库：8 题，4 简单 + 4 复杂
- 每题只跑 1 次；先做 MCP + LLM 预热
- `file_agent`：对 38 个文件做 TF-IDF 词面检索，取 top3 文件、每个文件取 token 最密集的 4500 字窗口
- `mcp_single` / `mcp_agent`：`search top3` + 回读 top3 小节
- 评分：关键词覆盖，全中 1.0、中一半 0.5、否则 0；明确说“资料里没有”会扣分

## 汇总结果

| 模式 | 类型 | 平均总耗时 | P50 | 平均 LLM | 平均检索 | 读文件数 | 上下文 | prompt/完成 token | 平均得分 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `direct` | simple | 7609ms* | 1104ms | 7609ms | 0ms | 0 | 0 | 57/7 | **0.00** |
| `file_agent` | simple | **1099ms** | **990ms** | 1089ms | 10ms | 3 | 13213 字 | 6126/33 | **0.75** |
| `mcp_single` | simple | **1959ms** | **1563ms** | 1913ms | 44ms | 3 | 4622 字 | 2198/48 | **0.75** |
| `mcp_agent` | simple | **2063ms** | **2182ms** | 1098ms | 42ms | 3 | 4319 字 | 1960/38 | **0.75** |
| `direct` | complex | 1071ms | 1066ms | 1071ms | 0ms | 0 | 0 | 66/33 | **0.12** |
| `file_agent` | complex | **1297ms** | **1320ms** | 1283ms | 13ms | 3 | 12999 字 | 5736/96 | **0.88** |
| `mcp_single` | complex | **1406ms** | **1306ms** | 1359ms | 44ms | 3 | 2316 字 | 1143/98 | **0.75** |
| `mcp_agent` | complex | **1952ms** | **2010ms** | 1091ms | 45ms | 3 | 2303 字 | 1086/75 | **0.75** |

\* `direct` 有一次 27.6s 的模型异常，均值被拉高；看 P50 更合理。

## 逐题结果

| # | 类型 | direct | file_agent | mcp_single | mcp_agent |
|---|---|---|---|---|---|
| S1 | 简单：MySQL 宿主端口 | ❌ | ✅ | ✅ | ✅ |
| S2 | 简单：chat-service 端口 | ❌ | ✅ | ✅ | ✅ |
| S3 | 简单：api 健康检查路径 | ❌ | ❌ | ❌ | ❌ |
| S4 | 简单：scheduler 运行态文件 | ❌ | ✅ | ✅ | ✅ |
| C1 | 复杂：scheduler 三文件分工 | ❌ | ✅ | ✅ | ✅ |
| C2 | 复杂：JWT 三档 + 两道门 | ❌ | ✅ | ✅ | ✅ |
| C3 | 复杂：消息可见范围 + 已读表 | ❌ | ✅ | ✅ | ✅ |
| C4 | 复杂：chat 索引/集合 + 单独容器 | ❌ | ⚠️ 0.5 | ❌ | ❌ |

## 结论

### 1. 你的判断是对的：不调 MCP 也会读文件，准确率不该那么低

`file_agent` 简单题 **0.75**、复杂题 **0.88**；`direct` 的 0/0.12 只是“模型没有项目访问权”，
不能代表“不调 MCP 的 Agent”。

### 2. MCP 确实把上下文变窄了

- `file_agent`：读 3 个文件，约 **13k 字 / 5.7–6.1k prompt token**
- `mcp_single`：读 3 个小节，约 **2.3–4.6k 字 / 1.1–2.2k prompt token**

MCP 的上下文只有文件基线的 **1/3 ~ 1/6**，这是它在**大仓库**里的核心价值。

### 3. 但在这个 38 篇文档的小仓库里，MCP 没有更快

看 P50：

- 简单题：`file_agent` **990ms** vs `mcp_single` **1563ms**
- 复杂题：`file_agent` **1320ms** vs `mcp_single` **1306ms**

复杂题两者基本打平；简单题文件检索反而更快。原因：

- `file_agent` 用本地文件扫描，检索只要 **10–13ms**；
- MCP 检索要 **42–45ms**，还多一次工具调用/JSON 传输；
- 总耗时主要被模型生成（1.0–1.3s）吃掉，上下文变小省下的那点 token 不足以抵消工具开销。

### 4. `mcp_agent` 仍然不划算

多数题比 `mcp_single` 多 **约 0.5–1.0s**，但准确率没有提升（都是 0.75）。  
多出来的就是“规划器那次模型调用”；它没有比“直接用原问题检索”更准。

### 5. 复杂题上 MCP 的收益是“少读”，不是“更快”

MCP 把 13k 字压到 2.3k 字，理论上在大仓库能显著减少读取量和 prompt token；  
但这个项目只有 38 篇文档，`grep/read` 本来就很快，所以**速度优势体现不出来**。

### 6. 两题仍然失败

- **S3**：`api-service` 健康路径，`file_agent` 选到 `openapi.json` 但没定位到 `/api/health`；MCP 选到 `chat-service/README` 的“接口”小节。两边都失败。
- **C4**：`chat-service` 索引/集合前缀，`file_agent` 选到 rag README，命中一部分（0.5）；MCP 选到 chat NOTES，完全没命中。

这两类精确事实仍然更适合：

- `rg` 精确搜 `/api/health`、`comic_kb`；
- 或加 `module` / `kind` 过滤；
- 或让 Agent 在结果不相关时再搜一次。

## 复现

```bash
PYTHONPATH="knowledge-mcp/src;chat-service/src;comic-core/src" \
  crawler-service/.venv/Scripts/python.exe knowledge-mcp/bench.py
```

明细在 `bench_results.json`。

## 局限

- 只有 8 题、每题 1 次，模型延迟波动很大（`direct` 有一次 27.6s）；
- `file_agent` 是“TF-IDF + 读窗口”的近似，不是真实 Agent 的完整多轮 grep/read；
- 关键词评分很粗，复杂题只能看趋势；
- `mcp_agent` 的 `prompt_tokens` 只统计最终生成，不含规划器那次调用。
