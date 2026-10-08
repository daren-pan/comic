#!/usr/bin/env python3
"""qwen-image 直连脚本 —— **T2I（文生图）与 I2I（图生图）都走这里**，不经过 MCP。

## 为什么不用 MCP

MCP 的 `generate_image`（T2I）本来能用，但 `edit_image`（I2I）**必然超时**：
MCP 服务端（`qwen_image_mcp/server.py`）的读超时 `IMAGE_GEN_TIMEOUT` **默认只有 120s**，
而 I2I 实测要 200~230s，超时后会重试 2 次、最终报 `API 调用失败，已重试 2 次`
（报错还会被 MCP 的表格格式化截断，看着像"说不清的错误"）。

既然 I2I 必须绕开 MCP，干脆**两种模式都用本脚本**，行为一致、只需维护一处。

## 用法

    # T2I：文生图（不给 --image 就是 T2I）
    python qwen-image.py --prompt "A modern minimalist app icon: ..." --size 1024*1024

    # I2I：以某图为底图改（给 --image 就是 I2I）
    python qwen-image.py --image 底图.png \
        --prompt "Keep everything EXACTLY the same, ONLY change the color scheme to ..." \
        --negative "changed shape, changed composition, text, watermark" \
        --size 1024*1024

底图既可以是**本地文件**（脚本转 base64），也可以是**公网 URL**（直传）——
服务端只认这两种，**不认裸本地路径**。

## API Key 解析顺序

1. `--key` 显式传入
2. 环境变量 `DASHSCOPE_API_KEY`
3. `--key-file`（默认 `~/.workbuddy/mcp.json`）里的 `mcpServers.qwen-image.env.DASHSCOPE_API_KEY`

## 输出

按 `{YYYYMMDD-HHMMSS}-{批次}-{序号}.png` 存到 `--out` 目录，并打印保存路径与耗时。
"""

import argparse
import base64
import json
import mimetypes
import os
import pathlib
import sys
import time
import urllib.request

API = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
DEFAULT_KEY_FILE = pathlib.Path.home() / ".workbuddy" / "mcp.json"


def load_key(args):
    if args.key:
        return args.key
    env = os.environ.get("DASHSCOPE_API_KEY")
    if env:
        return env
    key_file = pathlib.Path(args.key_file).expanduser() if args.key_file else DEFAULT_KEY_FILE
    if key_file.exists():
        data = json.loads(key_file.read_text(encoding="utf-8"))
        key = (
            data.get("mcpServers", {})
            .get("qwen-image", {})
            .get("env", {})
            .get("DASHSCOPE_API_KEY")
        )
        if key:
            return key
    sys.exit(
        "未找到 DASHSCOPE_API_KEY：请用 --key 传入、设置环境变量，"
        "或确认 --key-file 里的 mcpServers.qwen-image.env.DASHSCOPE_API_KEY"
    )


def to_image_ref(src):
    """底图 → API 可接受的引用：公网 URL 直传，本地文件转 data URI。"""
    if src.startswith("http://") or src.startswith("https://"):
        return src
    path = pathlib.Path(src)
    if not path.exists():
        sys.exit("底图不存在：%s" % src)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode())


def call(key, prompt, image_ref, negative, size, n, model, seed=None):
    content = []
    if image_ref:
        content.append({"image": image_ref})
    content.append({"text": prompt})
    params = {
        "size": size,
        "n": n,
        "prompt_extend": True,
        # ⚠️ I2I 只支持 direct，传 agent 会被服务端拒绝；T2I 也用 direct 保持一致
        "prompt_extend_mode": "direct",
        "watermark": False,
    }
    if negative:
        params["negative_prompt"] = negative
    if seed is not None:
        params["seed"] = seed
    body = {
        "model": model,
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": params,
    }
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="qwen-image 直连（T2I 文生图 / I2I 图生图）—— 不经过 MCP"
    )
    parser.add_argument("--prompt", required=True, help="提示词 / 编辑指令（建议英文，模型对英文风格词遵循更准）")
    parser.add_argument("--image", default=None, help="底图（本地路径或公网 URL）；**给了就是 I2I，不给就是 T2I**")
    parser.add_argument("--negative", default=None, help="反向提示词")
    parser.add_argument("--size", default="1024*1024", help='输出尺寸，如 "1024*1024"')
    parser.add_argument("--n", type=int, default=1, help="生成数量 1-6")
    parser.add_argument("--out", default=".", help="输出目录")
    parser.add_argument("--batch", default="1", help="文件名里的批次号")
    parser.add_argument("--model", default="qwen-image-3.0-pro", help="模型名（默认 qwen-image-3.0-pro）")
    parser.add_argument("--key", default=None, help="直接指定 API Key")
    parser.add_argument("--key-file", default=None, help="从该 json 里读 Key（默认 ~/.workbuddy/mcp.json）")
    args = parser.parse_args()

    key = load_key(args)
    image_ref = to_image_ref(args.image) if args.image else None
    mode = "I2I 图生图" if image_ref else "T2I 文生图"

    print("[qwen-image] %s 提交中…（I2I 通常要 200s+，请耐心等）" % mode, flush=True)
    started = time.time()
    data = call(key, args.prompt, image_ref, args.negative, args.size, args.n, args.model)

    urls = [
        item["image"]
        for choice in data.get("output", {}).get("choices", [])
        for item in choice.get("message", {}).get("content", [])
        if item.get("image")
    ]
    if not urls:
        sys.exit("未返回图像：%s" % json.dumps(data, ensure_ascii=False)[:800])

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for index, url in enumerate(urls, 1):
        target = out_dir / ("%s-%s-%d.png" % (stamp, args.batch, index))
        with urllib.request.urlopen(url, timeout=180) as resp:
            target.write_bytes(resp.read())
        print("[qwen-image] 已保存 %s（总耗时 %.0fs）" % (target, time.time() - started), flush=True)


if __name__ == "__main__":
    main()
