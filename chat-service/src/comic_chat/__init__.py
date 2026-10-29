"""comic-chat —— 独立的 RAG 客服服务。

## 为什么单独一个服务

`comic-api` 的镜像只装 `comic-api` 这个 wheel 的依赖。RAG 这套要拉进 80+ 个传递依赖
（langchain / chromadb / onnxruntime / tokenizers…），全塞进 api 镜像会让它涨 400MB 以上，
而且 bge 模型常驻要 300~500MB 内存 —— 和主站抢内存，被 OOM 杀掉时全站不可用。

所以照 `comic-scheduler` 的做法拆出来：**独立进程、独立容器、独立重启**。

## 进程边界（和 api 的关系）

```
前端 ──→ comic-api ──(内网 HTTP)──→ comic-chat
         鉴权 / 限流                 纯 RAG，不认用户
```

- **鉴权留在 api**：`core/security.py` 是 api-service 的模块，跨服务引用不了。
  让 api 当网关，chat 服务只管「问题 → 答案」，不需要知道是谁在问。
- **不映射宿主端口**：没鉴权的服务绝不能暴露到公网，只能同网络容器访问。
- **依赖方向单向**：`comic-chat → comic-core`，**不依赖 api-service**。

## 怎么跑

```bash
# 本地
python -m comic_chat                 # 起 HTTP 服务（默认 :8001）
python -m comic_chat.cli doctor      # 配置自检
python -m comic_chat.cli index       # 重建索引
python -m comic_chat.cli ask "问题"   # 命令行问答

# 容器
docker compose -f deploy/docker-compose.yml up -d comic-chat
```
"""
from __future__ import annotations

__version__ = "1.0.0"
