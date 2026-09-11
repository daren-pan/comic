# docs —— 设计与原理文档

本目录集中存放**跨服务的设计文档与原理说明**，代码实现分别在各服务目录下。
改行为逻辑时优先更新对应服务的 `README.md`（面向使用），改**架构/机制**时更新本目录。

| 文件 | 内容 | 对应代码 |
|---|---|---|
| [`architecture.md`](architecture.md) | 总体架构设计方案：模块划分、数据模型、存储约定、页面布局 | 全局 |
| [`auth.md`](auth.md) | 登录认证原理速查：JWT + bcrypt、收藏/历史鉴权边界 | `api-service/core/security.py` · `routers/auth.py` |

> 各服务的使用说明见 `crawler-service/README.md` / `api-service/README.md` / `comic-web/README.md`。

## 源站适配说明（已就近到各源包）

每份适配文档**跟着源代码走**，不再集中在本目录：

| 文档 | 源站 | 状态 |
|---|---|---|
| [`sources/zaimanhua/README.md`](../crawler-service/src/comic_crawler/sources/zaimanhua/README.md) | 再漫画（H5 匿名可读） | **主源** |
| [`sources/mangadex/README.md`](../crawler-service/src/comic_crawler/sources/mangadex/README.md) | MangaDex | 备源（config 默认 `enabled=False`） |
| [`sources/weebcentral/README.md`](../crawler-service/src/comic_crawler/sources/weebcentral/README.md) | WeebCentral | 备源 |

> **新增源站**：在 `sources/` 下复制一个子包（`adapter.py` + `README.md` + `fixtures/`），
> 改动只在子包内 —— 具体步骤见 `crawler-service/README.md`。
