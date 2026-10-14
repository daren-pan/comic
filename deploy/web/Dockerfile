# web 模块 —— 网页端入口（nginx 托管 comic-web 产物 + 反代后端）
#
# 产物：deploy/build.sh 把 comic-web/dist 复制到本目录 dist/，再构建本镜像。
# 用法：镜像自带 nginx，直接跑就是一个完整站点入口（宿主端口由 compose 映射，见 docker-compose.yml）。
#
# 基础镜像经 DaoCloud 加速站拉取（m.daocloud.io 代理 docker.io）；换回官方源删掉前缀即可。
FROM m.daocloud.io/docker.io/library/nginx:alpine

# 站点配置烘进镜像 —— 改配置 = 重建这一层，可版本化 / 可回滚（与产物同一策略）
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 前端产物（deploy/build.sh 负责填充 dist/）
COPY dist /usr/share/nginx/html

# 不能用 RUN nginx -t 做构建期校验：构建期解析不到 upstream 里的 `comic-app`，会直接报错。
# 运行期校验：docker compose exec comic-web nginx -t   （或 comic-front）
