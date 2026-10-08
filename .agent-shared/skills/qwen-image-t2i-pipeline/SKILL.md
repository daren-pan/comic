---
name: qwen-image-t2i-pipeline
description: >-
  基于 qwen-image-3.0-pro 的图片生成流水线，**双模式**：
  ① 文生图（T2I）——看图写 prompt 生成新图，用于风格转换、重新生成、按参考图出新图；
  ② 图生图（I2I）——用户发图并明确要求"以该图为底图修改/增加细节/保留原图主体"时，
  在保留原图内容的基础上编辑。
  两种模式都走本包自带的直连脚本 `qwen-image.py`（**不经过 MCP**，理由见下）。
  核心原则：按用户意图选模式 —— **以图为底图改 → I2I；换风格/重画 → T2I**。
when_to_use: >-
  命中任一即触发：
  (a) 风格转换——"把 X 图的风格改成 Y 风格/和 Z 图一致""把这个图换成 xx 画风"；
  (b) 看图生图——"根据这张图生成一张 xx 的图"；
  (c) 图片描述→生成——用户提供一张或多张参考图，要求生成风格统一的新图；
  (d) **图生图/细节增强（必须走 I2I）**——用户发图并说"以这个图为底图修改/增加
  细节/完善/补全/换装/换背景/保持主体修改局部"等，只要语义是"在保留这张图内容的
  基础上编辑"，就走 I2I；
  (e) 纯文字文生图（无参考图）→ T2I。
version: 2.0.0
---

## 先决条件：用直连脚本，不走 MCP

两种模式统一入口：**本包自带的 `qwen-image.py`**。

> ⚠️ **脚本路径按实际位置调整** —— 它**不在本 skill 目录里**，而在配套包的 `script/` 下
> （`.agent-shared/script/qwen-image.py`）。下面用 `<脚本路径>` 占位：把 skill 装到别的 agent 后，
> 换成**该脚本的实际路径**（相对 / 绝对都行，取决于调用时的工作目录）。

```bash
# T2I 文生图（不给 --image 就是 T2I）
python <脚本路径>/qwen-image.py --prompt "<英文 prompt>" --size 1024*1024 --out <输出目录>

# I2I 图生图（给 --image 就是 I2I）
python <脚本路径>/qwen-image.py --image <底图> --prompt "<英文指令>" \
  --negative "<反向词>" --size 1024*1024 --out <输出目录>
```

- **底图**可传本地路径（脚本转 base64）或公网 URL —— 服务端只认这两种；
- **API Key** 按 `--key` → 环境变量 `DASHSCOPE_API_KEY` → `~/.workbuddy/mcp.json` 的顺序自动找；
- **输出**按 `{YYYYMMDD-HHMMSS}-{批次}-{序号}.png` 落到 `--out`。

> ⚠️ **为什么绕开 MCP**：MCP 的 `edit_image`（I2I）**必然超时** —— 服务端
> `qwen_image_mcp/server.py` 的读超时 `IMAGE_GEN_TIMEOUT` 默认只有 **120s**，
> 而 I2I 实测要 **200~230s**，超时后重试 2 次并报 `API 调用失败，已重试 2 次`
> （报错还会被 MCP 的表格格式化截断，看着像"说不清的错误"）。
> 既然 I2I 必须绕开，干脆**两种模式都用脚本**，行为一致、只维护一处。

---

## 模式选择（第一步必须判断）

```
用户发图 + 指令语义是"以这个图为底图修改/增加细节/完善/补全/换局部"
        │
        ▼
   走 I2I 图生图（--image）：保留原图主体，按指令编辑
        │
        ▼
   不是上述语义（换风格/重画/风格统一/生成新图）
        │
        ▼
   走 T2I 文生图（不给 --image）：看图写 prompt 重新生成
```

**判定示例**：
- "以这个图为底图，增加背景细节" → **I2I**
- "把这个图的人物换身衣服" → **I2I**
- "把这张图的风格改成 GBF 风格" → **T2I**（重画）
- "帮我生成一张和这图风格一致的图" → **T2I**

⚠️ **最容易做错的一点**：用户说「以某图为底图改」时**不能**用 T2I 重画 ——
T2I 会让构图整个变样（实测连改多轮都"不像原来那张"），必须走 I2I。

---

## 模式一：I2I 图生图（以图为底图修改/增加细节）

**适用**：用户发图并明确要求以图为底图编辑，保留原图主体内容。

### ① 编辑指令怎么写

结构：**保留什么（原图主体细节逐项写明）+ 修改/增加什么（精确描述）+ 整体风格约束**

```
[保留主体] Keep everything EXACTLY the same: {形状 / 位置 / 比例 / 配色 / 风格逐项}
[编辑指令] ONLY CHANGE {要改的那一处 / 要增加的细节}
[质量词]   crisp clean edges, no text, no watermark
```

**反向提示词**：把你**不想它变**的东西塞进去 ——
`changed shape, changed composition, changed layout`（想保形时必加）。

要点：
- 指令用**英文**更精确（模型对英文风格词遵循更准）；中文版先展示在对话窗口（双语规则见下）；
- 局部修改要写清位置（`upper left` / `on the chest` / `in the background`）；
- 要「增加细节」用 `add fine details to ...` / `enrich ... with more detail`；
- 想**减少**已有元素时，别指望模型"删掉一些" —— 换**干净底图重做**更可控。

### ② 生成后必查

- 主体是否被顺手改掉（形状 / 配色 / 构图）；
- 若改了图，**用 Read 看一遍成图**再交付，别只看接口返回。

---

## 模式二：T2I 文生图（看图写 prompt 重新生成）

**适用**：换风格、重画、风格统一生成新图（用户发图仅作参考/描述来源）。

### ① 解析源图片（最重要的一步，决定成图质量）

用 Read 工具读取源图片，逐项记录画面细节，必须精确到可写入 prompt 的程度：

- **人物**：性别、年龄感、发型（单/双马尾、刘海、发色）、眼睛颜色与形状、表情
- **服装**：款式（长袍/裙装/盔甲）、颜色、配饰（腰带、胸针、披风、肩甲）、纹理
- **道具**：武器/法杖/工具的形状与顶部装饰（如太阳形、花形、宝石）
- **动作**：奔跑/站立/挥杖、裙摆/衣角状态
- **背景**：地形、天空（云、浮空岛）、光线
- **画风**：水彩/厚涂/赛璐璐/写实/低多边形等

### ② 设计 prompt（结构模板）

```
[风格宣言] An illustration in official {目标风格} style:
[主体]     a {age} {hair color} {subject} with {details}, {expression},
[服装道具] wearing {clothes} with {details}, holding {item},
[动作]     {action} through {scene},
[背景]     Background: {背景}，
[质感词]   flat vector / crisp clean edges / rich saturated colors,
           masterpiece quality, high detail
```

**双语规则（用户指定，必须遵守，两种模式通用）**：
1. 每次生成/编辑 prompt，**先把中文版完整展示在对话窗口**（逐项翻译：主体/风格/构图/反向词），让用户能看懂并确认；
2. **实际调用时用英文 prompt**；
3. 用户要求调整时，先展示修改后的中文版，确认后再调。

要点：
- **保留主体**：原图的形状/配色/构图必须逐项写进 prompt（这是"以 X 为底图"的关键）；
- **风格替换靠关键词**：把目标风格关键词写进 prompt，不要指望图生图自动迁移；
- **negative 必加**：把原图特征 / 不想要的东西放进去（如 `watermark, text, signature, low quality, blurry`）；
- **小图迭代再放大**：先出小图（如 `512*512`）确认构图，满意后同 prompt 出大图；
- **中文文案**：模型能写对、但**字号会失控**，务必给**可量化**约束（如"占图宽 45~50%、约 480px"），
  生成后用像素核验实际占比。

### ③ 调用

用上面的 `qwen-image.py`（不给 `--image`）。

---

## ④ 交付

- 按 `{时间戳}-{批次}-{序号}.png` 命名（脚本自动处理），时间戳由脚本用本地时间生成；
- 生成后用 **Read 看图核验**，再用 `present_files` 展示给用户。

---

## ⑤ 附加：把文字"生成"到图上（不要抠像素贴）

需求形态："把官方图上的角色名**弄到**改过动作/背景的图上相同位置"。

> ⚠️ 用 **I2I 把文字生成上去**，**不要**用代码抠原图像素再贴（走过弯路，已废弃）。

### 正确做法：双图参考 I2I

给 I2I 传 2 张图，让模型"看着样式照着写"：

- **图 1** = 底图：指令里写 `The first image is the base image to edit`；
- **图 2** = 文字样式参考：写 `The second image is a style reference for the character name text`。

> 注：本包脚本当前只接**单张**底图。需要双图参考时，改脚本的 `content` 数组多塞一项 `{"image": ...}` 即可
> （服务端支持 1–3 张）。

### 指令必须写清的三件事

1. **保留清单**（逐项列全，否则模型会顺手改掉）：人物姿势、背景元素、边框、星级行、画风配色；
2. **只加文字**：`ONLY ADD: the character name text in Chinese, exactly these characters XXXX in this order`，
   位置写清（如 `centered horizontally, just above the five golden stars`）；
3. **⚠️ 尺寸硬约束**（第一次极容易超宽，**必须写数值**）：
   ```
   IMPORTANT SIZE CONSTRAINT: the text must be SMALL and elegant, spanning only about
   45 to 50 percent of the image width (approximately 480 pixels wide), with a cap height
   of about 60 to 70 pixels, leaving generous empty space on the left and right sides.
   Do NOT make the text large or wide, do NOT let it fill the frame, do NOT overlap the
   subject.
   ```

### 实测结论

| 写法 | 名字宽/图宽 | 结果 |
|---|---|---|
| 只写 "same size proportion as reference" | **80.5%**（824px） | ❌ 过大 |
| 写入具体百分比 + 像素值 | **43.9%**（450px） | ✅ 与参考图一致 |

**结论：讲比例不写数值没用，必须给可量化约束。** 生成后用亮度掩码量实际占比（别凭肉眼）。
