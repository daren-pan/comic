# TASK-20261022-01 · 消息中心收藏漫画提示增加链接到详情页

> 由 `scripts/parse-request.py` 从 `需求登记表-v1.xlsx` 自动解析，生成于 2026-10-22 17:20。
> 本文件是**任务卡**；确认后即进入 设计 → 开发 → 测试 → 收尾。

**类型**：新功能　|　**优先级**：P1 高

## 目标（完成态）

点击对应的收藏更新提示能够跳转到对应详情页

## 背景与问题

现在消息中心当有收藏漫画更新时会提示出来，但是需要自己手动跳转到对应详情页才能看到，增加链接方便跳转

## 影响模块

- comic-web

## 范围（白名单）

用户填写：

- `comic-web`
- `comic-front`（**设计补充后用户确认同步**，2026-10-22 —— 两端功能等价是硬约定）

**设计细化，用户已确认同步双端** —— 详见 `02-design.md` §4、§1.1：

- `comic-web/src/stores/message.ts` —— 新增导出纯函数 `detailPath(n)`（唯一判定入口）
- `comic-web/src/views/MessagesView.vue` —— 点击改走 `openItem()`（先标已读、再按 `detailPath` 跳转）+ `linkable` 类与 hover 样式
- `comic-web/tests/message-detail-link.test.ts` —— 新增单测（测试角色写，可选但推荐）
- `comic-front/src/stores/message.ts` —— 与 web 版**逐字相同**的 `detailPath`
- `comic-front/src/pages/messages/index.vue` —— 点击改走 `openItem()`（`uni` 侧经 `utils/router.ts` 兼容层跳 `pages/comic/index?id=`）+ `linkable` 类与 `:hover`/`:active` 样式
- `comic-front/tests/message-detail-link.test.ts` —— 同矩阵单测（测试角色写，可选但推荐）

共 **6 个文件**（4 个源码 + 2 个新增测试）。白名单外一律不动（含两端 `types.ts` / `utils/router.ts` / `src/pages.json` / `components/Layout.vue` / 全部后端文件）。
**跨模块**：`comic-web` + `comic-front` —— **已获用户确认**（不再是待拍板项）。

## 明确不做

- 不改后端 / 数据库 / `/api/messages` 出参契约（`params.comicId` 已有）
- 不新增站内路由（web `/comic/:id`、front `pages/comic/index` 均已存在）
- 不改消息页已读时机（进页不标、离开标全部）
- 不改顶栏任务结果 toast
- **不做键盘可达性**（`role`/`tabindex`/焦点样式，属独立可访问性需求）
- **不做 uni 原生端（App / 小程序）验证**，只按 H5 形态（:5174）验收
- 不改 comic-front 详情页的层级返回规则（从消息页进入后「← 返回」仍落 `/latest`）

## 数据库变更

**无** —— 无。运维阶段直接判 N/A，无需迁移与备份。

## 验收标准

1. 点击对应的收藏更新提示能够跳转到对应详情页

## 参考材料

- （无）

## 执行约定

- **提交策略**：不自动提交（改完等用户确认）
- **期望完成**：未指定

## 待确认（负责人提交用户拍板）

- [ ] 范围白名单是否准确（有无漏掉的路径 / 多写的路径）
- [ ] 验收标准是否都能用命令或可见结果判定
- [ ] 是否现在开工（否则停在 brief 阶段等待）
