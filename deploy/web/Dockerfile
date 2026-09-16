# web 模块 —— 前端产物层（只装 dist，供 api 层 COPY --from 取值）
#
# 基础镜像经 DaoCloud 加速站拉取（m.daocloud.io 代理 docker.io）；换回官方源删掉前缀即可。
FROM m.daocloud.io/docker.io/library/alpine:3.20
COPY dist /app/dist
CMD ["true"]
