# front 模块 —— 移动端入口（nginx 托管 comic-front 的 H5 产物 + 反代后端）
#
# 产物：deploy/build.sh 把 comic-front/dist/build/h5 复制到本目录 dist/，再构建本镜像。
# 用法：镜像自带 nginx，直接跑就是一个完整站点入口（宿主端口由 compose 映射，见 docker-compose.yml）。
#
# ⚠️ 与 deploy/web/ 是**同构的两个镜像**，只有烘进去的产物不同（网页端 / 移动端）。
#    两边各自带 nginx 而不是共用一个反代容器，是为了「按需启动」：只跑移动端时，
#    nginx 与静态产物在同一个容器里，不存在「反代活着但产物不在」的悬空状态。
#
# 基础镜像经 DaoCloud 加速站拉取（m.daocloud.io 代理 docker.io）；换回官方源删掉前缀即可。
FROM m.daocloud.io/docker.io/library/nginx:alpine

# 站点配置烘进镜像 —— 改配置 = 重建这一层，可版本化 / 可回滚（与产物同一策略）
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 前端产物（deploy/build.sh 负责填充 dist/）
COPY dist /usr/share/nginx/html

# 不能用 RUN nginx -t 做构建期校验：构建期解析不到 upstream 里的 `comic-app`，会直接报错。
# 运行期校验：docker compose exec comic-front nginx -t
