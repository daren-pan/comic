# api-service · 知识库（AI 维护）

> 本文件是 api-service 的**踩坑与知识沉淀**，由 AI 协作时维护 ——
> **每次踩坑 / 实测 / 复盘写到这里**，不再写进 `README.md`（README 只放模块框架、约定与用途，给人看）。
> 具体逻辑由源码注释解释维护，这里只放「为什么」与「踩过的坑」。

## 条目模板（新增知识时按此写）

```markdown
#### 标题（一句话说清是什么）

- **日期**：YYYY-MM-DD（多个用 ` / ` 分隔）
- **背景 / 现象**：发生了什么（决策类写"当时的背景"）
- **根因**：为什么会这样（决策类写"为什么这么定"）
- **结论**：怎么解决 / 最终决定是什么
- **实测**（可选）：关键数字 / 验证方式
- **位置**（可选）：涉及的文件 / 页面
```

同质清单用**表格**（列头即字段）；操作规程用**步骤结构**。

---

## 一、统一响应模型与 OpenAPI（2026-10-13）

### 1.1 背景：OpenAPI 只有入参、没有响应

- **背景 / 现象**：`/openapi.json` 里 46 个 path 的 `responses.200.schema` **全是 `None`** ——
  `/docs` 上请求参数完整、响应结构空白；拿它生成前端类型全是 `unknown`。
- **根因**：路由全 `return ok({...})` 返回裸 dict、`response_model` 用量 **0**；
  FastAPI 的 OpenAPI 只描述**函数签名看得见**的东西，而字段定义在 `to_comic()` 的**函数体**里。
- **结论**：补响应模型（见下），让字段定义从函数体挪到签名可见处。运行期业务逻辑一行未动。

### 1.2 `schemas_out.py` 与 52 个接口加声明（A 块）

- **结论**：新增 `schemas_out.py`（36 个响应模型 + 泛型 `ApiEnvelope[T]` / `PageResult[T]` + `TimeStr`）；
  `serializers.py` 的 7 个 `to_*` 从「返回 dict」改为「构造模型」；**52 个 JSON 接口**全部加 `response_model`。
- **实测**：`components.schemas` 18 → 94；52/52 接口有响应 schema；测试 138 → 151 全绿；
  匿名接口响应结构与改前**逐项一致**（改前抓快照、改后递归比对——**比结构不比字节**，views/pages 会自然变化）。
- **位置**：`schemas_out.py`、`serializers.py`、`routers/*.py`、`tests/test_response_contract.py`（13 例契约测试）。

### 1.3 ⚠️ 坑：`response_model` 会**静默裁剪**未声明的字段

- **背景 / 现象**：改前裸 dict 不过滤；改后若模型漏写字段，接口会**悄悄少返回它** ——
  前端表现为"某字段突然 undefined"，后端不报错、日志也没有。
- **根因**：FastAPI 按响应模型做序列化过滤。
- **结论**：模型必须**完整**覆盖前端在用的字段；**不要"模型 + dict 两处并存"**（字段必然漂移、
  且漂移后果更隐蔽）。新增 `tests/test_response_contract.py` 三道断言兜底：
  模型字段 ⊇ 前端在用字段 ｜ 模型字段 ⊆ 库行 key（防"声明了但 SQL 没投影"）｜ 数值字段确实是 `int`。

### 1.4 ⚠️ 坑：`datetime` 直写 `str` 会让接口 500

- **背景 / 现象**：`sources.meta()` 的 `lastSync` 实测返回的是 **`datetime` 对象**而非字符串。
- **根因**：Pydantic v2 **不做**隐式 datetime→str 转换。
- **结论**：新增 `TimeStr` 类型（模型里统一把 datetime 转 ISO 字符串）。**别照直写 `str`** ——
  那个接口一上线就是 500。

### 1.5 ⚠️ 坑：返回类型改模型后，测试断言要改属性访问

- **背景 / 现象**：`to_*` 返回模型后，所有下标访问的测试全炸（`'ComicOut' object is not subscriptable`）。
- **根因**：dict → Pydantic 模型，`out["isNew"]` 不再合法。
- **结论**：生产代码天然兼容（都是"放进 list/dict"），**只有测试断言要改**（共 7 处）。
  另：`to_chapter.createdAt` 的语义从"透传 datetime 对象"变成"归一成 ISO 字符串"，
  直接调函数的单测断言要跟着改（对外响应形态不变）。

### 1.6 ⚠️ 坑：新模块要被分层守卫补录

- **背景 / 现象**：加完 `schemas_out.py` 测试立刻红。
- **根因**：`tests/test_layering.py` 的 `_LAYER_PREFIXES` 要求每个模块归层。
- **结论**：`schemas_out` 归 **L1**（与 `schemas` / `serializers` 同层）。这是项目刻意的设计，不是障碍。

### 1.7 OpenAPI 快照与前端类型生成

- **结论**：`tools/export_openapi.py`（in-process 导出，**不要求服务在跑**、不连库）→
  `api-service/openapi.json`（提交进仓库）→ 前端 `npm run gen:api` 生成 TS 类型。
- **位置**：`tools/export_openapi.py`（仓库根）、`openapi.json`。

---

## 二、测试的坑

### 2.1 ⚠️ 假存储只有一份（测试互相污染）

- **背景 / 现象**：用假存储替换 `core.db` 的测试，与别的测试跑在同一进程里会**互相污染**
  （后导入的桩覆盖前一个）。
- **根因**：桩是模块级安装的（`install_stub()`），所有测试共享同一进程。
- **结论**：假存储只有一份（`tests/_stub_db.py`），用它必须**在导入应用模块之前**调 `install_stub()`。
- **位置**：`tests/_stub_db.py`。

### 2.2 响应契约测试（`test_response_contract.py`）

- **背景 / 现象**：响应模型上线带来的新风险是"静默裁剪"（见 §1.3）。
- **结论**：13 例测试 —— 字段快照（逐模型钉住字段集合）+ serializers↔模型一致 + 类型归一 +
  派生列 fail-fast。**改模型时它先红，比线上发现早**。
- **位置**：`tests/test_response_contract.py`。

---

## 三、契约治理

### 3.1 `SourceSearchItem.inLibrary` 冗余字段删除（2026-10-13）

- **背景 / 现象**：`inLibrary` 与 `comicId !== null` **语义完全重复**（后端构造时就是
  `comic_id is not None`）—— 两字段表达同一件事必然漂移。
- **根因**：历史遗留的冗余字段。
- **结论**：全链路删除 —— 后端 `services/ondemand.py` / `schemas_out.py` / 契约测试快照；
  前端 `types.ts` 与 search 页两处改用 `it.comicId !== null`。
- **位置**：`services/ondemand.py`、`schemas_out.py`、`tests/test_response_contract.py`。

### 3.2 `status` 白名单静默兜底删除（2026-10-13，B 块）

- **背景 / 现象**：`serializers.py` 曾有一行白名单 —— `status` 不在 `("连载中","已完结")` 内
  **一律强制成"连载中"**。生产库实测：`连载 29 / 连载中 23 / 完结 2`，**31 条（57%）不在白名单内**，
  那 2 部已完结作品在界面上**一律显示"连载中"**（信息被静默吞掉）。
- **根因**：`status` 从未做过归一（各源各写一套转换），接口层用兜底"藏住"了不一致。
- **结论**：删掉兜底，改调 `comic_core.status.normalize_status()`（唯一定义处）；配套存量迁移
  （`tools/migrations/0009_migrate_comic_status.sql`）。**归一化只做一次、只在一个地方**。
- **位置**：`serializers.py`（`to_comic` 的 status 处理）。

---

## 四、任务与后台

### 4.1 任务落库的历史（2026-10-06）

- **背景 / 现象**：管理台后台任务原先存**内存**，api 重启就丢。
- **根因**：状态在进程内存里。
- **结论**：搬到 MySQL `admin_task` 表（状态 / 结果 / **触发账号** / 入参快照）—— 重启不丢、
  与触发账号绑定；api 启动时把上一进程残留的 `running` 标成「服务重启，任务中断」。
  读写实现在 `comic_core.storage.mysql.task_store`。
- **位置**：`services/tasks.py`。
