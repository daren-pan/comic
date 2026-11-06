# 检索评测（第一版）

**方法**：20 条项目问题，`top_k=5`；命中期望文件中的任意一个即算通过。
只看“文档有没有被召回”，不判断最终答案质量。

运行：

```bash
bash scripts/dev.sh knowledge-index
PYTHONPATH="knowledge-mcp/src;chat-service/src;comic-core/src" \
  crawler-service/.venv/Scripts/python.exe -m comic_rag_mcp.cli eval --top-k 5
```

## 结果（2026-11-03，约 800 chunk）

**Recall@5 = 20/20（100%）**。

| # | 问题 | Top-1 命中 | 分数 | 备注 |
|---|---|---|---:|---|
| 01 | scheduler 为什么独立进程 | `comic-scheduler/README.md` / 为什么独立成进程 | 0.8096 | 准确 |
| 02 | api 为什么只能 import crawler 的 facade | `api-service/README.md` / 基础命令 | 0.7195 | 路径对，小节偏“命令” |
| 03 | JWT 角色三档和两道门 | `docs/auth.md` / 8.3 鉴权怎么落 | 0.6159 | 准确 |
| 04 | 部署端口 85 86 nginx 反代 | `deploy/README.md` / 前端入口 | 0.7758 | 准确 |
| 05 | 怎么新增一个爬虫源 | `sources/weebcentral/README.md` / 端点 | 0.6256 | **top-1 不理想**（具体源≠怎么新增） |
| 06 | chat 索引目录和集合名怎么定 | `chat-service/README.md` / 目录 | 0.6971 | 路径对，小节偏“目录” |
| 07 | comic-core 为什么不放 HTTP | `comic-core/README.md` / 为什么单独成包 | 0.7797 | 准确 |
| 08 | message_read 已读怎么按账号记 | `api-service/openapi.json` / Mark All Read | 0.8516 | 路径对，表结构排第 2 |
| 09 | 定时任务三个文件谁写谁读 | `comic-scheduler/README.md` / 与 api 的分工 | 0.7170 | 准确 |
| 10 | MySQL 迁移脚本怎么执行 | `tools/README.md` / 其它运维脚本 | 0.7737 | 路径对，小节略偏 |
| 11 | 封面图存储和占位图三级兜底 | `crawler-service/README.md` / 约定 | 0.6867 | 路径对，小节偏“约定” |
| 12 | comic-web 和 comic-front 功能等价吗 | `comic-web/README.md` / 标题 | 0.8284 | 准确 |
| 13 | 同源判重键是什么 | `crawler-service/README.md` / 约定 | 0.6000 | 准确 |
| 14 | 管理台任务记录在哪个表 | `mysql_schema.sql` / admin_task | 0.6992 | 直接答到表 |
| 15 | scheduler 和 api 的依赖方向 | `comic-scheduler/README.md` / 约定 | 0.7736 | 准确 |
| 16 | DSH 临时目录导致 Chroma code 14 | `chat-service/NOTES.md` / §7 | 0.7592 | 准确 |
| 17 | fastembed 模型缓存放哪 | `chat-service/.../rag/NOTES.md` / §6 | 0.7497 | 准确（rag NOTES 更具体） |
| 18 | API 统一响应格式 | `api-service/NOTES.md` / 1.2 | 0.7452 | 准确 |
| 19 | 登录 token 改密后为什么失效 | `docs/auth.md` / 6 安全要点 | 0.7869 | 准确 |
| 20 | 部署时 compose 的服务名 | `docs/deploy.md` / 1 方式 A | 0.7017 | 准确 |

**top-1 命中期望路径：19/20**（#05 例外，但 #05 的 top-5 里仍有
`crawler-service/README.md` 或源站 README，所以 Recall@5 通过）。

## 结论

- 第一版“能查到”已经达标：20 条全部在 top 5 内；
- 但 Recall@5 掩盖了 **top-1 排序**问题：#05 把“具体源站 API”排到了
  “怎么新增源”前面；#02/#06/#10/#11 路径对但小节不是最贴切；
- 后续应补 **MRR / top-1 accuracy / 答案正确性**，不要只看 Recall@5；
- 如果继续调，优先调“查询意图 → 模块/文档类型”的加权，而不是继续加大 chunk。

## 后续用例

建议按模块补到 40~50 条，尤其：

- 部署排障（容器健康检查、端口冲突、volume）；
- 认证边界（`require_admin` vs `require_superadmin`、service token）；
- 采集源新增（adapter 契约、fixtures、注册）；
- 数据库迁移（0001~0010 的语义、回滚）；
- 前端两套构建（H5 / 小程序、`src/utils/*` 兼容层）。
