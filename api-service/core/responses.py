"""统一响应包封（架构约定：`{code, message, data}`）。"""
from __future__ import annotations


def ok(data, message: str = "ok") -> dict:
    """成功响应。失败统一用 `HTTPException`（由 FastAPI 输出错误体）。"""
    return {"code": 0, "message": message, "data": data}
