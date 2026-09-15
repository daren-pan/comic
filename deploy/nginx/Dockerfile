# nginx 模块 —— 反向代理（站点配置烘进镜像：改配置=重建这一层；证书运行时挂载）
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf

# 不能用 RUN nginx -t 做构建期校验：构建期解析不到 upstream 里的 `app`，会直接报错。
# 运行期校验：docker compose exec nginx nginx -t
