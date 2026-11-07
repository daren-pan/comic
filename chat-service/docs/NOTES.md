# chat-service · 踩坑与实测记录

> 按项目约定：`README.md` 讲框架与用法，本文件只记**踩过的坑、实测数字、复盘**。
> RAG 内核本身的坑（cosine 度量、阈值标定、繁简、hash 后端）记在 `src/comic_chat/rag/NOTES.md`。

## 2026-10-29 从 api 进程拆成独立服务

### 1. 服务挂掉时返回 502「连接被重置」，而不是 503「未启动」

**现象**：停掉 chat-service，调 `/api/chat/ask` 返回

```
502  客服服务通信失败：[WinError 10054] 远程主机强迫关闭了一个现有的连接。
```

预期是 503「客服服务未启动或地址不通」。

**原因**：一开始只捕了 `httpx.ConnectError`。但实测 Windows 上对一个**已关闭的端口**发请求，
常常是「先建连成功、再被 RST」，抛出的是 `ReadError`（WinError 10054），它和 `ConnectError`
是**兄弟**，不是子类 —— 于是掉进了兜底的 `httpx.HTTPError` 分支，被归类成 502。

**修法**：改捕 `httpx.TransportError`（连接失败 / 重置 / 协议中断的统一父类），并**把
`TimeoutException` 排在它前面** —— 超时也是 `TransportError` 的子类，顺序反了超时会被
误报成「连不上」。

```python
except httpx.TimeoutException:   # 必须先，504
except httpx.TransportError:     # 再，503
except httpx.HTTPError:          # 兜底，502
```

日志里能直接看出是哪种：`客服服务不可达：…（ReadError）`。

### 2. `DATA_ROOT` 在容器里会算到不可写的位置

`comic_core/paths.py` 的注释写得很清楚：

> 容器/wheel 态由 env `COMIC_IMAGE_ROOT` / `COMIC_STATE_FILE` 覆盖，走不到这里的默认值

也就是说 **data 目录下的每样东西都要各自配一个环境变量**。索引目录原来写的是
`DATA_ROOT / "rag_lab"`，没有 env 覆盖 —— 打包进 site-packages 后 `DATA_ROOT` 会算到一个
不存在、也不可写的位置，**而且不报错**，表现为「每次重启索引都归零」。

**修法**：新增 `COMIC_CHAT_INDEX_DIR`（只接受绝对路径，相对路径视为误配并回落默认，
与 `COMIC_IMAGE_ROOT` 同一原则），compose 里设成 `/data/rag_lab`。

### 3. wheel 不声明 `package-data` 就丢 `faq.md`

`knowledge/faq.md` 是运行时数据，不是 `.py`。不写这一段：

```toml
[tool.setuptools.package-data]
comic_chat = ["rag/knowledge/*.md"]
```

装成 wheel 后 `FAQ_FILE` 指向的路径不存在，建索引直接 `FileNotFoundError`。

⚠️ **而且本地 editable 安装时不会暴露这个问题** —— 源码目录里文件确实在，只有镜像里才炸。
验证方法：`python -m zipfile -l dist/*.whl | grep faq`。

### 4. 模型必须在构建时预热

不做这一步，容器首次收到提问要现下 90MB 模型，表现为「第一次问卡 30 秒」，而 `/health`
是通的 —— 这种「看起来正常」的慢最难查。

```dockerfile
ENV HF_HOME=/opt/hf-cache HF_ENDPOINT=https://hf-mirror.com
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-zh-v1.5')"
```

模型名必须与 `rag/settings.py` 的 `LOCAL_MODEL` 默认值一致，改模型时两处都要改。

### 5. 拆分的实际收益（实测）

| 项 | 拆分前（进程内） | 拆分后 |
|---|---|---|
| api 镜像依赖 | 需装 langchain 全套（80+ 包） | 只多一个 `httpx` |
| chat 挂掉时主站 | 一起挂 | `/api/health`、`/api/comics` 均 **200**，只有客服 503 |
| 客服接口延迟 | 本地函数调用 | +一次内网 HTTP（实测 <10ms） |
| 索引迁移 | — | **零迁移**：路径与集合名都没变（`comic_kb_ae18b7`），本地与容器共用同一份 |

### 6. 本地开发要起两个进程

以前 `up api` 一个就够，现在：

```bash
bash scripts/dev.sh up chat    # :8001
bash scripts/dev.sh up api     # :8000
```

`dev.sh` 的 `chat` 分支里 `PYTHONPATH` 按平台分号/冒号分开写 —— **Windows 是 `;`，Linux 是 `:`**，
用错了 Python 会把整串当一个路径，`import comic_core` 直接失败。

### 7. DSH / 受限 Windows：TEMP 不可写会让 Chroma 报 code 14（2026-11-03）

**现象**：服务能起来、`/health` 也有响应，但 `ok=false`、`vectors=0`，日志里是：

```
chromadb.errors.InternalError: error returned from database:
  (code: 14) unable to open database file
```

同时 fastembed 可能报 `PermissionError: [WinError 5]`。

**原因**：Chroma 1.5 的 Rust SQLite 绑定和 fastembed 直接使用系统临时目录；DSH 把
`TEMP` 指到工作区外的 `...\AppData\Local\Temp\dsh-xxx`，受限进程写不进去。Python 的
`tempfile` 会回退到 cwd，所以纯 Python 代码看着没事；这两个原生库不走这个回退。

**修法**（两条路径互为兜底）：

- `scripts/dev.sh up chat` 显式把 `TMP`/`TEMP`/`TMPDIR` 指到 `crawler-service/data/tmp`，
  把 `FASTEMBED_CACHE_PATH` 指到 `crawler-service/data/fastembed_cache`；
- 直接 `python -m comic_chat` / `comic_chat.cli` 时，`comic_chat.runtime_env.prepare()`
  会探测临时目录是否可写，不可写就自动回退到 `DATA_ROOT/tmp`，开发态还会把模型缓存
  固定到 `DATA_ROOT/fastembed_cache`。

⚠️ 容器里 `/tmp` 可写、且 `HF_HOME` 已预热，**不要**把这两个变量硬编码进 Dockerfile；
`runtime_env` 在 wheel/容器态会跳过开发态的判断。

⚠️ 索引目录仍是 `crawler-service/data/rag_lab`，模型缓存是 `crawler-service/data/fastembed_cache`，
两者都在 `DATA_ROOT` 下（`crawler-service/data/` 已 gitignore）。
