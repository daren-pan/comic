# TASK-20261022-01 · 收尾

> 负责人产出。结论：**可交付**（测试独立验收通过），**未提交**，等用户确认。

## DoD

- [x] 验收达标 —— `04-verify.md`：可交付，0 缺陷
- [x] check 全绿 —— web：lint 0 错 / typecheck 0 / vitest 19 passed；front：lint 0 错（4 条既有 warning）/ typecheck 0 / vitest 25 passed；两端 `npm run build` 成功
- [ ] **NOTES 未更新** —— 建议补 2 条，见「沉淀建议」（需扩白名单，待用户定）
- [ ] **未提交** —— 按 brief「允许自动提交 = 否」，等用户确认（提交建议见下）
- [x] 工作日志已记
- [x] 无意外删除、无硬编码密钥 —— `git status` 无 `D` 状态

## 改动规模

6 个文件 / +69 −6 行（4 改 + 2 新增测试）

| 文件 | 摘要 |
|---|---|
| `comic-web/src/stores/message.ts` | 新增 `detailPath(n)`：`kind==='update'` 且 `params.comicId` 为正整数 → `/comic/<id>` |
| `comic-web/src/views/MessagesView.vue` | `openItem(n)`：先标已读再跳转；整条可点 + hover 样式 |
| `comic-web/tests/message-detail-link.test.ts` | 新增 6 用例 |
| `comic-front/src/stores/message.ts` | `detailPath` 与 web 逐字相同 |
| `comic-front/src/pages/messages/index.vue` | `openItem` + 整条可点 + hover/`:active` |
| `comic-front/tests/message-detail-link.test.ts` | 新增 6 用例 |

## 验收证据（测试独立复跑）

- **web 端到端**：点 update 条目 → `#/comic/44`，`h1` 与消息标题一致；先 `POST /api/messages/{id}/read` 再跳转
- **front 端到端**：→ `#/pages/comic/index?id=44`，`h1` 一致，无路由兜底 warning
- **不该跳的**：`sync` 类、老格式 `update`（`params:{}`）点击均不跳，只标已读
- **detailPath 19 格输入矩阵**双端全过
- **视觉**：hover / cursor 有区分；窄屏无溢出；顶栏按钮不误跳

## 未验证（如实记录）

1. **真实登录全链**：库内无账号口令（约定凭证不落盘），改用「合法结构 JWT + 仅拦截 `/api/messages`（形状与 `services/messages.py` 逐字段核对）+ 其余真打后端」替代。**建议有凭据时补 5 分钟真机验证。**
2. 顶栏铃铛轮询 / toast（本次未改 Layout）
3. front 详情页「← 返回」落点（该页无返回入口）
4. uni 原生端（约定外）

## 沉淀建议（未执行，需扩白名单）

1. **`comic-front/NOTES.md`**：`utils/router.ts` 会把 `/comic/<id>` 翻译成 `pages/comic/index?id=`，新增页面跳转**无需登记 `pages.json`**（本次实测）。
2. **`comic-web/NOTES.md`**：消息条目跳转必须是「先 `markRead`（不 await）→ 再 `push`」；顺序反了会让 `markRead` 的 401 触发 `clearAuth`，把用户踢下线（测试用假 token 时实测到）。

## 提交建议（未执行）

| # | 标题 | 文件 |
|---|---|---|
| 1 | `feat(web): 消息中心收藏更新提示可跳转详情页` | comic-web 三件套 |
| 2 | `feat(front): 消息中心收藏更新提示可跳转详情页` | comic-front 三件套 |
| 3 | `chore(tools): 新增需求表解析脚本与需求目录` | `scripts/parse-request.py`、`scripts/README.md`、`docs/requirements/`、`docs/tasks/_template/` |

## 遗留

- **R9**：从消息页进详情后点「← 返回」落 `/latest`（既有行为，本次未改）—— 可另开任务
- 键盘可达性（Tab / Enter）本次不做
