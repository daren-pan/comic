# demo —— 演示源（离线样例）

**用途**：不联网也能跑通「采集 → 指纹去重 → 入库 → 转存」全链路，是单测与本地演示的
基础数据。解析目标不是真实站点，而是本目录 `fixtures/` 下的静态 HTML。

## 两个变体

| 源名 | 实现 | 说明 |
|---|---|---|
| `demo_source` | `adapter.py` → `DemoSourceAdapter` | 主样例，进轮询清单（`SOURCES`） |
| `demo_source_b` | `adapter_b.py` → `DemoSourceBAdapter` | 继承 A，仅覆盖 `LIST_FILE` / `DETAIL_PREFIX`；用来验证"一套解析复用第二个源"与跨源指纹合并 |

## 样例数据（`fixtures/`）

| 文件 | 对应页面 |
|---|---|
| `demo_list.html` / `demo_list_b.html` | 两个源的列表页 |
| `demo_detail_100x.html` / `demo_detail_b_200x.html` | 详情页 |
| `demo_chapter.html` | 章节页（图片地址列表） |

## 新增同类演示源

复制 `adapter_b.py`，改 `source_name` / `LIST_FILE` / `DETAIL_PREFIX`，再在
本目录 `__init__.py` 里导出即可 —— 无需改动解析逻辑。
