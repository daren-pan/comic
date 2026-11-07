# comic-core · 知识库（AI 维护）

> 本文件是 comic-core 的**踩坑与知识沉淀**，由 AI 协作时维护 ——
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

## 一、`status` 归一（2026-10-13，B 块）

### 1.1 背景：一个字段四种写法 + 接口层静默吞值

- **背景 / 现象**：`status` 字段全链路四种用词 —— 各源 adapter **各写一套转换**（`weebcentral`
  用 `STATUS_MAP` 输出"连载/完结/休载/已取消"、`mangadex` 用 `_status_text()`、`copymanga` 用
  `_status_of()`、`zaimanhua` 直接透传源站文本），`models.py` 的默认值是第三种（"连载"），
  而 `api-service/serializers.py` 再用白名单把认不出的值**一律强制成"连载中"**。
- **根因**：`status` 从未做过归一 —— 项目对**标签**写了教科书级的归一模块（`taxonomy.py`），
  但 `status` 漏了；接口层用兜底"藏住"了不一致，所以一直没暴露。
- **结论**：生产库实测 `连载 29 / 连载中 23 / 完结 2` —— **31 条（57%）不在白名单内**，
  2 部已完结作品在界面上**一律显示"连载中"**（信息被静默吞掉）。

### 1.2 修法：唯一定义处 + 存量迁移 + 删兜底

- **结论**：新增 `status.py`（**4 个规范值**：`连载中` / `已完结` / `休载` / `已取消` +
  别名表（含繁体）+ `normalize_status()`）。**未命中保留原文 + warning** —— 不吞、不猜。
  各源 adapter 与接口层都调同一个函数；删掉接口层白名单兜底；配套存量迁移
  `tools/migrations/0009_migrate_comic_status.sql`（由 tools/migrate.sh 统一执行）。
- **实测**：迁移 31 行（`连载` 29 → `连载中`、`完结` 2 → `已完结`）；迁移后分布
  `连载中 52 / 已完结 2`；接口实证 `id=8「電鋸人」` / `id=57「現實闖關」` 由「显示为连载中」
  修复为「已完结」。**迁移只 UPDATE `status`、不碰 `sync_time`** —— 排序未受影响（已实测）。
- **位置**：`src/comic_core/status.py`、`crawler-service/tests/test_status.py`（10 例）、
  `tools/migrations/0009_migrate_comic_status.sql`。

### 1.3 ⚠️ 不做迁移会污染"最近更新"排序

- **背景 / 现象**：迁移前若直接上线（adapter 输出规范值、库里还是旧值）—— 下次采集这 31 部时，
  `comic_store._CHANGE_FIELDS` 含 `("status", "status")` → 会被判定成"内容有变化" → 触发无谓 UPDATE、
  **并把 `sync_time` 刷成当前时间** → 31 部作品突然挤到「最近更新」最前面。
- **根因**：`sync_time` 是"内容最近变化"的标记，status 值差异会触发它。
- **结论**：**先迁移、后上线**（或迁移与上线同时），保证采集时比较结果一致、不触发更新。

---

## 二、标签归一（`taxonomy.py`）的现状

### 2.1 归一的覆盖范围与"刻意不做的事"（2026-10-13 复核）

- **背景 / 现象**：用户曾提出"归一化不用处理了，现在数据源都是中文的" —— 复核后发现**归一部分在跑**：
  `comic_store._sync_tags` 里先 `canonical_tag(raw)` 再 `INSERT IGNORE`。
- **实测**：
  - 同义词表 `data/tag_synonyms.json` 仅 **1564 字节 / 约 30 组**（`"喜剧": ["Comedy","搞笑","欢乐向"]`…）；
  - 库内 `tag` 表 29 个标签**全是中文规范名**，没有 `Comedy` / `Action` / `格鬥` 这类原文；
  - 约 30 组之外的标签走"回落简体"分支 ≈ 原样存（字典表 `INSERT IGNORE` 也确实是"没有就存、有就不管"）。
- **结论**：**保留现状**（用户裁定：数据源都是中文站，不再为英文标签做归一；已收录的规范名不回滚）。
  若将来要移除，受影响面：`comic_store._sync_tags` 的调用、`taxonomy.py` + `data/tag_synonyms.json`
  的打包声明、`crawler-service/tests/test_taxonomy.py`。

---

## 三、用户表的邮箱与「唯一索引 + NULL」（2026-10-24）

> 背景：需求 `TASK-20261024-01`（找回密码 → 邮箱验证码）给 `user` 加了 `email`（+`uk_email`）与
> `password_changed_at`。两列都允许 `NULL`，这两条坑都跟"`NULL` 与唯一索引怎么相处"有关。

### 3.1 ⚠️ 未绑定必须存 `NULL`，不能存 `''`

- **日期**：2026-10-24
- **背景 / 现象**：`user.email` 加了唯一索引 `uk_email` 之后，"老用户 / 没绑定的人"该写什么值。
- **根因**：MySQL（以及 SQL 标准）的唯一索引**不比较 `NULL`** —— 任意多行 `NULL` 都合法；
  而 `''` 是**普通值**，两行 `''` 直接撞 `uk_email` 报 `1062 Duplicate entry`。
  若定义成 `NOT NULL DEFAULT ''`，上线瞬间第二个未绑定用户（注册 / 任何写回）就会 500，**把所有人都挡在门外**。
- **结论**：列定义 `VARCHAR(128) NULL DEFAULT NULL`；**代码里空串一律显式转 `NULL`**
  （`MySQLUserStore.set_user_email()` 的 `(email or "").strip().lower() or None`）。
  现网 4 个老用户 `email IS NULL` 并存，实测注册 / 绑定均正常。
- **位置**：`sql/mysql_schema.sql`（`user`）、`tools/migrations/0010_add_user_email_and_email_code.sql`、
  `src/comic_core/storage/mysql/user_store.py`。

### 3.2 ⚠️ `UPDATE ... SET email=?` 在新值 == 旧值时 `rowcount` 返回 0

- **日期**：2026-10-24
- **背景 / 现象**：`set_user_email()` 用 `cur.rowcount > 0` 表示成功，接口在 `False` 时返 409
  「该邮箱已被其他账号绑定」。实测「同一账号重复绑定自己**已绑的**邮箱」被误报 409 ——
  用户明明绑的就是自己的邮箱；更隐蔽的是 `set_user_email(15, '')` 在 `email` 本来就是 `NULL` 时也返回 `False`。
- **根因**：MySQL 的 `UPDATE` 默认返回**实际变更的行数**，`新值 == 旧值` 时是 **0 行**（不是 1 行）。
  于是「值没变」与「行不存在」在 `rowcount` 上无法区分。
- **结论**：`rowcount == 0` 时**补一次按主键的存在性查询**再判 —— 查到 → 成功（值没变而已），
  查不到 → 确实失败。同时保留唯一键冲突的兜底（捕获 `pymysql.err.IntegrityError` → `False`），
  那条是并发绑定同一邮箱时的最终裁决。
- **实测**：`set_user_email(15, 't_a@test.com')`（被 A 占用）→ `False`；`set_user_email(15, '')`（本就 NULL）→ `True`；
  `set_user_email('999999', …)`（用户不存在）→ `False`；接口侧「重复绑同一邮箱」由 409 修正为 200。
- **位置**：`src/comic_core/storage/mysql/user_store.py`（`set_user_email`）。


