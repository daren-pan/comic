"""漫画聚合平台 · 公共内核（存储域）。

被 `comic-crawler` 与 `comic-api` **共同依赖**的共享层：

| 模块 | 内容 |
|---|---|
| `models`   | 领域对象（作品 / 章节 / 页 / 统计），各层通用的数据形状 |
| `paths`    | 运行时数据目录的默认值（`DATA_ROOT` / 图库根 / 源开关文件） |
| `taxonomy` | 标签归一（繁转简 + 同义词），**写入侧**生效 |
| `logctx`   | 日志上下文绑定（把任务 / 源 / 作品带进每条日志） |
| `storage`  | `Storage` / `UserStore` 契约 + MySQL 实现 + `log_record` Handler |
| `images`   | 图库读写契约 + 本地实现（`LocalImageStore` / `default_store_root()`） |

## 设计原则

**本包不依赖任何一方** —— 不 import `comic_crawler`，也不 import `api-service`；
只依赖标准库与第三方库。两个服务各自把它列进 `dependencies`，
而不是互相 import（见仓库根 `AGENTS.md` 的「模块依赖」）。

⚠️ 因此这里的每个模块都必须是**进程无关、服务无关**的：不假设自己跑在采集进程
还是接口进程里，也不做任何启动副作用（`sys.path` 注入那类事情归各服务的引导模块）。
"""
