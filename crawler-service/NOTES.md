# crawler-service · 知识库（AI 维护）

> 本文件是 crawler-service 的**踩坑与知识沉淀**，由 AI 协作时维护 ——
> **每次踩坑 / 实测 / 复盘写到这里**，不再写进 `README.md`（README 只放模块框架、约定与用途，给人看）。
> 具体逻辑由源码注释解释维护，这里只放「为什么」与「踩过的坑」。
> 各源站的接口 / 限流 / 已知坑仍写在各源子包的 `sources/<源名>/README.md`（就近维护）。

## 条目模板（新增知识时按此写）

```markdown
#### 标题（一句话说清是什么）

- **日期**：YYYY-MM-DD（多个用 ` / ` 分隔）
- **背景 / 现象**：发生了什么（决策类写"当时的背景"）
- **根因**：为什么会这样（决策类写"为什么这么定"）
- **结论**：怎么解决 / 最终决定是什么
- **实测**（可选）：关键数字 / 验证方式
- **位置**（可选）：涉及的文件 / 页面
```

同质清单用**表格**（列头即字段）；操作规程用**步骤结构**。

---

## 一、`status` 归一改造（2026-10-13，B 块）

### 1.1 四个源 adapter 改调统一函数

- **背景 / 现象**：`status` 此前**每个源各写一套转换**（见 `comic-core/NOTES.md` §1.1 的完整背景）。
- **结论**：四个源统一改调 `comic_core.status.normalize_status()`：

  | 源 | 改动 |
  |---|---|
  | `weebcentral` | 删私有 `STATUS_MAP`，改调归一函数 |
  | `mangadex` | 删 `_status_text()`，改调归一函数 |
  | `copymanga` | 保留 `display` 文本判定（源站特性），但输出换成规范值 |
  | `zaimanhua` | 两处透传点改调归一函数 |

- **位置**：`src/comic_crawler/sources/{weebcentral,mangadex,copymanga,zaimanhua}/adapter.py`。

### 1.2 ⚠️ 漏改的硬编码（测试红了才发现）

- **背景 / 现象**：改造后 crawler 测试 5 个失败。
- **根因**：`copymanga/adapter.py` 的 `_row_to_brief` 里有一处**硬编码 `status="连载"`**
  （列表页不给状态、默认值的兜底），改造时漏了。
- **结论**：全源 grep 确认无残留（`status="连载"` 这类字面量）；单测断言同步更新（见下）。
- **位置**：`copymanga/adapter.py` 的 `_row_to_brief`。

### 1.3 测试断言同步（5 处）

- **背景 / 现象**：4 个 adapter 测试文件里的状态断言期望**旧值**（`连载` / `完结`）。
- **结论**：更新为规范值（`连载中` / `已完结`）；新增 `tests/test_status.py`（10 例），
  含「休载 / 已取消**不得**被压进两值」这条与旧白名单划清界限的断言。

---

## 二、测试与门禁

### 2.1 ⚠️ `check.sh` 曾缺 `PYTHONPATH` → 21 个 ImportError

- **背景 / 现象**：`scripts/check.sh` 跑 crawler 测试时 21 个 `unittest.loader._FailedTest`
  —— 看起来像"测试挂了"，其实是环境没配好。
- **根因**：`comic_core` / `comic_crawler` **两个本地包并未安装进 venv**
  （site-packages 里没有任何 comic 相关文件或 `.pth`），只靠源码路径导入；
  脚本没设 `PYTHONPATH` → 测试模块在 import 阶段就失败。
- **结论**：修复为 `PYTHONPATH="src;../comic-core/src"`（2026-10-13，D 块一并修）。
  或改用 editable 安装一次：`.venv/Scripts/pip install -e ../comic-core -e .`。
- **位置**：`scripts/check.sh` 第 1 步。

### 2.2 测试套件规模（2026-10-13）

- **结论**：241 个测试（pipeline + adapters + 分层守卫 + 状态归一），纯逻辑不连库、不写临时文件。
  运行：`PYTHONPATH="src;../comic-core/src" ./.venv/Scripts/python.exe -m unittest discover -s tests`。

---

## 三、采集策略的历史决策

### 3.1 单轮最多翻 5 页（`MAX_PAGES_PER_SYNC` 50 → 5，2026-10-07）

- **背景 / 现象**：原先单轮最多翻 50 页；一页约 20 部 → 50 页 ≈ 1000 部，
  而每部都要抓详情 + 补齐缺失章节（一部可能几百章），一轮会跑极久。
- **根因**：页数上限同时约束"扫描量"与"详情抓取量"，50 页的上限形同虚设。
- **结论**：降到 **5 页**（≈100 部/轮）—— 增量 / 全量、有无水位一视同仁；要收更多就**分批**
  （把 `since` 定早一些、多跑几轮）。
- **实测 / 补充**：⚠️ **配套影响** —— 水位会推进到本轮完成时刻，所以窗口内超过 5 页的部分
  **这一轮收不到、下一轮也不会再进窗口**。想避免漏采：要么把 `since` 固定成一个较早的日期
  （每轮覆盖重扫，幂等），要么定期跑一轮把窗口放宽。
