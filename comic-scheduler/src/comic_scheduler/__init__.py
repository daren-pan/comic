"""定时任务执行器 —— **独立进程**（`comic-scheduler` 镜像的入口）。

它读管理台配的 5 段 cron，按点对选中的数据源跑采集，并把运行态写回文件供页面展示。

## 模块边界

```
comic-scheduler  →  comic-crawler  →  comic-core
       （不依赖 api-service：接口层不参与定时执行）
```

与 api 之间**只通过运行时数据目录里的三个文件**交换（各只有一个写者，见
`comic_crawler.scheduling.schedule_state`）：

| 文件 | 写者 | 读者 |
|---|---|---|
| `schedule.json` | api（页面保存） | 本进程 |
| `schedule_state.json` | 本进程 | api（页面展示） |
| `schedule_run_now.json` | api（「立即执行一次」按钮） | 本进程（读到即删） |

入口：`python -m comic_scheduler` 或控制台脚本 `comic-scheduler`。
"""

from .daemon import TICK_SECONDS, main, run_once

__all__ = ["main", "run_once", "TICK_SECONDS"]
