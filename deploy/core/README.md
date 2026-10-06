# deploy/core —— 公共内核的 wheel 产物（**唯一没有 Dockerfile 的模块**）

```
core/
├── dist/comic_core-<版本>-py3-none-any.whl   ← 由 deploy/build.sh 生成（gitignore，不入库）
└── README.md                                  ← 本文件
```

## 为什么这里没有 Dockerfile / 没有镜像

`comic-core` 是**纯库**（领域模型 / 存储契约与 MySQL 实现 / 图库读写 / 标签归一），
自己不提供任何可运行的服务 —— 它是被 `comic-crawler` 与 `comic-api` 依赖的**上游内核**，
不是部署单元。所以它在 `deploy/` 里只需要一个**放 wheel 的目录**，不需要镜像。

## 这个目录怎么被用

`build.sh` / `build.bat` 把 `comic-core/` 构建成 wheel 放进 `dist/`，
再以 BuildKit **命名构建上下文 `core`** 挂给两个消费方：

| 消费方 | 挂载点 | Dockerfile 里的用法 |
|---|---|---|
| `comic-crawler` | `--build-context core=./core` | `COPY --from=core dist/ /tmp/wheels/core/` |
| `comic-api` | `--build-context core=./core` | 同上（另加 `crawler` 上下文） |

wheel 的拓扑顺序固定为 **comic-core → crawler → api**（后两个的 `METADATA` 里声明了 `comic-core>=1.0.0`）。

⚠️ **漏挂这个上下文的后果**：`pip install comic-crawler` / `comic-api` 时会读 `Requires-Dist: comic-core`
去 PyPI 找 —— 而 PyPI 上没有 `comic-core`（实测 404），所以会**直接报错中止构建**。
不会静默装回一个同名的假包，这点是安全的。

## 为什么本文件不能删

Docker 的构建上下文（`context: ./core`）**必须指向一个真实存在的目录**，
否则 `docker compose build comic-app` / `docker build --build-context core=./core` 会报
`context not found`。而 `dist/` 是 gitignore 的构建产物 ——
**全新 clone 下来时本目录会是空的**，于是这个 README.md 就是让目录得以存在的那份占位文件。

## 单独重建内核 wheel

```bash
cd comic-core && python -m pip wheel --no-deps --wheel-dir ../deploy/core/dist .
```

（一般不用手工跑 —— `deploy/build.sh` 已经把它排在步骤 1 的最前面。）
