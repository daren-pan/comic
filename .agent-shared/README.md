# .agent-shared —— playwright / qwen-image 的跨 agent 复用包

把 **qwen-image 的直连脚本**与 **playwright 的 MCP 配置**放在这里，换 agent
（Claude Code / Cursor / OpenCode / Codex …）时照着装回去即可。

```
.agent-shared/
├── README.md                    # 本文件（说明 + 用法）
├── script/
│   └── qwen-image.py            # ⭐ 直连脚本：T2I 文生图 + I2I 图生图（不走 MCP）
├── mcp/
│   └── playwright.json          # playwright 的 MCP 配置
└── skills/
    └── qwen-image-t2i-pipeline/ # qwen-image 生图流水线（T2I / I2I 双模式）
```

## 怎么用

### qwen-image —— 直连脚本，**不用装 MCP**

> 下面的路径**相对于本包根目录**（`.agent-shared/`）；从别处调用时换成脚本的实际路径。

```bash
# T2I 文生图（不给 --image 就是 T2I）
python script/qwen-image.py --prompt "A modern minimalist app icon: ..." --size 1024*1024

# I2I 图生图（给 --image 就是 I2I）
python script/qwen-image.py --image 底图.png \
  --prompt "Keep everything EXACTLY the same, ONLY change the color scheme to ..." \
  --negative "changed shape, changed composition, text, watermark" \
  --size 1024*1024
```

- 底图可传**本地路径**（脚本转 base64）或**公网 URL**（直传）；
- API Key 自动按 `--key` → 环境变量 `DASHSCOPE_API_KEY` → `~/.workbuddy/mcp.json` 的顺序找；
- 输出按 `{YYYYMMDD-HHMMSS}-{批次}-{序号}.png` 落到 `--out` 目录。

**为什么不用 MCP**：MCP 的 `edit_image`（I2I）**必然超时** —— 服务端读超时默认 **120s**，
而 I2I 实测要 **200~230s**，超时后重试 2 次并报 `API 调用失败，已重试 2 次`。
既然 I2I 必须绕开 MCP，干脆 **T2I / I2I 都走脚本**，行为一致、只维护一处。

### playwright —— 装 MCP

把 `mcp/playwright.json` 的 `mcpServers` 合并进目标 agent 的 MCP 配置，替换占位符：

| 占位符 | 换成什么 |
|---|---|
| `<PLAYWRIGHT_OUT_DIR>` | 截图 / 快照的输出目录（**可写**即可） |

配置里用的是 `npx -y @playwright/mcp@latest --browser=msedge --output-dir=<目录>`
（用系统已有的 Edge，省去下载 Chromium）。

### skill

把 `skills/qwen-image-t2i-pipeline/` 整个目录拷到目标 agent 的 skill 目录
（WorkBuddy 是 `~/.workbuddy/skills/`；其他 agent 见各自的 skill 约定）。

## qwen-image 写 prompt 的经验

- 「以某图为底图改」**必须走 I2I**（给 `--image`）—— 用 T2I 重画会让构图整个变样；
- I2I 指令要把**保留项逐条写死**（形状 / 位置 / 比例 / 配色 / 风格），再写清**只改哪一处**；
- 反向提示词里塞进**不想它变的东西**（`changed shape, changed composition, changed layout`）；
- 想「减少」已有元素时，换**干净底图重做**比让模型「删掉一些」更可控；
- 中文文案模型能写对、但**字号会失控**，务必给可量化约束（比如占图宽百分之多少）。

## playwright 用法

典型流程：`browser_navigate` → `browser_resize`（移动端常用 393×852）→
`browser_console_messages` / `browser_network_requests` / `browser_snapshot` / `browser_take_screenshot`。

- ⚠️ 页面地址要用**框架的完整路由**：uni-app H5 是 `#/pages/login/index` 这种，写 `#/login` 会**白屏**；
- ⚠️ 前端问题**先实跑取证**（console / network / DOM），**别只读代码就断言"应该是 XX 问题"**。

## 注意

- **不落密钥**：脚本只从环境变量或本机 agent 配置里取 Key，仓库里没有任何真值。
- `skills/` 下的内容是**从 `~/.workbuddy/skills/` 复制**来的 —— 源更新后不会自动同步，需手动同步一份。
