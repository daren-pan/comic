"""内部知识接口 —— 只给 MCP indexer 用，**不接受用户 JWT**。

第一个数据源：`message` 表。接口只读、按 id 升序分页；MCP indexer 用服务令牌
拉取后写本地 Chroma，MCP 运行时不直连数据库。

为什么单独一个 router，而不是挂在 `/api/messages` 下：

- `/api/messages` 是**当前账号**的收件箱，按 `to_user_id` / `min_role` 过滤；
- 这里要的是**全量 message 行**，给知识库做索引，不能复用用户过滤；
- 单独 router 便于后续给别的表/接口加 `/api/internal/knowledge/*`，
  MCP 只消费这类接口，不碰业务库。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from core.security import require_service
from services import messages

router = APIRouter(prefix="/api/internal/knowledge", tags=["knowledge"])


@router.get("/messages")
def knowledge_messages(
    cursor: int = Query(0, ge=0, description="上一条的 message.id；0 = 从头"),
    limit: int = Query(200, ge=1, le=200, description="单页条数，最大 200"),
    _auth: dict = Depends(require_service),
) -> dict:
    """按 id 升序返回 message 行（全量，不做收件范围过滤）。

    返回：

    ```json
    {
      "items": [{"id": 1, "kind": "sync", "level": "info", ...}],
      "nextCursor": 1,
      "hasMore": false,
      "schemaVersion": 1
    }
    ```

    `message` 表是追加式，没有 `updated_at`；增量游标就是 `id > cursor`。
    删除/清理（`purge`）由后续全量对账处理，不在本接口伪装成更新。
    """
    return messages.knowledge_feed(cursor=cursor, limit=limit)
