# scripts · 知识库（AI 维护）

> 本文件是 scripts（启动 / 自检 / 打包脚本）的**踩坑与知识沉淀**，由 AI 协作时维护 ——
> **每次踩坑 / 实测 / 复盘写到这里**，不再写进 `README.md`。

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

---

## 一、门禁脚本（`check.sh`）

### 1.1 ⚠️ 缺 `PYTHONPATH` 会让 crawler 测试"看起来全挂"（2026-10-13 修复）

- **背景 / 现象**：脚本跑 crawler 测试时 21 个 `unittest.loader._FailedTest` ——
  看起来像"测试挂了"，其实是环境没配好。
- **根因**：`comic_core` / `comic_crawler` 两个本地包**并未安装进 venv**，只靠源码路径导入；
  脚本没设 `PYTHONPATH` → 测试模块在 import 阶段就失败。
- **结论**：第 1 步固定带 `PYTHONPATH="src;../comic-core/src"`。

### 1.2 门禁的演进（2026-10-13）

- **背景 / 现象**：原第 3 步在检查**已冻结的** comic-web 的 `tsc`（无实际意义）。
- **结论**：改为 —— ① crawler 单测 ② api 单测 ③ comic-front ESLint ④ comic-front vitest
  ⑤ comic-front `tsc --noEmit`（**纳入当天就抓到 `stores/message.ts` 一个真实缺字段错误**）。
  第 5 步只查 `.ts`（`tsc` 不认 `.vue`；模板类型要 vue-tsc，暂未纳入）。
