"""comic_crawler —— 漫画聚合平台采集服务。

对应架构方案 §2/§4：负责多源抓取、解析、去重、入库，与业务服务完全解耦。

## 分层（通用在外，扩展在里）

| 层 | 位置 | 放什么 |
|---|---|---|
| L0 通用内核 | 包根平铺 | `models` 领域模型 · `config` 数据结构与限速 · `http` 抓取客户端 · `fingerprint` 跨源去重 · `paths` 路径常量 · `cli` 命令行入口 |
| L1 契约 | 各子包根 | `sources/base.py` 适配器契约 · `storage/base.py` 存储契约 |
| L2 实现 | 契约之下 | `sources/<源名>/` 各源适配器 · `storage/mysql/` 存储实现 · `images/` 图片读写 |
| L3 编排 | `scheduling/` | 决定"何时跑、跑一次做什么"，单向依赖下面各层 |

**依赖方向只能由内向外**：`scheduling` → `sources` / `storage` / `images` → 包根通用件。
通用层与契约层**不**反向 import 实现层（由 `tests/test_layering.py` 断言守卫）。

## 常见改动位置

- **加一个源站** → 复制 `sources/demo/` 为模板，改 `source_name` 与三个解析方法，
  在 `sources/__init__.py` 的 `_SOURCE_PACKAGES` 加一项（不用碰 `config.py`）；
- **换存储后端** → 在 `storage/` 下新增实现 `storage.base` 两个契约的子包；
- **调采集节奏 / 封面自愈** → `scheduling/`；
- **跑一次 / 常驻** → `cli.py`。

```bash
PYTHONPATH=src python -m comic_crawler.cli run --source demo_source
```
"""

__version__ = "0.1.0"
