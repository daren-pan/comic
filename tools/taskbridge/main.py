"""TaskBridge 的 HTTP 接口（给 Dify 的 HTTP 节点调用）。

设计约束：
- **提交立即返回**（毫秒级）：Dify 的 HTTP 节点有超时，绝不能让请求等 agent 跑完；
- 查进度 / 应用 / 丢弃都是独立短请求；
- 全部接口只在 `0.0.0.0:8020`，由同机 Docker 通过 `host.docker.internal:8020` 访问。
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import commands, config, worker
from .store import TaskStore

app = FastAPI(title="TaskBridge", version="0.1.0", description="QQ 机器人 -> coding agent 的任务网关")
store = TaskStore(config.DB_PATH)


@app.on_event("startup")
def _startup() -> None:
    config.RUN_ROOT.mkdir(parents=True, exist_ok=True)
    worker.start_worker(store)


# ---------------- 模型 ----------------

class TaskIn(BaseModel):
    action: str = Field(default="code", description="动作枚举：code / doc / test")
    prompt: str = Field(..., min_length=5, description="自然语言需求，原样交给 coding agent")
    allowed_paths: list[str] = Field(
        default_factory=list,
        description="允许改动的路径前缀（相对仓库根）；为空表示不限（危险性更高）",
    )


class ApplyIn(BaseModel):
    message: str = Field(..., min_length=5, description="提交信息，按 Conventional Commits 写")


class CommandIn(BaseModel):
    text: str = Field(..., min_length=1, description="用户原话，例如「把轮播改成 5 秒」或「进度 A7F3」")


# ---------------- 路由 ----------------

@app.get("/healthz")
def healthz() -> dict:
    return {
        "ok": True,
        "repo": str(config.REPO_ROOT),
        "model": config.OPENCODE_MODEL,
        "actions": list(config.ALLOWED_ACTIONS),
        "timeout": config.TASK_TIMEOUT,
    }


@app.post("/tasks", status_code=202)
def create_task(body: TaskIn) -> dict:
    if body.action not in config.ALLOWED_ACTIONS:
        raise HTTPException(400, f"不支持的动作 {body.action}，允许：{', '.join(config.ALLOWED_ACTIONS)}")
    task = store.create(body.action, body.prompt.strip(), body.allowed_paths)
    worker.submit(task["id"])
    return {"id": task["id"], "status": task["status"], "hint": f"稍后用 GET /tasks/{task['id']} 查进度"}


@app.post("/command")
def command(body: CommandIn) -> dict:
    """自然语言入口：一句话 -> 提交 / 进度 / 应用 / 丢弃，返回可直接回给用户的文本。

    Dify 侧只需要一个 HTTP 节点调它，取 `reply` 当答案即可。
    """
    return commands.handle(store, body.text)


@app.get("/tasks")
def list_tasks(limit: int = 20) -> dict:
    return {"items": [_brief(t) for t in store.list(limit)]}


@app.get("/tasks/{task_id}")
def get_task(task_id: str, full: bool = False) -> dict:
    task = store.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    data = _brief(task)
    if full:
        data["diff_text"] = task.get("diff_text") or ""
    return data


@app.post("/tasks/{task_id}/apply")
def apply_task(task_id: str, body: ApplyIn) -> dict:
    try:
        task = worker.apply_task(store, task_id, body.message.strip())
    except Exception as exc:  # BridgeError 等
        raise HTTPException(400, str(exc)) from exc
    return {"id": task_id, "status": task["status"], "commit": task["commit_hash"]}


@app.post("/tasks/{task_id}/discard")
def discard_task(task_id: str) -> dict:
    try:
        task = worker.discard_task(store, task_id)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"id": task_id, "status": task["status"]}


@app.get("/artifacts/{task_id}/{name}")
def artifact(task_id: str, name: str):
    """产出文件（截图为后续扩展留的通道）。"""
    path = config.RUN_ROOT / "artifacts" / task_id / name
    if not path.is_file():
        raise HTTPException(404, "产物不存在")
    return FileResponse(str(path))


@app.exception_handler(Exception)
def _unhandled(_request, exc: Exception) -> JSONResponse:  # pragma: no cover
    return JSONResponse(status_code=500, content={"error": f"{type(exc).__name__}: {exc}"})


def _brief(task: dict) -> dict:
    return {
        "id": task["id"],
        "action": task["action"],
        "prompt": task["prompt"],
        "status": task["status"],
        "branch": task.get("branch", ""),
        "files": task["files"],
        "diff_stat": task["diff_stat"],
        "commit": task["commit_hash"],
        "error": task["error"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "log_tail": (task.get("log_tail") or "")[-1200:],
    }
