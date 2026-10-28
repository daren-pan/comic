# .agent-shared —— 跨 agent 复用包

把**脚本、MCP 配置、技能、协作协议与角色卡**放在这里，换 agent
（Claude Code / Cursor / OpenCode / Codex …）时照着装回去即可。

```
.agent-shared/
├── README.md                    # 本文件（说明 + 用法）
├── agents/                      # ⭐ AI 协作协议 + 5 张角色卡（lead / design / dev / test / ops）
│   └── dev-delivery-team/       # ⭐ 「通用研发交付团队」专家团整包备份（plugin 格式，6 张卡）
├── script/
│   └── qwen-image.py            # ⭐ 直连脚本：T2I 文生图 + I2I 图生图（不走 MCP）
├── mcp/
│   └── playwright.json          # playwright 的 MCP 配置
└── skills/
    ├── qwen-image-t2i-pipeline/ # qwen-image 生图流水线（T2I / I2I 双模式）
    ├── start-dev/               # 本地开发环境启停（status / up / down / bootstrap）
    └── parse-requirement/       # 需求表 → 任务档案（依赖 scripts/parse-request.py）
```

## 怎么用

### AI 协作协议与角色卡（`agents/`）

本项目的**多角色协作规范**备份。源文件在 `.workbuddy/agents/`（该目录被 gitignore，不进版本库），
这里留一份可在换 agent / 换机器时恢复。

| 文件 | 内容 |
|---|---|
| `README.md` | 协作协议总纲：沟通拓扑、调度规范、上下文节流、派单巡检、产出模板 |
| `lead.md` | **负责人**：唯一对外接口，派单 / 中转 / 汇总；含「上下文节流」「派单巡检（看门狗）」硬规则 |
| `design.md` | 设计：出方案不写实现；**文件级白名单是硬产出**；回报 ≤15 行 |
| `dev.md` | 开发：按白名单改代码、自测、写 `03-impl.md` |
| `test.md` | 测试：独立验收、结论只能是「可交付 / 需修复」 |
| `ops.md` | 运维：发布或免上线（N/A 也要写原因） |

**恢复方式**：把 `agents/*.md` 拷回 `.workbuddy/agents/` 即可。

> ⚠️ 与 `skills/` 一样，**源在 `.workbuddy/agents/`**，这里是副本，改完要手动同步。

### 「通用研发交付团队」专家团（`agents/dev-delivery-team/`）

2026-10-28 从插件目录**整包**备份（`diff -r` 逐字节一致）。**别和上面那 5 张卡混用** ——
上面是 `.workbuddy/agents/` 时期的**手写角色卡**；这个子目录是 **plugin 格式的专家团**（带 `plugin.json` 清单、走专家中心加载）。

| 文件 | 内容 |
|---|---|
| `.codebuddy-plugin/plugin.json` | 插件清单 v1.0.0：团队成员、agent 文件映射、头像、快捷提示词 |
| `README.md` | 团队说明 |
| `agents/dev-delivery-team-lead.md` | 齐活林 · 交付总监：唯一对外接口，编排 P0~P7、核门禁、管权限 |
| `agents/product-manager.md` | 许清楚 · 产品经理：目标 / 范围 / 可判定验收 / 待拍板 |
| `agents/architect.md` | 高见远 · 架构与评审：画像 / 分层 / 接口契约 / 文件级白名单；**P2 与 P5 两次出场** |
| `agents/dev.md` | 谷可全 · 全栈工程师：界面规格 → 后端 → 前端 → 联调 → 自测 |
| `agents/qa-verifier.md` | 严过关 · 质量工程师：独立重跑、真浏览器 / 真接口取证，结论二选一 |
| `agents/release-ops.md` | 邵可稳 · 发布与文档：上线步骤 / 回滚 / 观测点 / 文档沉淀 |

**恢复方式**：整个目录拷回 `~/.workbuddy/plugins/marketplaces/my-experts/plugins/dev-delivery-team/`，
再在 WorkBuddy 专家中心重新加载该专家团。

> ⚠️ 同样是**单向副本**：源在 `~/.workbuddy/plugins/marketplaces/my-experts/`，改完源要重新同步这里。
> ℹ️ `avatars/` 原本只有 `.gitkeep`，`plugin.json` 引用的 6 张头像 PNG **在源目录里就不存在** —— 备份保持原样，未补图。

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

- `qwen-image-t2i-pipeline` —— 生图流水线，**跨项目通用**。
- `start-dev` —— 本仓库 `scripts/dev.sh` 的用法封装（启动前后端 / 查状态 / 停服务 / 补 python 环境）。
  它**绑定本项目**：命令依赖 `scripts/dev.sh`、`.python/` 与 `.venv`，换项目要改内容，不是拿来即用的通用技能。
- `parse-requirement` —— 把《需求登记表》xlsx 解析成任务档案（`docs/tasks/<ID>/` 的 `00-request` / `01-brief` / `state.json`）。
  **绑定本仓库**：依赖 `scripts/parse-request.py` 与 `docs/requirements/`。
  与 `start-dev` 不同，它**带前置自检**：用 `git rev-parse --show-toplevel` 找仓库根，找不到 `scripts/parse-request.py` 就判 `NOT_APPLICABLE` 并停止，所以装到别的项目也不会误操作。

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
