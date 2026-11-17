"""把 Dify 的 compose 片段转成 comic 仓库内可直接用的形式。

为什么需要：Dify 的 46KB compose 里 90% 是按 profile 关闭的向量库，
直接用会导致路径（./volumes、./envs）在 comic 仓库里解析错位。
这里只挑**实际在跑**的服务，把路径重写成仓库内相对路径，输出独立片段文件。

用法：python tools/gen_dify_compose.py
输出：deploy/docker-compose.dify.yml
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
DIFY_COMPOSE = Path(r"D:\software\RuoYi\dify\docker\docker-compose.yaml")
OUT = REPO / "deploy" / "docker-compose.dify.yml"

#: 实际在跑的服务（其余都是 profile 关闭的可选组件，不纳入）
SERVICES = [
    "init_permissions", "api", "api_websocket", "worker", "worker_beat", "web",
    "db_postgres", "redis", "weaviate", "sandbox", "local_sandbox",
    "plugin_daemon", "ssrf_proxy", "agent_ssrf_proxy", "agent_backend", "nginx",
]

#: 数据目录：本地默认指向 Dify 原目录（零拷贝），服务器上用环境变量覆盖
VOLUMES_ENV = "${DIFY_VOLUMES:-../../dify/docker/volumes}"


def running_container_names() -> dict[str, str]:
    """推导当前容器名（compose 规则：<project>-<service>-1，下划线原样保留）。

    不去调 `docker ps`：本脚本可能在受限环境里跑，访问不到 Docker Desktop 的命名管道。
    现状项目名是 `docker`，所以直接按规则算即可，迁移后容器名保持不变。
    """
    return {svc: f"docker-{svc}-1" for svc in SERVICES}


def rewrite_path(p: str) -> str:
    """把 Dify 目录相对路径映射到 comic 仓库内（配置）或数据目录（卷）。"""
    if p.startswith("./volumes/"):
        return p.replace("./volumes/", VOLUMES_ENV + "/", 1)
    if p.startswith("./envs/"):
        return p.replace("./envs/", "./dify/envs/", 1)
    if p.startswith("./nginx/"):
        return p.replace("./nginx/", "./dify/nginx/", 1)
    if p.startswith("./ssrf_proxy/"):
        return p.replace("./ssrf_proxy/", "./dify/ssrf_proxy/", 1)
    if p.startswith("./certbot/"):
        return p.replace("./certbot/", "./dify/certbot/", 1)
    if p == "./.env":
        return "./dify/.env"
    return p


def main() -> int:
    src = yaml.safe_load(DIFY_COMPOSE.read_text(encoding="utf-8"))
    names = running_container_names()

    out = {"services": {}, "networks": {}, "volumes": {}}
    for svc in SERVICES:
        conf = src["services"].get(svc)
        if conf is None:
            print(f"  ⚠ 源文件缺少服务 {svc}", file=sys.stderr)
            continue
        conf = json.loads(json.dumps(conf))  # 深拷贝

        # 容器名固定成现状，迁移后 docker exec / 脚本引用不变
        if svc in names:
            conf["container_name"] = names[svc]

        # env_file 路径重写（字符串或 {path: ...} 两种写法都要处理）
        files = conf.get("env_file")
        if files:
            new_files = []
            for f in files:
                if isinstance(f, str):
                    new_files.append(rewrite_path(f))
                elif isinstance(f, dict) and "path" in f:
                    new_files.append({**f, "path": rewrite_path(f["path"])})
            conf["env_file"] = new_files

        # bind mounts 路径重写
        if conf.get("volumes"):
            vols = []
            for v in conf["volumes"]:
                if isinstance(v, str) and (v.startswith("./") or v.startswith("../")):
                    src_path, _, rest = v.partition(":")
                    vols.append(rewrite_path(src_path) + ":" + rest)
                else:
                    vols.append(v)
            conf["volumes"] = vols

        # depends_on 里引用的服务如果没纳入，会导致 "depends on undefined service"
        dep = conf.get("depends_on")
        if dep:
            if isinstance(dep, dict):
                conf["depends_on"] = {k: v for k, v in dep.items() if k in SERVICES}
            else:
                conf["depends_on"] = [d for d in dep if d in SERVICES]
            if not conf["depends_on"]:
                conf.pop("depends_on")

        out["services"][svc] = conf

    # 网络：原样搬过来（agents/ssrf 需要独立网络）
    used = set()
    for conf in out["services"].values():
        nets = conf.get("networks")
        if isinstance(nets, dict):
            used.update(nets.keys())
        elif isinstance(nets, list):
            used.update(nets)
    for net in src.get("networks", {}):
        if net in used:
            out["networks"][net] = src["networks"][net] or {}

    # 命名卷：声明为 external，复用已有的 docker_* 卷，避免生成新卷丢数据
    for vol in ("dify_agent_local_sandbox_home", "dify_agent_local_sandbox_workspace"):
        out["volumes"][vol] = {
            "external": True,
            "name": f"docker_{vol}",
        }

    header = (
        "# 由 tools/gen_dify_compose.py 生成，请勿手改。\n"
        "# 源：../dify/docker/docker-compose.yaml（Dify 1.19.0），仅保留实际在跑的 16 个服务。\n"
        "# 数据目录通过 DIFY_VOLUMES 覆盖（默认指向原 Dify 目录，零拷贝迁移）。\n"
    )
    OUT.write_text(header + yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    print(f"  已生成 {OUT.relative_to(REPO)}  ({OUT.stat().st_size // 1024} KB, {len(out['services'])} 个服务)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
