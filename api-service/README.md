# api-service HTTP API 服务（FastAPI）

漫画聚合平台的**业务服务层**（架构方案 §4「网关 + 微服务」的落地示例）：
读取采集服务（crawler-service）落库的数据（SQLite / MySQL 可切换），对外暴露 RESTful 接口，并**同源托管前端构建产物**。

## 运行

```bash
# 依赖（复用 crawler-service 的 Python venv）
python -m pip install -r requirements.txt

# 启动（默认 SQLite：读上一级 crawler-service 下生成的 comic_demo.db，可用 COMIC_DB 环境变量指定；仓库不带数据文件，请先 cli run 采集）
python -m uvicorn main:app --host 127.0.0.1 --port 8000

# 切换 MySQL（生产存储，前端零改动；连接参数见 crawler-service/README.md「切换 MySQL」）
COMIC_DB_TYPE=mysql python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

启动后：
- **API 文档**：http://127.0.0.1:8000/docs （FastAPI 自动生成 Swagger）
- **站点**：http://127.0.0.1:8000/ （前端 dist，底部标注"已连接采集服务"）

## 接口一览（统一响应格式 `{ code, message, data }`）

| 端点 | 说明 | 对应架构方案 |
|---|---|---|
| `GET /api/health` | 服务状态 + 库内统计（comics/chapters/pages） | 网关健康检查 |
| `GET /api/categories` | 分类与作品数（含"全部"） | 浏览服务 |
| `GET /api/comics?category=&keyword=&sort=updated\|views&page=&page_size=` | 作品列表：分类/关键词/排序/分页 | `GET /api/comics` |
| `GET /api/comics/{id}` | 作品详情（访问计数，驱动热门榜） | `GET /api/comics/{id}` |
| `GET /api/comics/{id}/chapters` | 章节列表（orderNo 升序 + 页数） | `GET /api/comics/{id}/chapters` |
| `GET /api/chapters/{id}/pages` | 分页图片（返回本服务图片 URL） | `GET /api/chapters/{id}/pages` |
| `GET /api/covers/{id}` | 封面（真实文件优先，缺失生成 SVG） | 图片服务 |
| `GET /api/images/{comic_id}/{chapter_id}/{page_no}` | 分页图（OSS 文件优先，缺失生成 SVG 占位） | 图片服务 |
| `GET/PUT/DELETE /api/users/{user_id}/favorites[/{comic_id}]` | 收藏查询/添加/取消（`PUT` 幂等） | 用户中心 |
| `GET/PUT /api/users/{user_id}/history` · `DELETE /api/users/{user_id}/history/{comic_id}` | 阅读历史：查询（含作品+章节信息）/写入进度/删除 | 用户中心 |

> 匿名用户模型：前端首次访问生成 `userId`（localStorage 持久化），收藏与历史按用户隔离；
> 服务端历史支持**跨浏览器续读**（换设备/浏览器登录同一 userId 即可继续上次阅读）。

## 关键设计

- **复用 Storage 抽象**：`main.py` 自动把 `crawler-service/src` 加入 `sys.path`，
  使用 `SQLiteStorage` 或 `MySQLStorage` 的只读查询（`list_comics/get_comic/get_chapters/get_pages`），
  与采集服务共用一套存储接口 —— `COMIC_DB_TYPE=mysql` 一行切换，API 代码零改动；
- **同源部署**：`app.mount("/", StaticFiles(comic-web/dist))`，前端与 API 同一端口，
  无 CORS / 代理问题；开发模式前端走 Vite proxy（见 comic-web/vite.config.ts）；
- **图片回退链**：已转存 OSS 文件（真实图片字节）→ 本地生成 SVG 占位图。
  接真实源站后转存文件即为真实漫画图，占位逻辑自动失效；
- **视图计数**：内存计数器（演示版），生产换 Redis 计数器。

## 数据流闭环

```
crawler-service（采集/去重/入库）→ SQLite/MySQL → api-service（RESTful API）
                                                     ↓ 同源
                                    comic-web（前端 dist，读 /api 真实数据）
```

在 `crawler-service` 目录执行 `cli run` 后，刷新前端即可看到新入库内容 ——
这就是架构方案「源站一更新，本站几分钟内可见」的最小闭环。
