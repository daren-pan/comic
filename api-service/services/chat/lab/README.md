# RAG 实验室（`services/chat/lab`）

用**站内真实数据**跑通 LangChain + RAG 的完整链路，每一步的中间结果都能看到。
**这不是生产客服**，是学习沙盒。

## 三十秒上手

```bash
# 在项目根目录
PY=crawler-service/.venv/Scripts/python.exe

# 0. 复制配置模板，填 COMIC_LLM_API_KEY（只 ask 需要，index / search 不用）
cp api-service/services/chat/lab/.env.example api-service/services/chat/lab/.env

$PY tools/rag_lab.py doctor                    # 1. 看配置：用哪个向量后端
$PY tools/rag_lab.py index                     # 2. 建索引（64 个文档 → 64 条向量）
$PY tools/rag_lab.py search "图裂了怎么办"       # 3. 只看检索命中（不花钱）
$PY tools/rag_lab.py ask "图裂了怎么办"          # 4. 完整问答（需要对话模型 key）
```

`search` 和 `ask` 的差别就是「检索」和「生成」两段。**调试时永远先用 `search`。**

### 在服务器上跑（非 Docker）

直接 `python` 跑的话，和本地一样，只是要注意两点：

1. **依赖要装齐**：`pip install -r api-service/requirements-lab.txt`
2. **模型下载走镜像**：模板里的 `HF_ENDPOINT=https://hf-mirror.com` 别删，
   否则首次建索引会报 `Could not load model ... from any source`（国内直连 HuggingFace 基本不通）

**Docker 部署跑不了这一套**：`deploy/api/Dockerfile` 只装 `comic-api` 的 wheel 依赖，
不含 langchain / chromadb / fastembed，容器里请求客服会直接返回 503。
要在容器里跑，得改 Dockerfile 装 `requirements-lab.txt` 并在构建时预热模型 ——
镜像会涨 400MB 以上，所以**默认不这么做**。

## 七步链路 → 对应代码

| # | 步骤 | 干什么 | 代码位置 |
|---|---|---|---|
| ① | 加载 | MySQL 的 54 部作品 + FAQ 的 10 节 → `Document` | `documents.py` |
| ② | 切分 | FAQ 按 `##` 切开；作品不切 | `documents.py` |
| ③ | 向量化 | 文本 → 512/1024 个浮点数 | `embeddings.py` |
| ④ | 存储 | 写进 Chroma，落盘到 `DATA_ROOT/rag_lab/` | `index.py` |
| ⑤ | 检索 | 问题转向量 → 找最近的 4 条 | `chain.py` |
| ⑥ | 增强 | 4 条原文拼进 system prompt | `chain.py` |
| ⑦ | 生成 | 模型读 prompt → 输出答案 | `chain.py` |

## 四个必须理解的点

**① 切分粒度由数据形态决定，不是一个 `chunk_size` 走天下**
FAQ 有 10 个小节，按 `##` 切；作品简介平均 102 字，**不切**。给短文本套
`RecursiveCharacterTextSplitter(chunk_size=500)` 等于没切，给长篇 FAQ 按字符切会把一节
从中间劈开 —— 检索到半截，模型看不懂。

**② 向量只用于「找」，找到后给模型看的是原文**
`Document.page_content` 是原文，`embedding` 只是一个用于比距离的索引。永远不要把向量
塞进 prompt。

**③ 分数方向别搞反**
`similarity_search_with_relevance_scores()` → **0~1，越大越像**（本项目用这个）
`similarity_search_with_score()` → **距离，越小越近**

**④ 换模型必须重建索引**
不同模型的向量不在同一个语义空间。本项目让集合名带配置指纹
（`comic_kb_<hash>`），换配置自动落到新集合，**忘了重建也不会串**。

## 三个实验（改一行代码，看结果怎么变）

| 实验 | 怎么改 | 你会看到 |
|---|---|---|
| 切分太碎会怎样 | 给 `load_comic_documents()` 也套上 `RecursiveCharacterTextSplitter(chunk_size=40)` | 「《某作品》作者是谁」检索到的片段里只剩书名没了作者 |
| 阈值的作用 | `search --topk 10`，再把它设成 `min_score=0.6` | 低分噪音（无关漫画简介）被挡住，答案不再跑题 |
| topK 不是越大越好 | `--topk 1` vs `--topk 8` | 1 条常缺信息，8 条开始被无关内容带偏 |

## 三个向量后端

| 后端 | 条件 | 效果 | 用途 |
|---|---|---|---|
| `openai` | 配了 `COMIC_EMBED_API_KEY` | 最好 | 正式效果 |
| `local` | 装了 `fastembed` | 够看 | **默认**，离线免费 |
| `hash` | 都没有 | 只反映字面重合 | 验证链路 |

切换只需改环境变量 + 重建索引，代码不动。

```bash
# 切到云端 embedding（通义百炼，DeepSeek 没有 embedding 接口）
export COMIC_EMBED_API_KEY=sk-xxx
$PY tools/rag_lab.py index     # 集合名会自动变，旧索引保留
```

## 和生产的边界

| 关注点 | 这里的做法 |
|---|---|
| 依赖 | 独立 `api-service/requirements-lab.txt`，**生产镜像不装** |
| 代码 | `routers/chat.py` 里 langchain 的 import 全在函数内，没装依赖也能启动 |
| 路由 | `COMIC_CHAT_LAB=0` 时不挂载（404） |
| 鉴权 | 全部 `require_admin` —— 这些接口会真花钱 |

## 目录

```
lab/
├── settings.py        配置（环境变量 → 常量）
├── embeddings.py      三种向量后端
├── documents.py       加载 + 切分
├── index.py           向量化入库 + 集合管理
├── chain.py           检索 + prompt + LCEL 管道
├── knowledge/faq.md   知识源（改完要 index）
├── README.md          本文件
└── NOTES.md           实测踩坑记录
```
