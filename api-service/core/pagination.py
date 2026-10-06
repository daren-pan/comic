"""分页参数归一与**接口侧**单页上限。

`MAX_PAGE_SIZE` 刻意定义在 api 侧，而不是复用采集包的常量（2026-09-24 调整）：
它此前住在 `crawler/storage/mysql/log_store.py`，再经契约面 `comic_crawler.facade`
导出给 api 用 —— 等于把**存储层的实现细节**塞进了对外契约面，而且语义错配：
`services/accounts.py`（用户域分页）也在用**日志域**的上限。单页上限是"别让一次请求
拉爆响应体"的**接口层约束**，与底层用什么存储无关，所以归 api 自己定。
"""
from __future__ import annotations

#: 单页条数上限（接口侧约束）。超出即被夹到该值 —— 与存储实现无关。
MAX_PAGE_SIZE = 200


def normalize(page: int | None, page_size: int | None, default: int) -> tuple[int, int]:
    """把分页入参归一为 `(page, size)`：两者都 >= 1，`size` 不超过 `MAX_PAGE_SIZE`。

    `default` 是各自的默认页大小（日志 50 / 用户列表 20，故由调用方传入）。

    ⚠️ 归一结果必须**同时用于查询与回报** —— 否则"传 0 却报 50"这类不一致会让人
    误判分页行为（见 `services/logs.query` / `services/accounts.list_users`）。
    """
    p = max(1, int(page or 1))
    size = max(1, min(int(page_size or default), MAX_PAGE_SIZE))
    return p, size
