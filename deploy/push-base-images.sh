#!/usr/bin/env bash
# ============================================================
#  基础镜像 → 本项目 ACR 推送
#
#  为什么有它：各 Dockerfile 的 FROM 直接引用**本项目 ACR**里的三个基础镜像
#  （python:3.13-slim / nginx:alpine / mysql:8.0）—— 不再依赖 m.daocloud.io 等
#  公共代理（它们间歇性 502，构建"时好时坏"，见 deploy/NOTES.md §2.2 / §2.3）。
#
#  什么时候跑：
#    · 首次搭建环境（或 ACR 里这三个镜像被删后重建）；
#    · 基础镜像要升级时（改下面的版本标签 → 跑本脚本 → 同步改各 Dockerfile 的 FROM）。
#  日常构建 / 部署**不需要**跑它（up.sh / build.sh 都不调用）。
#
#  用法：bash deploy/push-base-images.sh
#        ACR_PREFIX=其他注册表/命名空间 bash deploy/push-base-images.sh   # 换注册表
#  前置：docker 已登录 ACR（docker login <ACR 域名>）——未登录时 push 会报 unauthorized。
# ============================================================
set -euo pipefail

ACR_PREFIX="${ACR_PREFIX:-crpi-zu4tna9y8drenzc4.cn-hangzhou.personal.cr.aliyuncs.com/comic-website}"

# push_one <目标名:tag> <候选本地引用...>：按序找第一个存在的本地镜像 → 打 ACR tag → push
push_one() {
  local target="$1"; shift
  local src="" c
  for c in "$@"; do
    if docker image inspect "$c" >/dev/null 2>&1; then src="$c"; break; fi
  done
  if [ -z "$src" ]; then
    echo "!! 本地找不到可用于 $target 的镜像（候选：$*）"
    echo "   先拉一个官方名（如 docker pull ${target%%:*}），再重跑本脚本"
    exit 1
  fi
  echo "   $src  --tag+push-->  $ACR_PREFIX/$target"
  docker tag "$src" "$ACR_PREFIX/$target"
  docker push --quiet "$ACR_PREFIX/$target"
}

echo "-> 推送基础镜像到 ACR：$ACR_PREFIX"
push_one python:3.13-slim \
  python:3.13-slim \
  m.daocloud.io/docker.io/library/python:3.13-slim \
  docker.m.daocloud.io/library/python:3.13-slim
push_one nginx:alpine \
  nginx:alpine \
  m.daocloud.io/docker.io/library/nginx:alpine \
  docker.m.daocloud.io/library/nginx:alpine
push_one mysql:8.0 \
  mysql:8.0 \
  m.daocloud.io/docker.io/library/mysql:8.0 \
  docker.m.daocloud.io/library/mysql:8.0

echo
echo "OK  三个基础镜像已推送（各 Dockerfile 的 FROM 直接引用它们）"
echo "    服务器首次使用（私有仓库）先登录：docker login ${ACR_PREFIX%%/*}"
