# mysql 模块 —— 本项目独占的数据库镜像（基于官方 mysql:8.0，见 docs/deploy.md）
# 产物：deploy/build.sh 把 crawler-service/sql/mysql_schema.sql 复制到本目录 sql/
# 数据卷首次初始化时会自动执行 sql/ 里的脚本 → 10 张表直接建好，无需手工跑 SQL
#
# 版本选择：8.0（而非 5.7）—— 5.7 已于 2023-10 EOL，不再有安全更新。
# 8.0 默认认证插件是 caching_sha2_password，PyMySQL 需要 `cryptography`
# —— 已在 crawler/api 的 pyproject 依赖里声明，pip 装 wheel 时会自动带上。
#
# 基础镜像经 DaoCloud 加速站拉取（m.daocloud.io 代理 docker.io）—— mysql:8.0 约 600MB，
# 直连 Docker Hub 是整套构建里最慢的一步。要换回官方源，删掉 `m.daocloud.io/docker.io/library/` 前缀。
FROM m.daocloud.io/docker.io/library/mysql:8.0

COPY my.cnf /etc/mysql/conf.d/zz-comic.cnf

# 清掉基础镜像自带的初始化脚本 —— 本机 mysql 标签被别的项目顶掉过，
# 不清会把它自带的表建进我们的库
RUN rm -rf /docker-entrypoint-initdb.d/*

COPY sql/ /docker-entrypoint-initdb.d/
