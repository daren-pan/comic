# guazi —— 瓜子漫画（**尚未接入**）

⚠️ **本目录目前没有适配器**，只保留了 4 份样例 HTML（`fixtures/gz_*.html`）作为将来
接入时的参考，不参与轮询、不被任何代码引用。

| 文件 | 页面 |
|---|---|
| `gz_home.html` | 首页 / 列表 |
| `gz_detail.html`、`gz_detail_31088.html` | 详情页 |
| `gz_chapter.html` | 章节页 |

## 接入步骤（三步，都在本目录内完成）

1. 写 `adapter.py`：继承 `sources.base.CrawlerAdapter`，参考 `sources/zaimanhua/adapter.py`；
2. 写 `__init__.py`：导出 `Adapter` 类与 `SOURCES = [SourceConfig(name="guazi", ...)]`；
3. 在 `sources/__init__.py` 的聚合处加一行 import。

> 若确定不再需要这些样例，可整个目录删除 —— 但请先确认没有人在准备接入该源。
