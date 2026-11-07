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

---

## 五、邮箱验证码与找回密码（2026-10-24）

> 需求 `TASK-20261024-01`：登录页「忘记密码」+ 个人中心的邮箱绑定。实现见
> `services/email_codes.py` / `services/mailer.py` / `routers/auth.py` 尾部 5 个端点，
> 表结构见 `comic-core/sql/mysql_schema.sql` 的 `email_code`。

### 5.1 ⚠️ MySQL 单条 UPDATE 里自引用列会「从左往右」赋值

- **日期**：2026-10-24
- **背景 / 现象**：「验证码错 5 次整行作废」的写法规避成一条语句 ——
  `UPDATE email_code SET attempts = attempts + 1, consumed_at = IF(attempts + 1 >= 5, NOW(), consumed_at) WHERE id=?`。
  接口实测（设计验收 #14）发现**第 4 次错就把码作废了**，第 5 次返回的是「没有可用码」而不是「次数过多」；
  更糟的是正确码在第 5 次之前就失效，用户会被提示去重新获取。
- **根因**：MySQL 单表 `UPDATE` 的**赋值按书写顺序从左往右生效**，后一个赋值引用 `attempts` 时看到的是
  **已经 +1 的值** —— 于是 `IF(attempts + 1 >= 5, …)` 实际判断成了「旧值 + 2 >= 5」，门槛整体前移一次。
- **结论**：拆成 3 条朴素语句（`UPDATE attempts = attempts + 1` → `SELECT attempts` → 到顶再
  `UPDATE consumed_at`）。这条路径每次校验最多走一次，不在热路径上，可读性优先。
  **教训**：带自引用列的 `UPDATE` 一律先怀疑这个语义，别为了"一条语句"省往返。
- **实测**：`test_email_code_flow.py` 的 `FakeCodes` 是 Python 实现，**测不出 MySQL 这个语义** ——
  该 bug 是靠 curl 打真库（错 5 次 → 429、第 6 次传正确码 → 400）才暴露的。
  修后库里该行 `attempts=5` 且 `consumed_at` 非空。
- **位置**：`comic_core/storage/mysql/email_code_store.py`（`incr_attempts`）。

### 5.2 ⚠️ `smtplib` 是阻塞调用：端点必须同步 `def`，超时必须小于前端

- **日期**：2026-10-24
- **背景 / 现象**：发验证码要等 SMTP 往返（外网 1~3 秒、超时上限 10 秒）。
- **根因**：FastAPI 对 `async def` 端点**直接在事件循环里执行**；把阻塞的 `smtplib` 放进去，
  一个慢 SMTP 就能把整个进程的所有请求一起卡住（不是只卡这一条）。写成普通 `def`
  FastAPI 会丢进线程池，互不影响。
- **结论**：5 个新端点（`/password/reset/code`、`/password/reset`、`/email/code`、`PUT /email`、
  `GET /email`）**一律 `def`，不许 `async def`**，即使某个分支其实不发信。
  另外 `services/mailer.TIMEOUT = 10` **必须小于前端请求层的 10s**（`comic-web/src/api/request.ts` 的
  `TIMEOUT`）—— 否则前端先报「网络错误」，用户永远看不到后端的 503「验证码发送失败」文案。
- **位置**：`routers/auth.py`（5 个端点）、`services/mailer.py`（`TIMEOUT`）。

### 5.3 ⚠️ 反枚举与「绑定邮箱」的发信条件不同，别统一成一个判断

- **日期**：2026-10-24
- **背景 / 现象**：设计要求「先落库、再按"邮箱在 `user` 表存在"决定是否发信」。照搬到
  `POST /api/auth/email/code`（个人中心绑定邮箱）会**永远发不出码** —— 绑定要绑的正是"还没被任何账号绑定"的邮箱。
- **根因**：两个用途的目标相反：找回密码要**隐藏**"这个邮箱存不存在"，绑定邮箱要**明确**"这个邮箱还没被占用"。
- **结论**：`issue()` 里按用途分叉 ——
  - `reset`（匿名）：**未注册也落库、也占 60 秒冷却、也可能 429、返回同一句文案**，只是不发信（反枚举的关键）；
  - `bind`（需登录）：**一律发信**，"已被别的账号占用"由 router 在发码 / 提交两步各查一次并返 409。
- **实测**：未注册邮箱发码 → `200` 且文案与已注册逐字相同、`email_code` 落 1 行、日志里**没有**发信记录、
  紧接着再发 → `429`；绑定新邮箱 → 日志能取到码、`PUT` 成功。
- **位置**：`services/email_codes.py`（`issue`）、`routers/auth.py`（`send_bind_code`）。

### 5.4 本地无 SMTP：`COMIC_MAIL_FALLBACK=log` 出码，且 `grep` 必须加 `-a`

- **日期**：2026-10-24
- **背景 / 现象**：开发机 / 验收环境没有 SMTP，用户永远收不到码，页面流程走不下去。
- **结论**：设环境变量 `COMIC_MAIL_FALLBACK=log` 启动 api —— 未配置 SMTP 或发信失败时，
  把验证码写一条 WARNING 日志并**视为发送成功**（`logger = logging.getLogger("comic.auth.mail")`，
  root 上挂着落库 Handler，所以这条也会进 `log_record` 表）。
  ⚠️ **仅限本地开发 / 验收**：等于把凭证展示给所有能看日志的人，生产必须留空。
- **实测 / 坑**：`logs/api.log` 里混有非 UTF-8 字节，`grep` 会按**二进制**处理、只吐
  `Binary file logs/api.log matches` —— 取码命令必须加 `-a`：
  ```bash
  grep -a -oE "验证码 [0-9]{6}" logs/api.log | tail -1 | grep -aoE "[0-9]{6}"
  ```
- **位置**：`services/mailer.py`（`_fallback_log` / `is_configured`）、`deploy/.env.example`。

