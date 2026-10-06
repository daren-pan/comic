# comic-core —— 采集端与接口端共用的内核

`comic-core` 是 `crawler-service` 与 `api-service` **共同的底层依赖**：领域模型、路径常量、
标签归一、日志上下文，以及**存储与图库的读写契约 + MySQL / 本地实现**。

## 为什么单独成包

目标是把「采集服务」与「接口服务」做成两个能**独立部署 / 独立重启**的服务。原先接口层
`import comic_crawler` 在**同进程内**直调采集层，于是改一行采集代码就必须重启接口进程。

拆的时候发现：存储层**无法改走 HTTP** —— 接口侧有 28 处不同的存储方法调用（分页、批量取标签、
按 id 批量取对象…），逐个包成接口既啰嗦又丢掉批量语义。所以存储层不能留在采集包里，
只能**上抽成共享包**，两端都依赖它：

```
api-service ──┐
              ├──> comic-core （模型 / 路径 / 存储 / 图库）
crawler-service ┘
```

`comic-core` **不依赖** `comic_crawler`，也不依赖任何 HTTP 框架 —— 它是纯内核。

## 目录

```
comic-core/
├── pyproject.toml            # name = "comic-core"，包数据含 data/*.json
├── sql/                      # 建库脚本（唯一真源；deploy 的 MySQL 镜像从这里取）
└── src/comic_core/
    ├── models.py             # 领域模型（ComicDetail / ChapterBrief …）
    ├── paths.py              # 路径常量：数据根 / 图库根 / 源开关文件
    ├── taxonomy.py           # 标签归一（繁体→简体、别名映射；读 data/tag_synonyms.json）
    ├── data/                 # taxonomy 的运行时数据（必须随包发布）
    ├── logctx.py             # 日志上下文（task_id / task_type，供管理台「按任务查」）
    ├── storage/              # 存储契约（base）+ MySQL 实现（mysql/，含 log_handler）
    └── images/store.py       # 图库读写契约 + 本地实现（LocalImageStore / default_store_root）
```

## 依赖与安装

- 正式安装：`pip install comic-core>=1.0.0`（两端 `pyproject.toml` 的 `dependencies` 里各有一行）。
  `pymysql` / `cryptography` / `zhconv` 由本包声明，两端**不再重复列**。
- 开发态直跑：两个包都不在 site-packages 里，靠 `api-service/core/bootstrap.py` 把
  `comic-core/src` 与 `crawler-service/src` 一起注入 `sys.path`（导入即执行、幂等）。

## 硬约定

- **单向依赖**：`comic-core` 不得 import `comic_crawler` 或 `api-service`。它是被依赖方。
- **数据根不随本包位置走**（`paths.py` 里显式判定，别改成「上溯两级」）：开发态数据根固定在
  兄弟目录 `crawler-service/data`，打包态是 `<bundle>/data`。容器把 `/data` bind 的正是前者，
  一旦漂移就会破坏「本地直跑与 Docker 读写同一批文件」。细节见 `paths.py` 顶部注释。
- **`data/` 必须随包发布**：`taxonomy` 用 `Path(__file__).with_name("data")` 读
  `tag_synonyms.json`，漏了 `package-data` 会在运行期才炸。

## 验证

```bash
# 内核自身可导入 + 数据目录可达 + 数据根解析正确
cd comic-core && PYTHONPATH="src;../crawler-service/src" ../crawler-service/.venv/Scripts/python.exe -c "
from comic_core import paths
from comic_core.taxonomy import normalize_tag
from comic_core.images.store import default_store_root
print(paths.DATA_ROOT); print(normalize_tag('測試')); print(default_store_root())"
```
