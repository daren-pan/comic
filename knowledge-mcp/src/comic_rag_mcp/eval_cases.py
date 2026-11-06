"""检索评测用例：问题 → 期望命中的文件（任一即可）。

这不是“标准答案”，而是回归基线：改切分 / 改阈值 / 改加权后跑一遍，看 Recall@5
有没有掉。用例按项目文档的实际主题写，后续可以继续加。
"""
from __future__ import annotations

CASES: list[dict] = [
    {
        "query": "scheduler 为什么独立进程",
        "expect": ["comic-scheduler/README.md"],
    },
    {
        "query": "api 为什么只能 import crawler 的 facade",
        "expect": ["api-service/README.md", "api-service/NOTES.md", "AGENTS.md"],
    },
    {
        "query": "JWT 角色三档和两道门",
        "expect": ["docs/auth.md", "api-service/README.md"],
    },
    {
        "query": "部署端口 85 86 nginx 反代",
        "expect": ["docs/deploy.md", "deploy/README.md"],
    },
    {
        "query": "怎么新增一个爬虫源",
        "expect": [
            "crawler-service/README.md",
            "crawler-service/src/comic_crawler/sources/zaimanhua/README.md",
        ],
    },
    {
        "query": "chat 索引目录和集合名怎么定",
        "expect": ["chat-service/README.md", "chat-service/src/comic_chat/rag/README.md"],
    },
    {
        "query": "comic-core 为什么不放 HTTP",
        "expect": ["comic-core/README.md", "AGENTS.md"],
    },
    {
        "query": "message_read 已读怎么按账号记",
        "expect": [
            "api-service/README.md",
            "api-service/openapi.json",
            "comic-core/sql/mysql_schema.sql",
            "AGENTS.md",
        ],
    },
    {
        "query": "定时任务三个文件谁写谁读",
        "expect": ["comic-scheduler/README.md"],
    },
    {
        "query": "MySQL 迁移脚本怎么执行",
        "expect": ["tools/README.md", "comic-core/sql/mysql_schema.sql"],
    },
    {
        "query": "封面图存储和占位图三级兜底",
        "expect": ["crawler-service/README.md", "api-service/README.md"],
    },
    {
        "query": "comic-web 和 comic-front 功能等价吗",
        "expect": ["README.md", "comic-web/README.md", "comic-front/README.md"],
    },
    {
        "query": "同源判重键是什么",
        "expect": ["AGENTS.md", "crawler-service/README.md"],
    },
    {
        "query": "管理台任务记录在哪个表",
        "expect": [
            "AGENTS.md",
            "api-service/README.md",
            "comic-core/sql/mysql_schema.sql",
        ],
    },
    {
        "query": "scheduler 和 api 的依赖方向",
        "expect": ["comic-scheduler/README.md", "AGENTS.md"],
    },
    {
        "query": "DSH 临时目录导致 Chroma code 14 怎么修",
        "expect": ["chat-service/NOTES.md"],
    },
    {
        "query": "fastembed 模型缓存放哪",
        "expect": [
            "chat-service/README.md",
            "chat-service/src/comic_chat/rag/NOTES.md",
        ],
    },
    {
        "query": "API 统一响应格式",
        "expect": ["api-service/NOTES.md", "api-service/README.md"],
    },
    {
        "query": "登录 token 改密后为什么失效",
        "expect": ["docs/auth.md"],
    },
    {
        "query": "部署时 compose 的服务名",
        "expect": ["deploy/README.md", "docs/deploy.md"],
    },
]
