"""存储层：契约在外（`base.py`），实现在里（`mysql/`）。

- `base.py` —— `Storage` 契约：采集/调度/API 只依赖它，后端可替换（扩展点）
- `mysql/`  —— MySQL 实现（本项目唯一后端），含热度算法与时间归一工具

⚠️ `storage.base.Storage` 只依赖 `models`；`mysql/` 才依赖 `pymysql` —— 这样上层
（如测试里的内存 Fake）可以只实现契约，不引入数据库驱动。
"""
from .base import Storage, UserStore

__all__ = ["Storage", "UserStore"]
