"""comic_crawler —— 漫画聚合平台采集服务。

对应架构方案 §2/§4：负责多源抓取、解析、去重、入库，
与业务服务（漫画/搜索/用户）完全解耦。

分层：
- adapter/   源站适配器（CrawlerAdapter 接口 + 各源实现 + 注册表）
- http.py    抓取客户端（UA 池 / 随机延迟 / 指数退避）
- fingerprint.py  标题归一化与跨站指纹
- storage.py 存储契约（Storage 抽象，唯一实现 MySQL）
- scheduler.py    全量 / 增量调度
- cli.py     命令行入口
"""

__version__ = "0.1.0"
